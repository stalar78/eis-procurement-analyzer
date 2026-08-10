import json
from pathlib import Path

from radar.runner import run


def test_offline_report_is_created(tmp_path: Path) -> None:
    output = tmp_path / "out"
    db = tmp_path / "radar.db"
    code = run(
        [
            "--offline-input",
            "tests/fixtures/radar_cards.json",
            "--as-of",
            "2026-08-04",
            "--output",
            str(output),
            "--db",
            str(db),
            "--all-profiles",
        ]
    )
    assert code == 0
    assert (output / "latest.json").exists()
    assert (output / "latest.md").exists()
    assert (output / "latest.xlsx").exists()
    payload = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert payload["summary"]["unique_cards"] == 12


def test_dry_run_does_not_modify_db_or_latest(tmp_path: Path) -> None:
    output = tmp_path / "out"
    db = tmp_path / "radar.db"
    run(["--offline-input", "tests/fixtures/radar_cards.json", "--as-of", "2026-08-04", "--output", str(output), "--db", str(db), "--dry-run"])
    assert not db.exists()
    assert not (output / "latest.json").exists()
    assert list((output / "preview").glob("*/latest.json"))

