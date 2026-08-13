from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MALFORMED_CARD_WARNING = "не содержит номера или названия"
PAGE_CRASH_MARKER = "Page crashed"
PREFLIGHT_MARKER = "Preflight failed"
SECRET_PATTERNS = [
    re.compile(r"bot\d+:[A-Za-z0-9_-]+"),
    re.compile(r"(RADAR_TELEGRAM_BOT_TOKEN=)[^\s]+"),
    re.compile(r"(RADAR_TELEGRAM_CHAT_ID=)[^\s]+"),
]


@dataclass
class RuntimeLogSummary:
    path: str
    timestamp: str
    malformed_card_warnings: int = 0
    page_crashes: int = 0
    preflight_failures: int = 0


@dataclass
class RunSummary:
    run_id: str
    timestamp: str
    result_status: str
    raw_cards: int = 0
    unique_cards: int = 0
    change_events: int = 0
    alerts: int = 0
    detail_unavailable: int = 0
    verified_open: int = 0
    verified_closed: int = 0
    verified_cancelled: int = 0
    discovery_errors: list[str] | None = None
    malformed_card_warnings: int = 0
    page_crashes: int = 0
    preflight_failures: int = 0
    source_path: str = ""


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(1) + "<redacted>" if match.lastindex else "<redacted>", redacted)
    return redacted


def summarize_log(path: Path) -> RuntimeLogSummary:
    try:
        text = redact_secrets(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        text = ""
    timestamp = path.stem.removeprefix("radar-")
    return RuntimeLogSummary(
        path=str(path),
        timestamp=timestamp,
        malformed_card_warnings=text.count(MALFORMED_CARD_WARNING),
        page_crashes=text.count(PAGE_CRASH_MARKER),
        preflight_failures=text.count(PREFLIGHT_MARKER),
    )


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def summarize_report(path: Path) -> RunSummary:
    payload = load_json(path)
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    run_id = str(summary.get("run_id") or path.parent.name)
    timestamp = str(summary.get("run_started") or summary.get("as_of") or run_id)
    errors = summary.get("errors", [])
    if not isinstance(errors, list):
        errors = [str(errors)]
    result_status = "SUCCESS" if summary else "PARTIAL"
    return RunSummary(
        run_id=run_id,
        timestamp=timestamp,
        result_status=result_status,
        raw_cards=_as_int(summary.get("raw_cards")),
        unique_cards=_as_int(summary.get("unique_cards")),
        change_events=_as_int(summary.get("change_events")),
        alerts=_as_int(summary.get("alerts")),
        detail_unavailable=_as_int(summary.get("detail_unavailable")),
        verified_open=_as_int(summary.get("verified_open")),
        verified_closed=_as_int(summary.get("verified_closed")),
        verified_cancelled=_as_int(summary.get("verified_cancelled")),
        discovery_errors=[str(item) for item in errors],
        source_path=str(path),
    )


def find_report_paths(output_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    runs_dir = output_dir / "runs"
    if runs_dir.exists():
        candidates.extend(path / "latest.json" for path in runs_dir.iterdir() if path.is_dir())
    candidates.extend([output_dir / "latest_attempt.json", output_dir / "latest.json"])
    existing = [path for path in candidates if path.exists()]
    unique: dict[str, Path] = {}
    for path in existing:
        unique[str(path.resolve())] = path
    return list(unique.values())


def summarize_runs(project_root: Path, limit: int = 10) -> tuple[list[RunSummary], dict[str, int | bool]]:
    output_dir = project_root / "outputs" / "radar"
    logs = [summarize_log(path) for path in sorted((project_root / "runtime-logs").glob("radar-*.log"), key=lambda item: item.name, reverse=True)]
    runs = [summarize_report(path) for path in find_report_paths(output_dir)]
    runs.sort(key=lambda item: item.timestamp, reverse=True)
    distinct_runs: list[RunSummary] = []
    seen_run_ids: set[str] = set()
    for run in runs:
        key = run.run_id or run.source_path
        if key in seen_run_ids:
            continue
        seen_run_ids.add(key)
        distinct_runs.append(run)
    selected = distinct_runs[:limit]
    for index, run in enumerate(selected):
        if index < len(logs):
            run.malformed_card_warnings = logs[index].malformed_card_warnings
            run.page_crashes = logs[index].page_crashes
            run.preflight_failures = logs[index].preflight_failures
    aggregate = {
        "report_success_runs": sum(1 for run in selected if run.result_status == "SUCCESS"),
        "report_non_success_runs": sum(1 for run in selected if run.result_status != "SUCCESS"),
        "runs_with_failure_signals": sum(1 for run in selected if run.preflight_failures > 0 or run.page_crashes > 0),
        "malformed_card_warnings": sum(run.malformed_card_warnings for run in selected),
        "page_crashes": sum(run.page_crashes for run in selected),
        "detail_unavailable": sum(run.detail_unavailable for run in selected),
        "cards_discovered": sum(run.unique_cards for run in selected),
        "alerts_emitted": sum(run.alerts for run in selected),
        "radar_lock_present": (output_dir / "radar.lock").exists(),
    }
    return selected, aggregate


def render(runs: list[RunSummary], aggregate: dict[str, int | bool]) -> str:
    lines = ["Radar Operational Diagnostics", "Runs:"]
    for run in runs:
        errors = "; ".join(run.discovery_errors or []) if run.discovery_errors else "-"
        lines.append(
            " | ".join(
                [
                    f"{run.timestamp}",
                    f"run_id={run.run_id}",
                    f"status={run.result_status}",
                    f"raw_cards={run.raw_cards}",
                    f"unique_cards={run.unique_cards}",
                    f"change_events={run.change_events}",
                    f"alerts={run.alerts}",
                    f"detail_unavailable={run.detail_unavailable}",
                    f"verified={run.verified_open}/{run.verified_closed}/{run.verified_cancelled}",
                    f"errors={errors}",
                    f"malformed_warnings={run.malformed_card_warnings}",
                    f"page_crashes={run.page_crashes}",
                    f"preflight_failures={run.preflight_failures}",
                ]
            )
        )
    lines.append("Totals:")
    for key in [
        "report_success_runs",
        "report_non_success_runs",
        "runs_with_failure_signals",
        "malformed_card_warnings",
        "page_crashes",
        "detail_unavailable",
        "cards_discovered",
        "alerts_emitted",
        "radar_lock_present",
    ]:
        lines.append(f"{key}={aggregate[key]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize recent local Radar runtime diagnostics.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--limit", "-n", type=int, default=10)
    args = parser.parse_args(argv)
    runs, aggregate = summarize_runs(Path(args.root), max(0, args.limit))
    print(render(runs, aggregate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
