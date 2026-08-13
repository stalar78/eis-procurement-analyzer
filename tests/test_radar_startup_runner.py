from pathlib import Path

from radar.config import PROJECT_ROOT


def _read(name: str) -> str:
    return (PROJECT_ROOT / "scripts" / name).read_text(encoding="utf-8")


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


def test_background_loop_has_singleton_contract_and_continues_after_nonzero_radar_exit() -> None:
    text = _read("radar-background-loop.ps1")

    assert '$LoopLock = Join-Path $RuntimeLogDir "radar-background-loop.lock"' in text
    assert "Test-ProcessAlive" in text
    assert "exit 75" in text
    assert "$ExitCode = $LASTEXITCODE" in text
    assert "Radar production launcher exited with code $ExitCode." in text
    assert "do {" in text
    assert "} while ($true)" in text


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
