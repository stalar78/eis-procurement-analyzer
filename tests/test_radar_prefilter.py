from radar.config import RadarConfig
from radar.discovery import deduplicate_cards, normalize_card
from radar.prefilter import hard_reject_reasons
from radar.search_profiles import SearchProfile


def test_deduplication_merges_queries() -> None:
    cards = deduplicate_cards(
        [
            normalize_card({"procurement_number": "1", "title": "A", "search_queries": ["веб-приложение"]}),
            normalize_card({"procurement_number": "1", "title": "A", "search_queries": ["личный кабинет"]}),
        ]
    )
    assert len(cards) == 1
    assert sorted(cards[0].search_queries) == ["веб-приложение", "личный кабинет"]


def test_license_supply_is_hard_rejected() -> None:
    card = normalize_card(
        {
            "procurement_number": "2",
            "title": "Поставка лицензий",
            "nmck": 900000,
            "raw_text": "Продление лицензий без разработки.",
        }
    )
    reasons = hard_reject_reasons(card, RadarConfig(), [SearchProfile(name="software_development")])
    assert any("лиценз" in reason for reason in reasons)


def test_support_with_real_development_is_not_rejected_by_support_word() -> None:
    card = normalize_card(
        {
            "procurement_number": "3",
            "title": "Сопровождение системы",
            "nmck": 900000,
            "raw_text": "Сопровождение, доработка, модернизация и изменение функциональности.",
        }
    )
    reasons = hard_reject_reasons(card, RadarConfig(), [SearchProfile(name="software_development", exclusion_terms=["сопровождение"])])
    assert not reasons


def test_nmck_below_hard_minimum_is_rejected() -> None:
    card = normalize_card({"procurement_number": "4", "title": "Разработка модуля", "nmck": 90_000})
    reasons = hard_reject_reasons(card, RadarConfig(), [SearchProfile(name="software_development")])
    assert "nmck below hard minimum" in reasons

