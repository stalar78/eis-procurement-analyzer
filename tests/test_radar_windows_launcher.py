import subprocess
from pathlib import Path

from radar.config import PROJECT_ROOT
from radar.preflight import PREFLIGHT_EXIT_CODE


def test_windows_launcher_command_shape_and_root_independence(tmp_path: Path, monkeypatch) -> None:
    unrelated = tmp_path / "cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    launcher = PROJECT_ROOT / "scripts" / "radar-production.cmd"
    text = launcher.read_text(encoding="utf-8")

    assert "%PROJECT_ROOT%\\.venv\\Scripts\\python.exe" in text
    assert "--production %*" in text
    assert "runtime-logs" in text
    completed = subprocess.run(
        ["cmd", "/c", str(launcher), "--preflight-only"],
        cwd=unrelated,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert (PROJECT_ROOT / "outputs" / "radar").exists()
    assert (PROJECT_ROOT / "data").exists()


def test_windows_launcher_preserves_preflight_exit_code(tmp_path: Path, monkeypatch) -> None:
    unrelated = tmp_path / "cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text(
        f"""
radar:
  output_dir: {tmp_path.as_posix()}/out
  database: {tmp_path.as_posix()}/db/radar.db
recurring:
  lock_stale_after_minutes: 0
""".strip(),
        encoding="utf-8",
    )
    launcher = PROJECT_ROOT / "scripts" / "radar-production.cmd"
    completed = subprocess.run(
        ["cmd", "/c", str(launcher), "--preflight-only", "--config", str(bad_config)],
        cwd=unrelated,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == PREFLIGHT_EXIT_CODE
    logs = sorted((PROJECT_ROOT / "runtime-logs").glob("radar-*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    assert logs
    latest_log = logs[0].read_text(encoding="utf-8")
    assert "lock_stale_after_minutes" in latest_log
    assert "RADAR_TELEGRAM" not in latest_log
    assert "token" not in latest_log.lower()


def test_launcher_preflight_only_does_not_duplicate_production_flag() -> None:
    launcher = PROJECT_ROOT / "scripts" / "radar-production.cmd"
    text = launcher.read_text(encoding="utf-8")
    assert '"%PYTHON_EXE%" -m radar.runner --production %*' in text


def test_root_level_validation_artifact_is_ignored_by_rule() -> None:
    rule = Path(".gitignore").read_text(encoding="utf-8")
    assert "RADAR_R3A1_LIVE_VALIDATION.md" in rule
