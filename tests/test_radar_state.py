from pathlib import Path

from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus, NoCompetitionOpportunity, ProcurementFailureEvent
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
    rows = state.connection.execute("SELECT change_type FROM changes").fetchall()
    assert ("NEW_PROCUREMENT",) in [tuple(row) for row in rows]
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


def test_repeated_identical_run_has_empty_change_feed(tmp_path: Path) -> None:
    state = RadarState(tmp_path / "radar.db")
    config = RadarConfig()
    card = normalize_card({"procurement_number": "1", "title": "Р Р°Р·СЂР°Р±РѕС‚РєР°", "application_deadline": "2026-08-20"})
    assessment = assess_card(card, EligibilityStatus.OPEN, 10, config, [], is_new=True)
    first = state.save_run("r1", "s", "f", "a", "0.4.0-r4a-change-feed", {}, [card], [assessment])
    second_assessment = assess_card(card, EligibilityStatus.OPEN, 10, config, [], is_new=False)
    second = state.save_run("r2", "s2", "f2", "a", "0.4.0-r4a-change-feed", {}, [card], [second_assessment])
    assert first["change_feed"]
    assert second["change_feed"] == []
    state.close()


def test_status_and_assessment_changes_are_recorded(tmp_path: Path) -> None:
    state = RadarState(tmp_path / "radar.db")
    config = RadarConfig()
    original = normalize_card({"procurement_number": "1", "title": "Р Р°Р·СЂР°Р±РѕС‚РєР°", "status_raw": "РџРѕРґР°С‡Р° Р·Р°СЏРІРѕРє", "nmck": 1_000_000})
    original.status_normalized = "application_submission"
    assessment = assess_card(original, EligibilityStatus.OPEN, 10, config, [], is_new=True)
    state.save_run("r1", "s", "f", "a", "0.4.0-r4a-change-feed", {}, [original], [assessment])
    changed = normalize_card({"procurement_number": "1", "title": "Р Р°Р·СЂР°Р±РѕС‚РєР°", "status_raw": "РћРїСЂРµРґРµР»РµРЅРёРµ РїРѕСЃС‚Р°РІС‰РёРєР° Р·Р°РІРµСЂС€РµРЅРѕ", "nmck": 2_000_000})
    changed.status_normalized = "closed"
    assessment2 = assess_card(changed, EligibilityStatus.CLOSED, None, config, [], is_changed=True)
    result = state.save_run("r2", "s2", "f2", "a", "0.4.0-r4a-change-feed", {}, [changed], [assessment2])
    event_types = {event["event_type"] for event in result["change_feed"]}
    assert {"STATUS_CHANGED", "NMCK_CHANGED", "PRELIMINARY_SCORE_CHANGED", "PRELIMINARY_DECISION_CHANGED"} <= event_types
    state.close()


def test_missing_previous_open_procurement_is_classified_closed(tmp_path: Path) -> None:
    state = RadarState(tmp_path / "radar.db")
    config = RadarConfig()
    first = normalize_card({"procurement_number": "1", "title": "РћРґРёРЅ", "status_normalized": "APPLICATION_SUBMISSION"})
    second = normalize_card({"procurement_number": "2", "title": "Р”РІР°", "status_normalized": "APPLICATION_SUBMISSION"})
    state.save_run("r1", "s", "f", "a", "0.4.0-r4a-change-feed", {}, [first, second], [assess_card(first, EligibilityStatus.OPEN, 10, config, [], is_new=True), assess_card(second, EligibilityStatus.OPEN, 10, config, [], is_new=True)])
    result = state.save_run("r2", "s2", "f2", "a", "0.4.0-r4a-change-feed", {}, [second], [assess_card(second, EligibilityStatus.OPEN, 10, config, [])])
    assert any(event["event_type"] == "PROCUREMENT_CLOSED" and event["procurement_number"] == "1" for event in result["change_feed"])
    state.close()


def test_opportunity_transition_feed_and_no_longer_active(tmp_path: Path) -> None:
    state = RadarState(tmp_path / "radar.db")
    opportunity = NoCompetitionOpportunity(current_procurement_number="1", previous_procurement_number="0", opportunity_score=60, opportunity_level="MEDIUM")
    first = state.save_opportunity_assessment(
        algorithm_version="test",
        failure_events=[ProcurementFailureEvent(procurement_number="0", failure_type="NO_APPLICATIONS")],
        republication_links=[],
        opportunities=[opportunity],
        transitions=[],
        detected_at="f",
        active_procurement_numbers=["1"],
    )
    second = state.save_opportunity_assessment(
        algorithm_version="test",
        failure_events=[],
        republication_links=[],
        opportunities=[],
        transitions=[],
        detected_at="f2",
        active_procurement_numbers=["1"],
    )
    assert any(event["event_type"] == "NEW_OPPORTUNITY" for event in first)
    assert any(event["event_type"] == "OPPORTUNITY_NO_LONGER_ACTIVE" for event in second)
    state.close()
