from pathlib import Path

from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.historical import (
    assess_dumping_risk,
    apply_history_to_assessment,
    budget_similarity,
    build_customer_history,
    build_supplier_history,
    calculate_competition_metrics,
    detect_repeated_procurements,
    generate_historical_queries,
    history_adjustment,
    load_offline_history,
    run_historical_for_cards,
    score_similarity,
    select_analogs,
)
from radar.models import CompetitionMetrics, EligibilityStatus, HistoricalAnalog, RadarAssessment, RadarDecision
from radar.prefilter import parse_as_of
from radar.scoring import assess_card
from radar.search_profiles import SearchProfile
from radar.state import RadarState


def source_card() -> object:
    return normalize_card(
        {
            "procurement_number": "90000000000000000001",
            "title": "Разработка веб-приложения с личным кабинетом и административной панелью",
            "customer": "ГБУ Пример Аналитика",
            "law": "44-FZ",
            "procedure_type": "Электронный аукцион",
            "nmck": 1800000,
            "region": "Москва",
            "raw_text": "Личный кабинет, workflow, API, интеграция, реестр.",
        }
    )


def test_completed_only_query_has_completed_status() -> None:
    config = RadarConfig()
    card = source_card()
    queries = generate_historical_queries(card, config, profile="web")
    assert queries
    assert all(query.completed_only for query in queries)
    assert queries[0].query_text


def test_query_generation_removes_boilerplate_terms() -> None:
    config = RadarConfig()
    card = normalize_card({"procurement_number": "2", "title": "Оказание услуг по созданию сайта", "customer": "X", "nmck": 1})
    queries = generate_historical_queries(card, config)
    assert all("оказание" not in query.query_text.lower() for query in queries)
    assert all("услуг" not in query.query_text.lower() for query in queries)


def test_similarity_uses_functional_overlap_and_budget() -> None:
    card = source_card()
    analog = HistoricalAnalog(source_procurement_number=card.procurement_number, analog_procurement_number="A1", title="Разработка веб-приложения с личным кабинетом и API", customer=card.customer, procedure_type=card.procedure_type, region=card.region, nmck=1750000)
    scored = score_similarity(card, analog, ["веб-приложение"])
    assert scored.similarity_score > 0
    assert scored.functional_similarity_score > 0
    assert scored.budget_similarity_score > 0


def test_low_value_title_terms_do_not_dominate() -> None:
    card = source_card()
    analog = HistoricalAnalog(source_procurement_number=card.procurement_number, analog_procurement_number="A2", title="Сайт новости контакты", customer="Other", procedure_type="Other", region="Other", nmck=500000)
    scored = score_similarity(card, analog)
    assert scored.similarity_score < 20


def test_select_analogs_applies_threshold_and_limit() -> None:
    config = RadarConfig()
    card = source_card()
    analogs = [
        HistoricalAnalog(source_procurement_number=card.procurement_number, analog_procurement_number=f"A{i}", title="Разработка веб-приложения с личным кабинетом", customer=card.customer, procedure_type=card.procedure_type, region=card.region, nmck=1800000)
        for i in range(5)
    ]
    config.historical.search.maximum_selected_analogs = 3
    selected = select_analogs(card, analogs, config)
    assert len(selected) == 3
    assert all(item.similarity_score >= config.historical.similarity.minimum_score for item in selected)


def test_budget_similarity_bands() -> None:
    assert budget_similarity(100, 110)[0] == 10
    assert budget_similarity(100, 140)[0] == 7
    assert budget_similarity(100, 300)[0] == 3
    assert budget_similarity(100, 700)[0] == 0


def test_competition_metrics_and_confidence() -> None:
    config = RadarConfig()
    analogs = load_offline_history("tests/fixtures/radar_history", "90000000000000000002")
    metrics = calculate_competition_metrics(analogs, config)
    assert metrics.median_participants and metrics.median_participants >= 22
    assert metrics.confidence in {"LOW", "MEDIUM", "HIGH"}


def test_extreme_competition_risk() -> None:
    config = RadarConfig()
    analogs = load_offline_history("tests/fixtures/radar_history", "90000000000000000002")
    metrics = calculate_competition_metrics(analogs, config)
    risk = assess_dumping_risk(metrics, config)
    assert risk.risk_level in {"HIGH", "EXTREME"}
    assert risk.risk_score > 0


