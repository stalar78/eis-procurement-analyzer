from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus, NoCompetitionOpportunity, RadarAssessment, RadarDecision
from radar.opportunities import (
    assess_failed_opportunities,
    classify_failure_event,
    detect_opportunity_transitions,
    failure_competition_signal,
    load_failure_events,
    score_republication_relation,
    build_opportunity,
)
from radar.prefilter import parse_as_of
from radar.scoring import assess_card
from radar.search_profiles import SearchProfile
from radar.state import RadarState


def current_card() -> object:
    return normalize_card(
        {
            "procurement_number": "10000000000000000001",
            "title": "Development of citizen portal personal account and workflow API",
            "customer": "Fictional City Digital Department",
            "law": "44-FZ",
            "procedure_type": "Electronic auction",
            "nmck": 1800000,
            "region": "Fictional Region",
            "published_at": "2026-02-20T10:00:00+03:00",
            "application_deadline": "2026-03-01T10:00:00+03:00",
            "status_normalized": "APPLICATION_SUBMISSION",
            "source_url": "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=10000000000000000001",
            "raw_text": "portal personal account workflow API explicit reference 99000000000000000008",
        }
    )


def assessment(card, decision: RadarDecision = RadarDecision.PRIORITY) -> RadarAssessment:
    return RadarAssessment(
        procurement_number=card.procurement_number,
        eligibility_status=EligibilityStatus.OPEN,
        days_to_deadline=12,
        total_score=82,
        radar_decision=decision,
    )


def load_events():
    return load_failure_events("tests/fixtures/radar_opportunities")


def test_explicit_no_applications_detection() -> None:
    event = classify_failure_event({"procurement_number": "x", "failure_reason": "No applications were submitted.", "application_count": 0})
    assert event.failure_type == "NO_APPLICATIONS"
    assert event.evidence_confidence == "HIGH"


def test_completed_without_winner_does_not_imply_zero_applications() -> None:
    event = classify_failure_event({"procurement_number": "x", "failure_reason": "Completed, winner information is absent on the result page."})
    assert event.failure_type == "UNKNOWN_FAILURE"


def test_all_rejected_and_single_application_detection() -> None:
    rejected = classify_failure_event({"procurement_number": "x", "failure_reason": "All applications were rejected.", "application_count": 3, "admitted_application_count": 1})
    single = classify_failure_event({"procurement_number": "y", "failure_reason": "One application was submitted and admitted.", "application_count": 1, "admitted_application_count": 1})
    assert rejected.failure_type == "ALL_APPLICATIONS_REJECTED"
    assert single.failure_type == "SINGLE_APPLICATION"


def test_cancellation_and_contract_nonconclusion_are_not_no_competition_signals() -> None:
    cancelled = failure_competition_signal(classify_failure_event({"procurement_number": "x", "failure_reason": "Procedure was cancelled by the customer."}))
    not_concluded = failure_competition_signal(classify_failure_event({"procurement_number": "x", "failure_reason": "Contract was not concluded."}))
    assert cancelled[0] == 0
    assert not_concluded[0] == 0


def test_republication_scoring_components() -> None:
    config = RadarConfig()
    current = current_card()
    previous = classify_failure_event({"procurement_number": "99000000000000000008", "customer": current.customer, "title": current.title, "nmck": 1800000, "procedure_type": current.procedure_type, "region": current.region, "failure_reason": "No applications were submitted.", "application_count": 0, "completed_at": "2026-01-09T10:00:00+03:00"})
    link = score_republication_relation(current, previous, config)
    assert link.same_customer
    assert link.title_similarity > 0
    assert link.functional_similarity > 0
    assert link.budget_similarity >= 0
    assert link.procedure_similarity > 0
    assert link.region_similarity > 0
    assert link.relation_type in {"EXPLICIT_REPUBLICATION", "LIKELY_REPUBLICATION", "SAME_CUSTOMER_SIMILAR_SUBJECT"}


