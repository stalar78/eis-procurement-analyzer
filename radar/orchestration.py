from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


SUCCESS_EXIT_CODE = 0
LOCKED_EXIT_CODE = 75
FAILURE_EXIT_CODE = 1


class RunLockedError(RuntimeError):
    def __init__(self, lock_path: Path, metadata: dict[str, Any]):
        self.lock_path = lock_path
        self.metadata = metadata
        super().__init__(f"recurring run lock is active: {lock_path}")


@dataclass
class RunLock:
    path: Path
    run_id: str
    acquired_at: datetime
    stale_recovered: bool = False

    def release(self) -> None:
        try:
            metadata = _read_lock_metadata(self.path)
            if metadata.get("run_id") == self.run_id:
                self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_lock_metadata(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def acquire_run_lock(
    output_dir: str | Path,
    run_id: str,
    acquired_at: datetime,
    stale_after_minutes: int,
) -> RunLock:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / "radar.lock"
    metadata = {
        "run_id": run_id,
        "pid": os.getpid(),
        "acquired_at": acquired_at.isoformat(timespec="seconds"),
    }
    stale_recovered = False
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(metadata, file, ensure_ascii=False, indent=2)
            return RunLock(path=path, run_id=run_id, acquired_at=acquired_at, stale_recovered=stale_recovered)
        except FileExistsError:
            existing = _read_lock_metadata(path)
            acquired_raw = existing.get("acquired_at")
            try:
                existing_at = datetime.fromisoformat(acquired_raw) if acquired_raw else datetime.fromtimestamp(path.stat().st_mtime, tz=acquired_at.tzinfo)
            except (OSError, ValueError):
                existing_at = datetime.fromtimestamp(0, tz=acquired_at.tzinfo)
            if existing_at.tzinfo is None and acquired_at.tzinfo is not None:
                existing_at = existing_at.replace(tzinfo=acquired_at.tzinfo)
            if acquired_at - existing_at <= timedelta(minutes=stale_after_minutes):
                raise RunLockedError(path, existing)
            path.unlink(missing_ok=True)
            stale_recovered = True


def retain_runtime_runs(output_dir: str | Path, retain_successful: int, retain_failed: int) -> dict[str, Any]:
    base = Path(output_dir)
    removed = {
        "successful_run_dirs_removed": [],
        "failed_run_dirs_removed": [],
    }
    removed["successful_run_dirs_removed"] = _trim_run_dirs(base / "runs", retain_successful)
    removed["failed_run_dirs_removed"] = _trim_run_dirs(base / "runs_failed", retain_failed)
    return removed


def _trim_run_dirs(root: Path, keep: int) -> list[str]:
    if keep < 0 or not root.exists():
        return []
    dirs = [item for item in root.iterdir() if item.is_dir() and not item.name.endswith(".tmp")]
    dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    removed: list[str] = []
    for item in dirs[keep:]:
        shutil.rmtree(item)
        removed.append(item.name)
    return removed
