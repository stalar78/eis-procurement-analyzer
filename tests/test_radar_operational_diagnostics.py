import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("radar_diagnostics", ROOT / "scripts" / "radar_diagnostics.py")
diagnostics = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = diagnostics
SPEC.loader.exec_module(diagnostics)


def _write_report(path: Path, run_id: str, raw_cards: int, unique_cards: int, alerts: int, detail_unavailable: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "summary": {
                    "run_id": run_id,
                    "run_started": f"2026-08-12T10:0{raw_cards}:00+03:00",
                    "raw_cards": raw_cards,
                    "unique_cards": unique_cards,
                    "change_events": 2,
                    "alerts": alerts,
                    "detail_unavailable": detail_unavailable,
                    "verified_open": 1,
                    "verified_closed": 0,
                    "verified_cancelled": 0,
                    "errors": ["PAGE_BUDGET_REACHED"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_summarizes_runs_logs_and_lock_without_mutation(tmp_path: Path) -> None:
    _write_report(tmp_path / "outputs" / "radar" / "runs" / "run-a" / "latest.json", "run-a", 5, 4, 1, 3)
    _write_report(tmp_path / "outputs" / "radar" / "latest_attempt.json", "run-b", 2, 2, 0, 1)
    (tmp_path / "outputs" / "radar" / "radar.lock").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "outputs" / "radar" / "radar.lock").write_text("{}", encoding="utf-8")
    log_dir = tmp_path / "runtime-logs"
    log_dir.mkdir()
    (log_dir / "radar-20260812-100500.log").write_text(
        "WARNING:root:Карточка 1 на странице 1 не содержит номера или названия.\nPage crashed\n",
        encoding="utf-8",
    )
    (log_dir / "radar-20260812-100200.log").write_text("Preflight failed: missing config\n", encoding="utf-8")

    runs, aggregate = diagnostics.summarize_runs(tmp_path, limit=10)

    assert [run.run_id for run in runs] == ["run-a", "run-b"]
    assert aggregate["report_success_runs"] == 2
    assert aggregate["report_non_success_runs"] == 0
    assert aggregate["runs_with_failure_signals"] == 2
    assert aggregate["malformed_card_warnings"] == 1
    assert aggregate["page_crashes"] == 1
    assert aggregate["detail_unavailable"] == 4
    assert aggregate["cards_discovered"] == 6
    assert aggregate["alerts_emitted"] == 1
    assert aggregate["radar_lock_present"] is True
    assert (tmp_path / "outputs" / "radar" / "radar.lock").exists()


def test_tolerates_missing_and_partial_runtime_files(tmp_path: Path) -> None:
    partial = tmp_path / "outputs" / "radar" / "runs" / "partial" / "latest.json"
    partial.parent.mkdir(parents=True)
    partial.write_text("{not-json", encoding="utf-8")

    runs, aggregate = diagnostics.summarize_runs(tmp_path, limit=5)

    assert len(runs) == 1
    assert runs[0].result_status == "PARTIAL"
    assert aggregate["report_success_runs"] == 0
    assert aggregate["report_non_success_runs"] == 1
    assert aggregate["runs_with_failure_signals"] == 0


def test_deduplicates_latest_aliases_for_same_run_id(tmp_path: Path) -> None:
    _write_report(tmp_path / "outputs" / "radar" / "runs" / "run-a" / "latest.json", "run-a", 5, 4, 1, 3)
    _write_report(tmp_path / "outputs" / "radar" / "latest.json", "run-a", 5, 4, 1, 3)
    _write_report(tmp_path / "outputs" / "radar" / "latest_attempt.json", "run-a", 5, 4, 1, 3)

    runs, aggregate = diagnostics.summarize_runs(tmp_path, limit=10)

    assert [run.run_id for run in runs] == ["run-a"]
    assert aggregate["report_success_runs"] == 1
    assert aggregate["report_non_success_runs"] == 0
    assert aggregate["detail_unavailable"] == 3
    assert aggregate["cards_discovered"] == 4
    assert aggregate["alerts_emitted"] == 1


def test_render_has_deterministic_output_shape(tmp_path: Path) -> None:
    _write_report(tmp_path / "outputs" / "radar" / "runs" / "run-a" / "latest.json", "run-a", 5, 4, 1, 3)
    runs, aggregate = diagnostics.summarize_runs(tmp_path, limit=1)
    output = diagnostics.render(runs, aggregate)

    assert output.startswith("Radar Operational Diagnostics\nRuns:")
    assert "run_id=run-a" in output
    assert "verified=1/0/0" in output
    assert "Totals:" in output


def test_redacts_telegram_like_secrets_from_logs(tmp_path: Path) -> None:
    log = tmp_path / "radar-20260812-100500.log"
    log.write_text("RADAR_TELEGRAM_BOT_TOKEN=123:secret-token\n", encoding="utf-8")

    summary = diagnostics.summarize_log(log)
    rendered = diagnostics.redact_secrets("RADAR_TELEGRAM_CHAT_ID=999 bot123:secret")

    assert summary.malformed_card_warnings == 0
    assert "999" not in rendered
    assert "secret" not in rendered