def test_publication_before_previous_failure_is_not_republication() -> None:
    config = RadarConfig()
    current = current_card()
    previous = classify_failure_event({"procurement_number": "x", "customer": current.customer, "title": current.title, "nmck": 1800000, "procedure_type": current.procedure_type, "region": current.region, "failure_reason": "No applications were submitted.", "application_count": 0, "completed_at": "2026-04-01T10:00:00+03:00"})
    link = score_republication_relation(current, previous, config)
    assert link.relation_type == "NOT_RELATED"


def test_explicit_reference_has_strong_confidence() -> None:
    config = RadarConfig()
    current = current_card()
    previous = classify_failure_event({"procurement_number": "99000000000000000008", "customer": current.customer, "title": current.title, "nmck": 1800000, "procedure_type": current.procedure_type, "region": current.region, "failure_reason": "No applications were submitted.", "application_count": 0, "completed_at": "2026-01-09T10:00:00+03:00"})
    link = score_republication_relation(current, previous, config)
    assert link.confidence == "HIGH"


def test_unrelated_or_weak_matches_are_lower_confidence() -> None:
    config = RadarConfig()
    current = current_card()
    unrelated = classify_failure_event({"procurement_number": "u", "customer": "Different Customer", "title": "Office paper delivery", "nmck": 90000, "procedure_type": "Purchase", "region": "Different Region", "failure_reason": "No applications were submitted.", "application_count": 0, "completed_at": "2026-01-01T10:00:00+03:00"})
    link = score_republication_relation(current, unrelated, config)
    assert link.relation_type in {"POSSIBLE_REPUBLICATION", "NOT_RELATED"}
    assert link.confidence in {"LOW", "MEDIUM"}


def test_opportunity_scoring_respects_technical_hard_reject_and_closed_status() -> None:
    config = RadarConfig()
    current = current_card()
    failure = classify_failure_event({"procurement_number": "99000000000000000008", "customer": current.customer, "title": current.title, "nmck": 1800000, "procedure_type": current.procedure_type, "region": current.region, "failure_reason": "No applications were submitted.", "application_count": 0, "completed_at": "2026-01-09T10:00:00+03:00"})
    link = score_republication_relation(current, failure, config)
    assessment_open = assessment(current)
    opp = build_opportunity(current, assessment_open, failure, link, config)
    assert opp.opportunity_score > 0
    assert "no-application" in " ".join(opp.positive_signals)
    hard_reject = assessment(current, RadarDecision.REJECT)
    hard_reject.hard_reject_reasons = ["technical blocker"]
    opp2 = build_opportunity(current, hard_reject, failure, link, config)
    assert opp2.opportunity_level in {"LOW", "REVIEW", "INSUFFICIENT_DATA"}
    assert opp2.technical_fit_signal == 0


def test_transition_and_sqlite_persistence(tmp_path: Path) -> None:
    config = RadarConfig()
    config.opportunities.enabled = True
    cards = [current_card()]
    assessments = [assessment(cards[0])]
    result = assess_failed_opportunities(cards, assessments, config, offline_failure_input="tests/fixtures/radar_opportunities")
    assert result.opportunities
    assert result.transitions
    state = RadarState(tmp_path / "radar.db")
    state.save_opportunity_assessment(
        algorithm_version="0.3.5-r3b-opportunities",
        failure_events=result.failure_events,
        republication_links=result.republication_links,
        opportunities=result.opportunities,
        transitions=result.transitions,
        detected_at="2026-08-10T12:00:00+03:00",
    )
    assert state.connection.execute("SELECT COUNT(*) FROM procurement_failure_events").fetchone()[0] >= 1
    assert state.connection.execute("SELECT COUNT(*) FROM opportunity_assessments").fetchone()[0] >= 1
    state.close()


def test_no_secret_or_local_paths_in_fixtures() -> None:
    raw = Path("tests/fixtures/radar_opportunities/failure_events.json").read_text(encoding="utf-8")
    lowered = raw.lower()
    assert "c:\\users\\" not in lowered
    assert "password" not in lowered
    assert "token" not in lowered
