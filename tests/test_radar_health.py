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


def _record_lifecycle(
    tmp_path: Path,
    *,
    run_id: str,
    status: str,
    finished_delta: timedelta | None = None,
    started_delta: timedelta | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    failure_reason: str | None = None,
) -> None:
    state = RadarState(tmp_path / "data" / "radar.db")
    now = datetime.now().astimezone()
    if finished_at is None and status != "STARTED":
        finished_at = (now - (finished_delta or timedelta())).isoformat(timespec="seconds")
    if started_at is None:
        if started_delta is not None:
            started_at = (now - started_delta).isoformat(timespec="seconds")
        elif finished_at:
            started_at = (datetime.fromisoformat(finished_at) - timedelta(minutes=5)).isoformat(timespec="seconds")
        else:
            started_at = now.isoformat(timespec="seconds")
    state.record_run_lifecycle(
        run_id=run_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at or "",
        failure_reason=failure_reason if failure_reason is not None else ("simulated failure" if status == "FAILED" else ""),
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


def test_health_fresh_started_with_recent_success_remains_healthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))
    _record_lifecycle(tmp_path, run_id="started", status="STARTED", started_delta=timedelta(minutes=30))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7", "--health-max-run-hours", "12"])

    output = capsys.readouterr().out
    assert code == HEALTHY_EXIT_CODE
    assert "Radar health: HEALTHY" in output
    assert "Latest lifecycle: STARTED started" in output
    assert "Latest STARTED age:" in output


def test_health_stale_started_with_recent_success_is_unhealthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))
    _record_lifecycle(tmp_path, run_id="started", status="STARTED", started_delta=timedelta(hours=13))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7", "--health-max-run-hours", "12"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "Radar health: UNHEALTHY" in output
    assert "latest STARTED run exceeded max run duration" in output


def test_health_stale_started_with_stale_success_is_unhealthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=9))
    _record_lifecycle(tmp_path, run_id="started", status="STARTED", started_delta=timedelta(hours=13))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7", "--health-max-run-hours", "12"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "Radar health: UNHEALTHY" in output
    assert "latest STARTED run exceeded max run duration" in output


def test_health_started_with_invalid_timestamp_is_unhealthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))
    _record_lifecycle(tmp_path, run_id="started", status="STARTED", started_at="not-a-time")

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7", "--health-max-run-hours", "12"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "Radar health: UNHEALTHY" in output
    assert "latest STARTED timestamp is invalid" in output


def test_health_unknown_latest_status_is_unhealthy(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))
    _record_lifecycle(tmp_path, run_id="paused", status="PAUSED")

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "7"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "Radar health: UNHEALTHY" in output
    assert "unknown latest lifecycle status: PAUSED" in output


def test_health_rejects_negative_max_age_hours(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "-1"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "--health-max-age-hours must be a finite value > 0" in output


def test_health_rejects_nan_max_age_hours(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "nan"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "--health-max-age-hours must be a finite value > 0" in output


def test_health_rejects_infinite_max_age_hours(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))

    code = run(["--health", "--config", str(config), "--health-max-age-hours", "inf"])

    output = capsys.readouterr().out
    assert code == UNHEALTHY_EXIT_CODE
    assert "--health-max-age-hours must be a finite value > 0" in output


def test_health_rejects_invalid_max_run_hours_values(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    _record_lifecycle(tmp_path, run_id="success", status="SUCCESS", finished_delta=timedelta(hours=1))

    for value in ["0", "-1", "nan", "inf", "-inf"]:
        code = run(["--health", "--config", str(config), f"--health-max-run-hours={value}"])
        output = capsys.readouterr().out
        assert code == UNHEALTHY_EXIT_CODE
        assert "--health-max-run-hours must be a finite value > 0" in output
