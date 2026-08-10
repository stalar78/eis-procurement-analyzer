from __future__ import annotations

from radar.analog_search import (
    extract_category,
    extract_functional_terms,
    generate_historical_queries,
    normalize_text,
    repair_mojibake,
)
from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.historical import score_similarity, select_analogs
from radar.models import HistoricalAnalog


def source_card(title: str, raw_text: str = "", customer: str = "Администрация тестового района"):
    return normalize_card(
        {
            "procurement_number": "0122300036525000031",
            "title": title,
            "customer": customer,
            "law": "44-FZ",
            "procedure_type": "Электронный аукцион",
            "nmck": 750000,
            "raw_text": raw_text,
        }
    )


def test_repair_mojibake_restores_russian_text() -> None:
    broken = "Разработка инвестиционного портала".encode("utf-8").decode("cp1251")
    assert repair_mojibake(broken) == "Разработка инвестиционного портала"
    assert normalize_text(broken) == "разработка инвестиционного портала"


def test_source_aware_queries_prefer_business_portal_terms() -> None:
    config = RadarConfig()
    config.historical.search.maximum_queries_per_procurement = 5
    card = source_card(
        "Оказание услуг по разработке интернет-портала для бизнеса",
        raw_text="Инвестиционный портал, личный кабинет, API и административная панель.",
    )
    queries = generate_historical_queries(card, config, profile="r3a3")
    assert queries
    assert queries[0].generation_reason == "SOURCE_EXACT_PHRASE"
    assert any(query.query_text == "инвестиционный портал" for query in queries)
    assert any(query.query_text == "портал для бизнеса" for query in queries)
    assert all("реестр" not in query.query_text for query in queries)


def test_functional_terms_detect_portal_account_and_admin_panel() -> None:
    terms = extract_functional_terms("Разработка интернет-портала с личным кабинетом и административной панелью")
    assert "portal" in terms
    assert "account" in terms
    assert "admin_panel" in terms


def test_category_detection_rejects_license_and_hardware() -> None:
    assert extract_category("Доработка 1С и передача лицензий") == "LICENSE_ONLY"
    assert extract_category("Поставка сервера и компьютерного оборудования") == "HARDWARE"


def test_portal_candidate_beats_hardware_candidate_with_diagnostics() -> None:
    source = source_card("Разработка инвестиционного портала для бизнеса", raw_text="Личный кабинет и API")
    portal_analog = HistoricalAnalog(
        source_procurement_number=source.procurement_number,
        analog_procurement_number="a1",
        title="Разработка информационного портала с личным кабинетом",
        customer=source.customer,
        nmck=730000,
    )
    hardware_analog = HistoricalAnalog(
        source_procurement_number=source.procurement_number,
        analog_procurement_number="a2",
        title="Поставка серверного оборудования",
        customer="Другой заказчик",
        nmck=700000,
    )
    portal_scored = score_similarity(source, portal_analog)
    hardware_scored = score_similarity(source, hardware_analog)
    assert portal_scored.similarity_score > hardware_scored.similarity_score
    assert portal_scored.category_compatibility in {"STRONG_CATEGORY_MATCH", "CATEGORY_MATCH"}
    assert hardware_scored.exclusion_reason == "CATEGORY_MISMATCH"
    assert "portal" in portal_scored.shared_functional_terms


def test_relaxed_threshold_is_used_for_broad_same_customer_portal_match() -> None:
    config = RadarConfig()
    config.historical.similarity.minimum_score = 45
    source = source_card("Разработка интернет-портала личный кабинет", raw_text="Портал, API")
    analog = HistoricalAnalog(
        source_procurement_number=source.procurement_number,
        analog_procurement_number="a1",
        title="Разработка портала",
        customer=source.customer,
        nmck=740000,
    )
    selected = select_analogs(source, [analog], config)
    assert len(selected) == 1
    assert selected[0].selection_mode == "RELAXED_THRESHOLD"
    assert "RELAXED_THRESHOLD" in selected[0].mismatch_reasons
    assert selected[0].similarity_score >= config.historical.similarity.hard_floor_score


def test_query_generation_preserves_priority_order() -> None:
    config = RadarConfig()
    card = source_card(
        "Разработка интернет-портала",
        raw_text="Информационный портал, личный кабинет.",
    )
    queries = generate_historical_queries(card, config, profile="r3a3")
    reasons = [query.generation_reason for query in queries]
    assert reasons[:3] == ["SOURCE_EXACT_PHRASE", "SOURCE_FUNCTIONAL_TERM", "SOURCE_CATEGORY"]
