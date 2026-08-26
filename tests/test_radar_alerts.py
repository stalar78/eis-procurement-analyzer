from datetime import datetime
from pathlib import Path
import json

from radar.alerts import NEW_PROCUREMENT_ALERT_REASON, alert_fingerprint, build_alert_feed
from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus, RadarAssessment, RadarDecision
from radar.runner import run
from radar.state import RadarState


def _card(number: str = "1", title: str = "Разработка портала", nmck: float = 1_000_000, deadline: str = "2026-08-25") -> object:
    return normalize_card(
        {
            "procurement_number": number,
            "title": title,
            "customer": "Департамент",
            "law": "44-FZ",
            "procedure_type": "Электронный аукцион",
            "nmck": nmck,
            "application_deadline": deadline,
            "status_normalized": "APPLICATION_SUBMISSION",
        }
    )


def _assessment(card, decision: RadarDecision = RadarDecision.REVIEW, score: int = 60) -> RadarAssessment:
    return RadarAssessment(
        procurement_number=card.procurement_number,
        eligibility_status=EligibilityStatus.OPEN,
        days_to_deadline=10,
        total_score=score,
        radar_decision=decision,
    )


def test_new_priority_procurement_is_promoted() -> None:
    config = RadarConfig()
    card = _card("1")
    assessment = _assessment(card, RadarDecision.PRIORITY, 82)
    alerts = build_alert_feed(
        [
            {
                "procurement_number": card.procurement_number,
                "event_type": "NEW_PROCUREMENT",
                "detected_at": "2026-08-11T10:00:00+03:00",
                "previous_value": "",
                "current_value": card.procurement_number,
                "explanation": "new procurement detected",
            }
        ],
        [card],
        [assessment],
        config,
        datetime.fromisoformat("2026-08-11T10:00:00+03:00"),
    )
    assert alerts and alerts[0]["alert_priority"] == "HIGH"
    assert alerts[0]["alert_type"] == "INTERESTING_NEW_PROCUREMENT"
    assert alerts[0]["reason"] == NEW_PROCUREMENT_ALERT_REASON
    assert alerts[0]["score"] == 82
    assert alerts[0]["radar_decision"] == "PRIORITY"


def test_new_procurement_preserves_transition_values_and_fingerprint() -> None:
    config = RadarConfig()
    card = _card("32616324790")
    assessment = _assessment(card, RadarDecision.REVIEW, 59)
    event = {
        "procurement_number": card.procurement_number,
        "event_type": "NEW_PROCUREMENT",
        "detected_at": "2026-08-11T10:00:00+03:00",
        "previous_value": "",
        "current_value": card.procurement_number,
        "explanation": "procurement changed from '' to '32616324790'",
    }
    alerts = build_alert_feed([event], [card], [assessment], config, datetime.fromisoformat("2026-08-11T10:00:00+03:00"))

    assert alerts[0]["reason"] == NEW_PROCUREMENT_ALERT_REASON
    assert alerts[0]["previous_value"] == ""
    assert alerts[0]["current_value"] == "32616324790"
    assert alerts[0]["event_types"] == ["NEW_PROCUREMENT"]
    assert alerts[0]["source_events"] == [event]
    assert alerts[0]["fingerprint"] == alert_fingerprint(alerts[0])


def test_noisy_event_is_suppressed() -> None:
    config = RadarConfig()
    card = _card("1")
    alerts = build_alert_feed(
        [
            {
                "procurement_number": card.procurement_number,
                "event_type": "NMCK_CHANGED",
                "detected_at": "2026-08-11T10:00:00+03:00",
                "previous_value": "1000000",
                "current_value": "1001000",
                "explanation": "minor change",
            }
        ],
        [card],
        [_assessment(card)],
        config,
        datetime.fromisoformat("2026-08-11T10:00:00+03:00"),
    )
    assert alerts == []


def test_priority_transition_and_urgent_deadline_are_promoted() -> None:
    config = RadarConfig()
    card = _card("1", deadline="2026-08-12")
    alerts = build_alert_feed(
        [
            {
                "procurement_number": card.procurement_number,
                "event_type": "PRELIMINARY_DECISION_CHANGED",
                "detected_at": "2026-08-11T10:00:00+03:00",
                "previous_value": "REVIEW",
                "current_value": "PRIORITY",
                "explanation": "decision upgraded",
            },
            {
                "procurement_number": card.procurement_number,
                "event_type": "DEADLINE_CHANGED",
                "detected_at": "2026-08-11T10:00:00+03:00",
                "previous_value": "2026-08-20",
                "current_value": "2026-08-12",
                "explanation": "deadline became urgent",
            },
        ],
        [card],
        [_assessment(card)],
        config,
        datetime.fromisoformat("2026-08-11T10:00:00+03:00"),
    )
    assert len(alerts) == 1
    assert alerts[0]["alert_priority"] == "HIGH"
    assert "PRIORITY" in alerts[0]["reason"] or "urgent" in alerts[0]["reason"]


def test_deduplicates_multiple_raw_changes_into_single_alert() -> None:
    config = RadarConfig()
    card = _card("1", nmck=1_000_000)
    alerts = build_alert_feed(
        [
            {"procurement_number": "1", "event_type": "NMCK_CHANGED", "detected_at": "2026-08-11T10:00:00+03:00", "previous_value": "1000000", "current_value": "1400000", "explanation": "nmck jump"},
            {"procurement_number": "1", "event_type": "DEADLINE_CHANGED", "detected_at": "2026-08-11T10:00:00+03:00", "previous_value": "2026-08-20", "current_value": "2026-08-12", "explanation": "urgent deadline"},
        ],
        [card],
        [_assessment(card)],
        config,
        datetime.fromisoformat("2026-08-11T10:00:00+03:00"),
    )
    assert len(alerts) == 1
    assert alerts[0]["event_types"]


def test_repeated_identical_run_does_not_reemit_alerts(tmp_path: Path) -> None:
    output = tmp_path / "out"
    db = tmp_path / "radar.db"
    args = [
        "--offline-input",
        "tests/fixtures/radar_cards.json",
        "--as-of",
        "2026-08-04",
        "--output",
        str(output),
        "--db",
        str(db),
        "--all-profiles",
        "--recurring",
    ]
    assert run(args) == 0
    first_alerts = (output / "alert_feed.json").read_text(encoding="utf-8")
    assert run(args) == 0
    assert (output / "alert_feed.json").read_text(encoding="utf-8") == "[]"
    state = RadarState(db)
    rows = state.connection.execute("SELECT COUNT(*) FROM alert_history").fetchone()[0]
    assert rows == len(json.loads(first_alerts))
    state.close()
