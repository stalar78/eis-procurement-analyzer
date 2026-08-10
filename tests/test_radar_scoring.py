from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus, RadarDecision
from radar.scoring import assess_card
from radar.search_profiles import SearchProfile


def test_simple_site_gets_commodity_penalty() -> None:
    card = normalize_card(
        {
            "procurement_number": "1",
            "title": "Создание сайта-визитки",
            "nmck": 600000,
            "raw_text": "Типовой сайт, фотогалерея, контакты.",
        }
    )
    assessment = assess_card(card, EligibilityStatus.OPEN, 20, RadarConfig(), [SearchProfile(name="portals")])
    assert assessment.commodity_score > 0
    assert any("commodity signal" in reason for reason in assessment.negative_reasons)


def test_registry_with_workflow_gets_positive_score() -> None:
    card = normalize_card(
        {
            "procurement_number": "2",
            "title": "Электронный реестр",
            "nmck": 1400000,
            "raw_text": "Workflow, роли, обработка заявок, API, интеграция.",
        }
    )
    assessment = assess_card(card, EligibilityStatus.OPEN, 20, RadarConfig(), [SearchProfile(name="automation")])
    assert assessment.technical_interest_score > 0
    assert assessment.total_score >= 55


def test_specific_platform_gets_blocker() -> None:
    card = normalize_card({"procurement_number": "3", "title": "Доработка 1С", "nmck": 1200000, "raw_text": "1С:Предприятие"})
    assessment = assess_card(card, EligibilityStatus.OPEN, 20, RadarConfig(), [SearchProfile(name="software_development")])
    assert assessment.radar_decision == RadarDecision.REJECT
    assert any("specific-platform" in reason for reason in assessment.hard_reject_reasons)


def test_priority_only_contains_open_eligible_records() -> None:
    card = normalize_card(
        {
            "procurement_number": "4",
            "title": "Разработка веб-приложения",
            "nmck": 1800000,
            "raw_text": "Личный кабинет, административная панель, роли, API, интеграция, реестр, workflow.",
        }
    )
    assessment = assess_card(card, EligibilityStatus.CLOSED, -1, RadarConfig(), [SearchProfile(name="web_apps")])
    assert assessment.radar_decision == RadarDecision.REJECT

