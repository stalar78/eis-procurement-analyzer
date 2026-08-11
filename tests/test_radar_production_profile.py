from pathlib import Path

from radar.config import PROJECT_ROOT, load_config
from radar.preflight import PREFLIGHT_EXIT_CODE, run_production_preflight
from radar.runner import run


def _write_config(tmp_path: Path, extra: str = "") -> Path:
    config = tmp_path / "radar.production.yaml"
    config.write_text(
        f"""
radar:
  output_dir: {tmp_path.as_posix()}/out
  database: {tmp_path.as_posix()}/data/radar.db
recurring:
  lock_stale_after_minutes: 120
  retain_successful_runs: 2
  retain_failed_runs: 2
telegram:
  enabled: false
  bot_token_env: RADAR_TEST_TELEGRAM_TOKEN
  chat_id_env: RADAR_TEST_TELEGRAM_CHAT
{extra}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def test_valid_production_preflight_creates_runtime_dirs(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    config = load_config(config_path)
    result = run_production_preflight(config_path, config)
    assert result.ok
    assert (tmp_path / "out").is_dir()
    assert (tmp_path / "data").is_dir()


def test_missing_telegram_env_fails_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RADAR_TEST_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("RADAR_TEST_TELEGRAM_CHAT", raising=False)
    config_path = _write_config(tmp_path, "  enabled: true\n")
    config = load_config(config_path)
    result = run_production_preflight(config_path, config)
    assert not result.ok
    assert any("RADAR_TEST_TELEGRAM_TOKEN" in item for item in result.sanitized_errors())
    assert any("RADAR_TEST_TELEGRAM_CHAT" in item for item in result.sanitized_errors())


def test_invalid_runtime_path_fails_preflight(tmp_path: Path) -> None:
    blocking_file = tmp_path / "not-a-dir"
    blocking_file.write_text("", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        f"""
radar:
  output_dir: {blocking_file.as_posix()}
  database: {tmp_path.as_posix()}/data/radar.db
""",
    )
    config = load_config(config_path)
    result = run_production_preflight(config_path, config)
    assert not result.ok
    assert any("output directory" in item for item in result.sanitized_errors())


def test_invalid_config_value_fails_preflight(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
recurring:
  lock_stale_after_minutes: 0
telegram:
  timeout_seconds: 0
""",
    )
    config = load_config(config_path)
    result = run_production_preflight(config_path, config)
    assert not result.ok
    assert "recurring.lock_stale_after_minutes must be positive" in result.sanitized_errors()
    assert "telegram.timeout_seconds must be positive" in result.sanitized_errors()


def test_production_mode_routes_through_recurring_orchestration(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    code = run(
        [
            "--production",
            "--config",
            str(config_path),
            "--offline-input",
            "tests/fixtures/radar_cards.json",
            "--as-of",
            "2026-08-04",
            "--all-profiles",
            "--no-history",
            "--no-enrich",
        ]
    )
    assert code == 0
    assert not (tmp_path / "out" / "radar.lock").exists()
    import sqlite3

    connection = sqlite3.connect(tmp_path / "data" / "radar.db")
    rows = connection.execute("SELECT status FROM recurring_run_lifecycle ORDER BY id").fetchall()
    connection.close()
    assert ("STARTED",) in rows
    assert ("SUCCESS",) in rows


def test_preflight_failure_exposes_no_secret_values(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
telegram:
  enabled: true
  bot_token: super-secret-token
  chat_id: ""
""",
    )
    config = load_config(config_path)
    result = run_production_preflight(config_path, config)
    joined = "\n".join(result.sanitized_errors())
    assert not result.ok
    assert "super-secret-token" not in joined


def test_preflight_only_returns_nonzero_without_starting_pipeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RADAR_TEST_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("RADAR_TEST_TELEGRAM_CHAT", raising=False)
    config_path = _write_config(tmp_path, "  enabled: true\n")
    code = run(["--preflight-only", "--config", str(config_path)])
    assert code == PREFLIGHT_EXIT_CODE
    assert not (tmp_path / "data" / "radar.db").exists()


def test_production_preflight_is_independent_from_current_working_directory(tmp_path: Path, monkeypatch) -> None:
    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()
    project_output = PROJECT_ROOT / "outputs" / "radar"
    project_data = PROJECT_ROOT / "data"
    monkeypatch.chdir(unrelated_cwd)

    code = run(["--production", "--preflight-only"])

    assert code == 0
    assert not (unrelated_cwd / "config" / "radar.production.yaml").exists()
    assert not (unrelated_cwd / "outputs" / "radar").exists()
    assert not (unrelated_cwd / "data").exists()
    assert project_output.exists()
    assert project_data.exists()
