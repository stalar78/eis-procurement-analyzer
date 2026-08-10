from pathlib import Path

from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus
from radar.scoring import assess_card
from radar.state import RadarState


def test_new_procurement_is_saved_as_new(tmp_path: Path) -> None:
    state = RadarState(tmp_path / "radar.db")
    card = normalize_card({"procurement_number": "1", "title": "Разработка", "application_deadline": "2026-08-20"})
    flags = state.preview_flags([card])
    assert flags["1"] == (True, False)
    assessment = assess_card(card, EligibilityStatus.OPEN, 10, RadarConfig(), [], is_new=True)
    state.save_run("r1", "s", "f", "a", "0.1.0-r1", {}, [card], [assessment])
    assert state.preview_flags([card])["1"] == (False, False)
    state.close()


def test_changed_deadline_is_recorded(tmp_path: Path) -> None:
    state = RadarState(tmp_path / "radar.db")
    config = RadarConfig()
    original = normalize_card({"procurement_number": "1", "title": "Разработка", "application_deadline": "2026-08-20"})
    assessment = assess_card(original, EligibilityStatus.OPEN, 10, config, [], is_new=True)
    state.save_run("r1", "s", "f", "a", "0.1.0-r1", {}, [original], [assessment])
    changed = normalize_card({"procurement_number": "1", "title": "Разработка", "application_deadline": "2026-08-21"})
    assert state.preview_flags([changed])["1"] == (False, True)
    assessment2 = assess_card(changed, EligibilityStatus.OPEN, 11, config, [], is_changed=True)
    state.save_run("r2", "s", "f2", "a", "0.1.0-r1", {}, [changed], [assessment2])
    rows = state.connection.execute("SELECT field_name FROM changes").fetchall()
    assert ("deadline",) in [tuple(row) for row in rows]
    state.close()
