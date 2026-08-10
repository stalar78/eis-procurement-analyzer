from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus
from radar.prefilter import evaluate_eligibility, parse_as_of
from radar.search_profiles import SearchProfile


def test_open_deadline_is_eligible() -> None:
    config = RadarConfig()
    card = normalize_card(
        {
            "procurement_number": "1",
            "title": "Разработка веб-приложения",
            "status_raw": "Подача заявок",
            "application_deadline": "2026-08-20 12:00",
        }
    )
    status, days_left, _ = evaluate_eligibility(card, parse_as_of("2026-08-04", config.radar.timezone), config, [SearchProfile(name="web_apps")])
    assert status == EligibilityStatus.OPEN
    assert days_left and days_left > 15


def test_expired_deadline_is_closed() -> None:
    config = RadarConfig()
    card = normalize_card({"procurement_number": "2", "status_raw": "Подача заявок", "application_deadline": "2026-08-01"})
    status, _, reasons = evaluate_eligibility(card, parse_as_of("2026-08-04", config.radar.timezone), config, [SearchProfile(name="web_apps")])
    assert status == EligibilityStatus.CLOSED
    assert "application deadline has passed" in reasons


def test_deadline_one_day_is_too_close() -> None:
    config = RadarConfig()
    card = normalize_card({"procurement_number": "3", "status_raw": "Подача заявок", "application_deadline": "2026-08-05"})
    status, days_left, _ = evaluate_eligibility(card, parse_as_of("2026-08-04", config.radar.timezone), config, [SearchProfile(name="web_apps")])
    assert status == EligibilityStatus.DEADLINE_TOO_CLOSE
    assert 0 <= days_left <= 1


def test_timezone_as_of_date_uses_moscow_midnight() -> None:
    as_of = parse_as_of("2026-08-04", "Europe/Moscow")
    assert as_of.tzinfo is not None
    assert as_of.hour == 0


def test_unknown_deadline_is_retained() -> None:
    config = RadarConfig()
    card = normalize_card({"procurement_number": "4", "status_raw": "Подача заявок", "application_deadline": ""})
    status, days_left, _ = evaluate_eligibility(card, parse_as_of("2026-08-04", config.radar.timezone), config, [SearchProfile(name="web_apps")])
    assert status == EligibilityStatus.DEADLINE_UNKNOWN
    assert days_left is None

