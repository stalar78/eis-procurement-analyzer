import json
from pathlib import Path

from radar.runner import run


def test_enriched_offline_report_contains_transitions(tmp_path: Path) -> None:
    output = tmp_path / "out"
    db = tmp_path / "radar.db"
    code = run(
        [
            "--offline-input",
            "tests/fixtures/radar_cards.json",
            "--offline-enrichment-input",
            "tests/fixtures/radar_enrichment",
            "--as-of",
            "2026-08-04",
            "--enrich",
            "--enrich-limit",
            "5",
            "--output",
            str(output),
            "--db",
            str(db),
            "--all-profiles",
        ]
    )
    assert code == 0
    payload = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert "decision_transitions" in payload["summary"]
    assert payload["items"][0]["preliminary_assessment"]
    assert "deep_assessment" in payload["items"][0]
    assert (output / "enrichment_plan.json").exists()

