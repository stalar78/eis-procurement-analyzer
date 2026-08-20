import json
import sys
import subprocess
import time
from pathlib import Path

import pytest

from radar.config import PROJECT_ROOT


WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell and cmd.exe")


def _read(name: str) -> str:
    return (PROJECT_ROOT / "scripts" / name).read_text(encoding="utf-8")


def _copy_loop_fixture(tmp_path: Path, launcher_body: str) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "runtime-logs").mkdir()
    loop = scripts / "radar-background-loop.ps1"
    loop.write_text(_read("radar-background-loop.ps1"), encoding="utf-8")
    (scripts / "radar-production.cmd").write_text(launcher_body, encoding="utf-8")
    return loop


def _run_loop(loop: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(loop), *args],
        cwd=loop.parent.parent,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _start_loop(loop: Path, *args: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(loop), *args],
        cwd=loop.parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_file(path: Path, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _launcher(exit_code: int = 0, sleep_seconds: int = 0) -> str:
    lines = [
        "@echo off",
        "set ROOT=%~dp0..",
        "echo run>> \"%ROOT%\\runtime-logs\\launcher-runs.txt\"",
    ]
    if sleep_seconds:
        lines.append(f"powershell -NoProfile -Command \"Start-Sleep -Seconds {sleep_seconds}\"")
    lines.append(f"exit /b {exit_code}")
    return "\n".join(lines) + "\n"


def _powershell_pid() -> int:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "$PID"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(completed.stdout.strip())


def test_background_loop_resolves_project_root_from_script_location() -> None:
    text = _read("radar-background-loop.ps1")

    assert '$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path' in text
    assert '$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path' in text
    assert '$Launcher = Join-Path $ProjectRoot "scripts\\radar-production.cmd"' in text


def test_background_loop_uses_three_hour_default_interval_and_launcher_args() -> None:
    text = _read("radar-background-loop.ps1")

    assert "[int]$IntervalSeconds = 10800" in text
    assert "& $Launcher --send-telegram-alerts" in text
    assert "Start-Sleep -Seconds $IntervalSeconds" in text


@WINDOWS_ONLY
def test_background_loop_continues_after_nonzero_radar_exit(tmp_path: Path) -> None:
    loop = _copy_loop_fixture(tmp_path, _launcher(exit_code=22))
    completed = _run_loop(loop, "-RunOnce")

    log = (tmp_path / "runtime-logs" / "radar-background-loop.log").read_text(encoding="utf-8")
    assert completed.returncode == 0
    assert "Radar production launcher exited with code 22." in log


@WINDOWS_ONLY
def test_two_concurrent_background_loops_have_one_owner_and_one_exit_75(tmp_path: Path) -> None:
    loop = _copy_loop_fixture(tmp_path, _launcher(sleep_seconds=3))
    first = _start_loop(loop, "-RunOnce")
    try:
        _wait_for_file(tmp_path / "runtime-logs" / "radar-background-loop.lock")
        second = _run_loop(loop, "-RunOnce", timeout=10)
        assert second.returncode == 75
        assert (tmp_path / "runtime-logs" / "radar-background-loop.lock").exists()
        assert first.wait(timeout=10) == 0
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=5)

    assert not (tmp_path / "runtime-logs" / "radar-background-loop.lock").exists()
    assert (tmp_path / "runtime-logs" / "launcher-runs.txt").read_text(encoding="utf-8").count("run") == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"pid": 999999, "process_start_time": "2020-01-01T00:00:00.0000000Z", "owner_token": "dead"},
        "{not-json",
    ],
)
@WINDOWS_ONLY
def test_dead_or_malformed_loop_lock_is_recovered(tmp_path: Path, payload) -> None:
    loop = _copy_loop_fixture(tmp_path, _launcher())
    lock = tmp_path / "runtime-logs" / "radar-background-loop.lock"
    if isinstance(payload, dict):
        lock.write_text(json.dumps(payload), encoding="utf-8")
    else:
        lock.write_text(payload, encoding="utf-8")

    completed = _run_loop(loop, "-RunOnce")

    assert completed.returncode == 0
    assert not lock.exists()
    assert (tmp_path / "runtime-logs" / "launcher-runs.txt").exists()


@WINDOWS_ONLY
def test_pid_reuse_mismatched_owner_metadata_is_recovered(tmp_path: Path) -> None:
    loop = _copy_loop_fixture(tmp_path, _launcher())
    lock = tmp_path / "runtime-logs" / "radar-background-loop.lock"
    lock.write_text(
        json.dumps(
            {
                "pid": _powershell_pid(),
                "process_start_time": "2020-01-01T00:00:00.0000000Z",
                "owner_token": "reused",
            }
        ),
        encoding="utf-8",
    )

    completed = _run_loop(loop, "-RunOnce")

    assert completed.returncode == 0
    assert not lock.exists()


@WINDOWS_ONLY
def test_live_matching_owner_rejects_second_runner(tmp_path: Path) -> None:
    loop = _copy_loop_fixture(tmp_path, _launcher(sleep_seconds=3))
    first = _start_loop(loop, "-RunOnce")
    try:
        _wait_for_file(tmp_path / "runtime-logs" / "radar-background-loop.lock")
        second = _run_loop(loop, "-RunOnce")
        assert second.returncode == 75
    finally:
        first.wait(timeout=10)


@WINDOWS_ONLY
def test_runner_removes_lock_only_when_it_still_owns_it(tmp_path: Path) -> None:
    loop = _copy_loop_fixture(tmp_path, _launcher(sleep_seconds=2))
    lock = tmp_path / "runtime-logs" / "radar-background-loop.lock"
    first = _start_loop(loop, "-RunOnce")
    try:
        _wait_for_file(lock)
        replacement = {"pid": 999999, "process_start_time": "2021-01-01T00:00:00.0000000Z", "owner_token": "other-owner"}
        lock.write_text(json.dumps(replacement), encoding="utf-8")
        assert first.wait(timeout=10) == 0
        assert json.loads(lock.read_text(encoding="utf-8")) == replacement
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=5)


@WINDOWS_ONLY
def test_run_once_removes_owned_lock_after_launcher_exits(tmp_path: Path) -> None:
    loop = _copy_loop_fixture(tmp_path, _launcher())
    lock = tmp_path / "runtime-logs" / "radar-background-loop.lock"

    completed = _run_loop(loop, "-RunOnce")

    assert completed.returncode == 0
    assert not lock.exists()


def test_startup_installer_uses_current_user_startup_shortcut_idempotently() -> None:
    text = _read("install-radar-startup.ps1")

    assert '[Environment]::GetFolderPath("Startup")' in text
    assert '$ShortcutPath = Join-Path $StartupDir "$EntryName.lnk"' in text
    assert "$Shell.CreateShortcut($ShortcutPath)" in text
    assert "$Shortcut.Save()" in text
    assert "-WindowStyle Hidden" in text
    assert '-File "{0}"' in text
    assert "radar-background-loop.ps1" in text


def test_startup_runner_scripts_do_not_embed_credentials_or_use_task_scheduler() -> None:
    combined = _read("radar-background-loop.ps1") + _read("install-radar-startup.ps1")
    forbidden = [
        "RADAR_TELEGRAM_BOT_TOKEN",
        "RADAR_TELEGRAM_CHAT_ID",
        "Get-Credential",
        "Register-ScheduledTask",
        "New-ScheduledTask",
        "-Password",
        "S4U",
        "InteractiveOrPassword",
    ]

    for marker in forbidden:
        assert marker not in combined
