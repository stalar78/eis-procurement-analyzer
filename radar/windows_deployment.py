from pathlib import Path

from radar.config import PROJECT_ROOT


def production_launcher_path(project_root: str | Path = PROJECT_ROOT) -> Path:
    return Path(project_root).resolve() / "scripts" / "radar-production.cmd"
