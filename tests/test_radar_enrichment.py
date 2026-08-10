from datetime import datetime
from pathlib import Path

from radar.artifact_registry import ArtifactRegistry, ensure_inside
from radar.config import RadarConfig
from radar.discovery import load_offline_cards
from radar.enrichment import run_enrichment, select_enrichment_candidates
from radar.models import EligibilityStatus, RadarDecision
from radar.prefilter import evaluate_eligibility, parse_as_of
from radar.scoring import assess_card
from radar.search_profiles import load_search_profiles
from radar.state import RadarState


def preliminary():
    config = RadarConfig()
    config.scoring.priority_threshold = 65
    profiles = load_search_profiles()
    cards = load_offline_cards("tests/fixtures/radar_cards.json")
    as_of = parse_as_of("2026-08-04", config.radar.timezone)
    assessments = []
    for card in cards:
        eligibility, days_left, reasons = evaluate_eligibility(card, as_of, config, profiles)
        assessments.append(assess_card(card, eligibility, days_left, config, profiles, is_new=True, eligibility_reasons=reasons))
    return config, cards, assessments


def test_only_priority_review_selected() -> None:
    config, cards, assessments = preliminary()
    plan = select_enrichment_candidates(cards, assessments, config, total_limit=10)
    selected = {item.procurement_number for item in plan.selected}
    assert selected
    for item in plan.selected:
        assert item.preliminary_decision in {RadarDecision.PRIORITY, RadarDecision.REVIEW}


def test_selection_respects_per_decision_and_total_limits() -> None:
    config, cards, assessments = preliminary()
    plan = select_enrichment_candidates(cards, assessments, config, total_limit=1, priority_limit=1, review_limit=0)
    assert len(plan.selected) == 1
    assert plan.selected[0].preliminary_decision == RadarDecision.PRIORITY


def test_closed_and_too_close_not_selected_by_default() -> None:
    config, cards, assessments = preliminary()
    plan = select_enrichment_candidates(cards, assessments, config, total_limit=20)
    selected = {item.procurement_number for item in plan.selected}
    assert "90000000000000000007" not in selected
    assert "90000000000000000008" not in selected


def test_explicit_override_works_with_force() -> None:
    config, cards, assessments = preliminary()
    plan = select_enrichment_candidates(
        cards,
        assessments,
        config,
        procurement_numbers=["90000000000000000004"],
        force_enrich=True,
        total_limit=5,
    )
    assert "90000000000000000004" in {item.procurement_number for item in plan.selected}


def test_cached_complete_enrichment_is_reused(tmp_path: Path) -> None:
    config, cards, assessments = preliminary()
    state = RadarState(tmp_path / "radar.db")
    result = run_enrichment(
        cards,
        assessments,
        config,
        state=state,
        offline_enrichment_input="tests/fixtures/radar_enrichment",
        total_limit=1,
    )
    state.save_enrichment_run("e1", "r1", "2026-08-04T00:00:00+03:00", "2026-08-04T00:01:00+03:00", 1, len(result.plan.selected), len(result.plan.skipped), result.diagnostics, config.enrichment.__dict__, cards, result.deep_assessments, result.artifacts)
    plan = select_enrichment_candidates(cards, assessments, config, total_limit=1, state=state, as_of=datetime.fromisoformat("2026-08-04T01:00:00+03:00"))
    assert any(item["reason_skipped"] == "cached complete enrichment is still fresh" for item in plan.skipped)
    state.close()


def test_partial_extraction_produces_partial_with_force() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(
        cards,
        assessments,
        config,
        offline_enrichment_input="tests/fixtures/radar_enrichment",
        procurement_numbers=["90000000000000000008"],
        force_enrich=True,
        total_limit=1,
    )
    deep = result.deep_assessments[0]
    assert deep.enrichment_status.value == "PARTIAL"
    assert deep.final_radar_decision == RadarDecision.INSUFFICIENT_DATA


def test_missing_tz_and_contract_produces_insufficient_data() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", procurement_numbers=["90000000000000000008"], force_enrich=True, total_limit=1)
    assert result.deep_assessments[0].final_radar_decision == RadarDecision.INSUFFICIENT_DATA


def test_unreadable_application_requirements_prevents_take_now() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", procurement_numbers=["90000000000000000008"], force_enrich=True, total_limit=1)
    deep = result.deep_assessments[0]
    assert deep.application_requirements_status == "unreadable"
    assert deep.final_radar_decision != RadarDecision.PRIORITY


def test_simple_tilda_website_receives_commodity_penalty() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", procurement_numbers=["90000000000000000002"], force_enrich=True, total_limit=1)
    deep = result.deep_assessments[0]
    assert deep.commodity_risk_confirmed
    assert deep.final_radar_decision != RadarDecision.PRIORITY


def test_medium_workflow_app_can_remain_priority() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", procurement_numbers=["90000000000000000001"], force_enrich=True, total_limit=1)
    assert result.deep_assessments[0].final_radar_decision == RadarDecision.PRIORITY


def test_mandatory_1c_produces_reject() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", procurement_numbers=["90000000000000000004"], force_enrich=True, total_limit=1)
    assert result.deep_assessments[0].final_radar_decision == RadarDecision.REJECT


def test_dry_run_performs_no_deep_analysis() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", dry_run=True, total_limit=2)
    assert result.plan.selected
    assert result.deep_assessments == []
    assert result.artifacts == []


def test_one_failure_does_not_stop_batch() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", procurement_numbers=["90000000000000000001", "90000000000000000011"], force_enrich=True, total_limit=2)
    assert len(result.deep_assessments) == 2
    assert any(item.error_code == "ANALYSIS_FAILED" for item in result.deep_assessments)


def test_preliminary_and_final_are_preserved() -> None:
    config, cards, assessments = preliminary()
    result = run_enrichment(cards, assessments, config, offline_enrichment_input="tests/fixtures/radar_enrichment", procurement_numbers=["90000000000000000001"], force_enrich=True, total_limit=1)
    deep = result.deep_assessments[0]
    assert deep.preliminary_decision
    assert deep.final_radar_decision
    assert deep.preliminary_score > 0


def test_artifact_paths_cannot_escape_procurement_directory(tmp_path: Path) -> None:
    registry = ArtifactRegistry(tmp_path)
    proc_dir = registry.procurement_dir("123")
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        ensure_inside(proc_dir, outside)
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal was not rejected")
