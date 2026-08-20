import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import radar.orchestration as orchestration
from radar.orchestration import FAILURE_EXIT_CODE, LOCKED_EXIT_CODE, SUCCESS_EXIT_CODE, retain_runtime_runs
from radar.runner import run


def _recurring_args(tmp_path: Path) -> list[str]:
    return [
        "--recurring",
        "--offline-input",
        "tests/fixtures/radar_cards.json",
        "--as-of",
        "2026-08-04",
        "--output",
        str(tmp_path / "out"),
        "--db",
        str(tmp_path / "radar.db"),
        "--all-profiles",
        "--no-history",
        "--no-enrich",
    ]


def _lifecycle_rows(db: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT * FROM recurring_run_lifecycle ORDER BY id"
    ).fetchall()
    connection.close()
    return rows


def test_successful_recurring_run_records_lifecycle_and_releases_lock(tmp_path: Path) -> None:
    code = run(_recurring_args(tmp_path))
    assert code == SUCCESS_EXIT_CODE
    assert (tmp_path / "out" / "latest.json").exists()
    assert not (tmp_path / "out" / "radar.lock").exists()
    rows = _lifecycle_rows(tmp_path / "radar.db")
    assert [row["status"] for row in rows[-2:]] == ["STARTED", "SUCCESS"]
    assert rows[-1]["status"] == "SUCCESS"
    assert rows[-1]["finished_at"]


def test_overlapping_recurring_run_is_skipped_by_lock(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    lock = out / "radar.lock"
    lock.write_text(
        json.dumps(
                {
                    "run_id": "active",
                    "pid": os.getpid(),
                    "acquired_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            ),
        encoding="utf-8",
    )
    code = run(_recurring_args(tmp_path))
    assert code == LOCKED_EXIT_CODE
    assert lock.exists()
    rows = _lifecycle_rows(tmp_path / "radar.db")
    assert rows[-1]["status"] == "SKIPPED_LOCKED"
    assert rows[-1]["failure_reason"] == "active recurring run lock"


def test_live_pid_keeps_fresh_lock_active(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    lock = out / "radar.lock"
    lock.write_text(
        json.dumps(
            {
                "run_id": "active",
                "pid": 456,
                "acquired_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestration, "_windows_pid_status", lambda pid: True)

    code = run(_recurring_args(tmp_path))

    assert code == LOCKED_EXIT_CODE
    assert lock.exists()


def test_dead_pid_recovers_fresh_lock_immediately(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    lock = out / "radar.lock"
    lock.write_text(
        json.dumps(
            {
                "run_id": "orphan",
                "pid": 456,
                "acquired_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestration, "_windows_pid_status", lambda pid: False)

    code = run(_recurring_args(tmp_path))

    assert code == SUCCESS_EXIT_CODE
    assert not lock.exists()


def test_malformed_pid_falls_back_to_age_based_recovery_only(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    lock = out / "radar.lock"
    fresh = datetime.now().astimezone()
    lock.write_text(
        json.dumps({"run_id": "broken", "pid": "not-a-number", "acquired_at": fresh.isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
    called: list[int] = []
    monkeypatch.setattr(orchestration, "_windows_pid_status", lambda pid: called.append(pid) or None)

    code = run(_recurring_args(tmp_path))

    assert code == LOCKED_EXIT_CODE
    assert lock.exists()
    assert called == []


def test_stale_lock_is_recovered_and_run_succeeds(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    stale_at = datetime.now().astimezone() - timedelta(minutes=10)
    (out / "radar.lock").write_text(
        json.dumps({"run_id": "stale", "pid": 123, "acquired_at": stale_at.isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
    code = run(_recurring_args(tmp_path) + ["--lock-stale-minutes", "1"])
    assert code == SUCCESS_EXIT_CODE
    assert not (out / "radar.lock").exists()
    rows = _lifecycle_rows(tmp_path / "radar.db")
    assert rows[-1]["status"] == "SUCCESS"
    diagnostics = json.loads(rows[-1]["diagnostics_json"])
    assert diagnostics["stale_lock_recovered"] is True


def test_dead_pid_orphan_lock_is_released_after_successful_run(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    lock = out / "radar.lock"
    lock.write_text(
        json.dumps(
            {
                "run_id": "orphan",
                "pid": 456,
                "acquired_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestration, "_windows_pid_status", lambda pid: False)

    code = run(_recurring_args(tmp_path))

    assert code == SUCCESS_EXIT_CODE
    assert not lock.exists()


def test_failed_recurring_run_preserves_last_success_and_next_run_recovers(tmp_path: Path) -> None:
    assert run(_recurring_args(tmp_path)) == SUCCESS_EXIT_CODE
    latest_before = (tmp_path / "out" / "latest.json").read_text(encoding="utf-8")
    failed_code = run(
        [
            "--recurring",
            "--enrichment-only",
            "--output",
            str(tmp_path / "out"),
            "--db",
            str(tmp_path / "radar.db"),
        ]
    )
    assert failed_code == FAILURE_EXIT_CODE
    assert (tmp_path / "out" / "latest.json").read_text(encoding="utf-8") == latest_before
    assert not (tmp_path / "out" / "radar.lock").exists()
    rows = _lifecycle_rows(tmp_path / "radar.db")
    assert rows[-1]["status"] == "FAILED"
    assert "--enrichment-only currently requires --offline-input" in rows[-1]["failure_reason"]

    assert run(_recurring_args(tmp_path)) == SUCCESS_EXIT_CODE
    rows = _lifecycle_rows(tmp_path / "radar.db")
    assert rows[-1]["status"] == "SUCCESS"


def test_runtime_retention_removes_only_old_run_dirs(tmp_path: Path) -> None:
    runs = tmp_path / "out" / "runs"
    failed = tmp_path / "out" / "runs_failed"
    runs.mkdir(parents=True)
    failed.mkdir(parents=True)
    for root in (runs, failed):
        for index in range(4):
            item = root / f"run_{index}"
            item.mkdir()
            (item / "latest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "out" / "latest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "out" / "latest.md").write_text("", encoding="utf-8")

    removed = retain_runtime_runs(tmp_path / "out", retain_successful=2, retain_failed=1)

    assert len(removed["successful_run_dirs_removed"]) == 2
    assert len(removed["failed_run_dirs_removed"]) == 3
    assert (tmp_path / "out" / "latest.json").exists()
    assert (tmp_path / "out" / "latest.md").exists()
    assert len([item for item in runs.iterdir() if item.is_dir()]) == 2
    assert len([item for item in failed.iterdir() if item.is_dir()]) == 1
