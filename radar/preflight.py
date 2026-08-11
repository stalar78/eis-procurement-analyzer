from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from radar.config import RadarConfig


PREFLIGHT_EXIT_CODE = 78


@dataclass
class PreflightResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def sanitized_errors(self) -> list[str]:
        return [sanitize_preflight_message(item) for item in self.errors]


def run_production_preflight(config_path: str | Path, config: RadarConfig, *, create_dirs: bool = True) -> PreflightResult:
    errors: list[str] = []
    path = Path(config_path)
    if not path.exists() or not path.is_file():
        errors.append(f"config is not readable: {path.name}")
    else:
        try:
            path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"config is not readable: {path.name}: {type(exc).__name__}")

    if config.recurring.lock_stale_after_minutes <= 0:
        errors.append("recurring.lock_stale_after_minutes must be positive")
    if config.recurring.retain_successful_runs < 0:
        errors.append("recurring.retain_successful_runs must be non-negative")
    if config.recurring.retain_failed_runs < 0:
        errors.append("recurring.retain_failed_runs must be non-negative")
    if config.telegram.timeout_seconds <= 0:
        errors.append("telegram.timeout_seconds must be positive")
    if config.telegram.max_retries < 0:
        errors.append("telegram.max_retries must be non-negative")
    if config.telegram.retry_backoff_seconds < 0:
        errors.append("telegram.retry_backoff_seconds must be non-negative")
    if config.telegram.max_message_chars <= 0:
        errors.append("telegram.max_message_chars must be positive")

    errors.extend(_ensure_writable_parent(Path(config.radar.database), "SQLite parent directory", create_dirs=create_dirs))
    errors.extend(_ensure_writable_dir(Path(config.radar.output_dir), "output directory", create_dirs=create_dirs))

    if config.telegram.enabled:
        token_present = bool(os.getenv(config.telegram.bot_token_env) or config.telegram.bot_token)
        chat_present = bool(os.getenv(config.telegram.chat_id_env) or config.telegram.chat_id)
        if not token_present:
            errors.append(f"Telegram bot token is missing: set {config.telegram.bot_token_env}")
        if not chat_present:
            errors.append(f"Telegram chat id is missing: set {config.telegram.chat_id_env}")

    return PreflightResult(ok=not errors, errors=errors)


def sanitize_preflight_message(message: str) -> str:
    lowered = message.lower()
    if "token=" in lowered or "password" in lowered or "secret" in lowered:
        return "preflight error contains sensitive value and was redacted"
    return message


def _ensure_writable_parent(path: Path, label: str, *, create_dirs: bool) -> list[str]:
    return _ensure_writable_dir(path.parent, label, create_dirs=create_dirs)


def _ensure_writable_dir(path: Path, label: str, *, create_dirs: bool) -> list[str]:
    try:
        if create_dirs:
            path.mkdir(parents=True, exist_ok=True)
        if not path.exists() or not path.is_dir():
            return [f"{label} is not a directory"]
        with tempfile.NamedTemporaryFile(prefix=".radar_preflight_", dir=path, delete=True):
            pass
    except OSError as exc:
        return [f"{label} is not writable: {type(exc).__name__}"]
    return []
