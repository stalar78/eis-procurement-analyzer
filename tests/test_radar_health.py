from datetime import datetime, timedelta
from pathlib import Path

from radar.runner import HEALTHY_EXIT_CODE, STALE_HEALTH_EXIT_CODE, UNHEALTHY_EXIT_CODE, run
from radar.state import RadarState


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "radar.health.yaml"
    config.write_text(
        f"""
radar:
  output_dir: {tmp_path.as_posix()}/out
  database: {tmp_path.as_posix()}/data/radar.db
telegram:
  enabled: false
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def _record_lifecycle(tmp_path: Path, *, run_id: str, status: str, finished_delta: timedelta | None = None) -> None:
    state = RadarState(tmp_path / "data" / "radar.db")
    now = datetime.now().astimezone()
    finished_at = now - (finished_delta or timedelta())
    state.record_run_lifecycle(
        run_id=run_id,
        status=status,
        started_at=(finished_at - timedelta(minutes=5)).isoformat(timespec="seconds"),
        finished_at=finished_at.isoformat(timespec="seconds"),
        failure_reason="simulated failure" if status == "FAILED" else "",
    )
    state.close()


def test_health_recent_success_is_healthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7"])

    output = capsys.readouterr().out
    assert code == HEALTHY_EXIT_CODE
    assert "Radar health: HEALTHY" in output
    assert "Latest lifecycle: SUCCESS success" in output


def test_health_old_success_is_stale(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="old-success", status="SUCCESS", finished_delta=timedelta(hours=9))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7"])

    output = capsys.readouterr().out
    assert code == STALE_HEALTH_EXIT_CODE
    assert "Radar health: STALE" in output


def test_health_without_success_is_unhealthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="failed", status="FAILED")

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "Radar health: UNHEALTHY" in output
    assert "no successful recurring run recorded" in output


def test_health_latest_failed_after_recent_success_is_unhealthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))
    _record_lifecycle(tmp_path, run_id="failed", status="FAILED")

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "Radar health: UNHEALTHY" in output
    assert "latest lifecycle status is FAILED" in output


def test_health_config_resolution_works_outside_project_cwd(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7"])

    output = capsys.readouterr().out
    assert code == HEALTHY_EXIT_CODE
    assert "Radar health: HEALTHY" in output
    assert not (elsewhere / "data").exists()
