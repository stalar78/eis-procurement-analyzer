from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus, NoCompetitionOpportunity, RadarAssessment, RadarDecision
from radar.opportunities import (
    assess_failed_opportunities,
    assess_failure_history,
    build_failure_query_plan,
    classify_failure_event,
    discover_failure_history,
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


def test_failure_query_plan_has_fallback_when_customer_missing() -> None:
    config = RadarConfig()
    card = normalize_card(
        {
            "procurement_number": "1",
            "title": "Portal personal account workflow API development",
            "status_normalized": "COMPLETED",
            "raw_text": "Portal personal account workflow API development",
        }
    )
    plan = build_failure_query_plan(card, config)
    assert plan
    assert plan[0]["mode"] == "FAILED_ONLY"


def test_discover_failure_history_distinguishes_zero_results_from_query_errors(tmp_path: Path) -> None:
    config = RadarConfig()
    config.opportunities.failure_history.maximum_queries_per_procurement = 1
    config.opportunities.failure_history.maximum_result_resolutions = 0
    card = current_card()

    def collector(_request, _config, _limit, _pages):
        return []

    result = discover_failure_history(card, config, collector=collector, cache_dir=tmp_path)
    assert result.diagnostics_summary["raw_cards"] == 0
    assert result.diagnostics_summary["query_errors"] == 0
    assert result.diagnostics_summary["zero_result_queries"] == 1
    assert "ZERO_RESULTS" in result.diagnostics[0].warnings


def test_failure_discovery_uses_failure_history_lookback_window(tmp_path: Path) -> None:
    config = RadarConfig()
    config.opportunities.failure_history.lookback_days = 365
    config.opportunities.failure_history.maximum_queries_per_procurement = 1
    config.opportunities.failure_history.maximum_result_resolutions = 0
    captured = {}

    def collector(request, _config, _limit, _pages):
        captured["published_from"] = request.published_from
        captured["published_to"] = request.published_to
        captured["mode"] = request.discovery_mode
        return []

    discover_failure_history(
        current_card(),
        config,
        as_of=datetime(2026, 8, 11, tzinfo=ZoneInfo("Europe/Moscow")),
        collector=collector,
        cache_dir=tmp_path,
    )
    assert captured == {"published_from": "11.08.2025", "published_to": "11.08.2026", "mode": "FAILED_ONLY"}


def test_assess_failure_history_collects_live_failure_events(tmp_path: Path) -> None:
    config = RadarConfig()
    config.opportunities.failure_history.maximum_queries_per_procurement = 1
    config.opportunities.failure_history.maximum_result_resolutions = 1
    card = current_card()
    current = normalize_card(
        {
            "procurement_number": "20000000000000000001",
            "title": card.title,
            "customer": card.customer,
            "law": "44-FZ",
            "procedure_type": card.procedure_type,
            "region": card.region,
            "status_raw": "Определение поставщика завершено",
            "status_normalized": "COMPLETED",
            "nmck": 1750000,
            "source_url": "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=20000000000000000001",
            "published_at": "2026-01-01T10:00:00+03:00",
            "updated_at": "2026-01-05T10:00:00+03:00",
        }
    )

    def collector(_request, _config, _limit, _pages):
        return [current]

    def fetch(_url: str):
        return "Цена контракта 10 000 руб. Участников 1. Победитель ООО Тест"

    result = assess_failure_history(card, assessment(card), config, collector=collector, result_fetch=fetch, cache_dir=tmp_path)
    assert result.failure_events
    assert result.failure_events[0].failure_type == "SINGLE_APPLICATION"
    assert result.diagnostics_summary["result_resolution_attempts"] == 1