def test_no_participant_and_republication_are_detected() -> None:
    config = RadarConfig()
    analogs = load_offline_history("tests/fixtures/radar_history", "90000000000000000005")
    metrics = calculate_competition_metrics(analogs, config)
    assert metrics.no_application_rate > 0
    card = normalize_card(
        {
            "procurement_number": "90000000000000000005",
            "title": "Интеграция портала с ЕСИА и СМЭВ",
            "customer": "АНО Пример Госуслуги",
            "law": "44-FZ",
            "procedure_type": "Конкурс",
            "nmck": 2500000,
            "region": "Москва",
            "raw_text": "Портал, личный кабинет, API.",
        }
    )
    selected = select_analogs(card, analogs, config)
    repeated = detect_repeated_procurements(card, selected)
    assert repeated


def test_history_adjustment_does_not_override_hard_reject() -> None:
    config = RadarConfig()
    card = normalize_card({"procurement_number": "3", "title": "Доработка 1С", "nmck": 1200000, "raw_text": "1С:Предприятие"})
    preliminary = assess_card(card, EligibilityStatus.OPEN, 10, config, [SearchProfile(name="software_development")])
    risk = assess_dumping_risk(CompetitionMetrics(confidence="HIGH"), config)
    adjusted = history_adjustment(preliminary, risk)
    assert adjusted.history_adjusted_decision == RadarDecision.REJECT


def test_offline_history_bundle_updates_assessment() -> None:
    config = RadarConfig()
    config.historical.enabled = True
    cards = [source_card()]
    as_of = parse_as_of("2026-08-04", config.radar.timezone)
    assessment = assess_card(cards[0], EligibilityStatus.OPEN, 10, config, [SearchProfile(name="web_apps")], is_new=True)
    bundles, diagnostics = run_historical_for_cards(cards, [assessment], config, offline_history_input="tests/fixtures/radar_history")
    assert bundles
    assert diagnostics["historical_queries_planned"] > 0
    assert assessment.analog_count >= 0
    assert assessment.history_adjusted_score >= 0


def test_customer_and_supplier_profiles_are_bounded() -> None:
    config = RadarConfig()
    analogs = load_offline_history("tests/fixtures/radar_history", "90000000000000000002")
    metrics = calculate_competition_metrics(analogs, config)
    customer = build_customer_history("МАУ Пример Культура", analogs, metrics, config)
    suppliers = build_supplier_history(analogs, config)
    assert customer.evidence_count <= config.historical.customer_history.maximum_procurements
    assert len(suppliers) <= config.historical.supplier_history.maximum_suppliers_per_procurement


def test_apply_history_preserves_preliminary_hard_reject() -> None:
    config = RadarConfig()
    card = normalize_card({"procurement_number": "4", "title": "Доработка 1С", "nmck": 1200000, "raw_text": "1С:Предприятие"})
    assessment = assess_card(card, EligibilityStatus.OPEN, 10, config, [SearchProfile(name="software_development")])
    bundle = run_historical_for_cards([card], [assessment], config, offline_history_input="tests/fixtures/radar_history")[0][0]
    apply_history_to_assessment(assessment, bundle, config)
    assert assessment.radar_decision == RadarDecision.REJECT


def test_history_fixture_loads() -> None:
    analogs = load_offline_history("tests/fixtures/radar_history", "90000000000000000001")
    assert analogs
    assert analogs[0].source_procurement_number == "90000000000000000001"


def test_state_saves_historical_tables(tmp_path: Path) -> None:
    config = RadarConfig()
    card = source_card()
    assessment = assess_card(card, EligibilityStatus.OPEN, 10, config, [SearchProfile(name="web_apps")], is_new=True)
    bundles, _ = run_historical_for_cards([card], [assessment], config, offline_history_input="tests/fixtures/radar_history")
    state = RadarState(tmp_path / "radar.db")
    state.save_run("r1", "s", "f", "a", "0.3.0-r3a-history", {}, [card], [assessment], bundles)
    assert state.connection.execute("SELECT COUNT(*) FROM historical_result_metrics").fetchone()[0] == 1
    state.close()
