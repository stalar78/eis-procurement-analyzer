from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from radar.config import PROJECT_ROOT


@dataclass(frozen=True)
class TaskSchedulerCommand:
    program_script: str
    arguments: str
    start_in: str


def production_launcher_path(project_root: str | Path = PROJECT_ROOT) -> Path:
    return Path(project_root).resolve() / "scripts" / "radar-production.cmd"


def task_scheduler_command(*, preflight_only: bool = False, project_root: str | Path = PROJECT_ROOT) -> TaskSchedulerCommand:
    args = "--preflight-only" if preflight_only else ""
    return TaskSchedulerCommand(
        program_script=str(production_launcher_path(project_root)),
        arguments=args,
        start_in="",
    )
