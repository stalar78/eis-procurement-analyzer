from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from radar.config import RadarConfig
from radar.discovery import discover_cards
from radar.models import NormalizedStatus
from radar.open_verification import (
    build_status_audit,
    is_provisionally_open,
    normalize_status_v2,
    verify_open_from_detail_text,
)
from radar.search_profiles import load_search_profiles, select_profiles
from radar.search_request import (
    build_eis_search_request,
    redact_url,
    request_from_url,
    serialize_eis_search_request,
)
from radar.discovery import normalize_card


BASE = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"


def test_active_only_search_request_includes_active_parameters() -> None:
    config = RadarConfig()
    req = build_eis_search_request("личный кабинет", config, as_of=datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    url = serialize_eis_search_request(req, BASE)
    params = parse_qs(urlparse(url).query)
    assert params["af"] == ["on"]
    assert "pc" not in params
    assert "pa" not in params
    assert params["applSubmissionCloseDateFrom"] == ["04.08.2026"]


def test_all_statuses_preserves_research_behavior() -> None:
    config = RadarConfig()
    req = build_eis_search_request("веб", config, discovery_mode="ALL_STATUSES")
    url = serialize_eis_search_request(req, BASE)
    params = parse_qs(urlparse(url).query)
    assert {"af", "ca", "pc", "pa"}.issubset(params)


def test_failed_only_search_request_uses_completed_and_cancelled_without_active_flags() -> None:
    config = RadarConfig()
    req = build_eis_search_request("Р»РёС‡РЅС‹Р№ РєР°Р±РёРЅРµС‚", config, discovery_mode="FAILED_ONLY")
    url = serialize_eis_search_request(req, BASE)
    params = parse_qs(urlparse(url).query)
    assert params["pc"] == ["on"]
    assert params["pa"] == ["on"]
    assert "af" not in params
    assert "ca" not in params
    assert request_from_url(url).discovery_mode == "FAILED_ONLY"


def test_pagination_preserves_filter_fingerprint() -> None:
    config = RadarConfig()
    req1 = build_eis_search_request("веб", config, page_number=1)
    req2 = build_eis_search_request("веб", config, page_number=2)
    assert req1.fingerprint() == req2.fingerprint()


def test_lost_filter_is_detectable() -> None:
    config = RadarConfig()
    req = build_eis_search_request("веб", config)
    url = serialize_eis_search_request(req, BASE).replace("&af=on", "")
    assert request_from_url(url).fingerprint() != req.fingerprint()


def test_completed_status_not_provisionally_open_even_future_deadline() -> None:
    card = normalize_card({"procurement_number": "1", "status_raw": "Определение поставщика завершено", "application_deadline": "2026-09-01"})
    ok, _, info = is_provisionally_open(card, datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    assert not ok
    assert info.normalized_status == NormalizedStatus.COMPLETED


def test_active_status_with_past_deadline_not_open() -> None:
    card = normalize_card({"procurement_number": "1", "status_raw": "Подача заявок", "application_deadline": "2026-08-01"})
    ok, reasons, _ = is_provisionally_open(card, datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    assert not ok
    assert "deadline is not in the future" in reasons


def test_active_status_with_future_deadline_open() -> None:
    card = normalize_card({"procurement_number": "1", "status_raw": "Подача заявок", "application_deadline": "2026-08-20"})
    ok, _, _ = is_provisionally_open(card, datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    assert ok


def test_detail_page_verifies_open_procurement() -> None:
    card = normalize_card({"procurement_number": "1", "status_raw": "Подача заявок", "application_deadline": "20.08.2026"})
    detail = "Статус: Подача заявок\nДата и время окончания срока подачи заявок: 20.08.2026 10:00"
    result = verify_open_from_detail_text(card, detail, datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    assert result.open_verification_status == "VERIFIED_OPEN"


def test_detail_deadline_conflict_blocks() -> None:
    card = normalize_card({"procurement_number": "1", "status_raw": "Подача заявок", "application_deadline": "20.08.2026"})
    detail = "Статус: Подача заявок\nДата и время окончания срока подачи заявок: 19.08.2026 10:00"
    result = verify_open_from_detail_text(card, detail, datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    assert result.open_verification_status == "DEADLINE_CONFLICT"


def test_cancelled_detail_blocks() -> None:
    card = normalize_card({"procurement_number": "1", "status_raw": "Подача заявок", "application_deadline": "20.08.2026"})
    result = verify_open_from_detail_text(card, "Статус: Закупка отменена", datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    assert result.open_verification_status == "VERIFIED_CANCELLED"


def test_status_audit_aggregates_raw_labels() -> None:
    cards = [
        normalize_card({"procurement_number": "1", "status_raw": "Подача заявок", "application_deadline": "20.08.2026"}),
        normalize_card({"procurement_number": "2", "status_raw": "Подача заявок", "application_deadline": "01.08.2026"}),
    ]
    rows = build_status_audit(cards, datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow")))
    assert rows[0]["occurrence_count"] == 2
    assert rows[0]["future_deadline_count"] == 1


def test_search_diagnostics_redacts_sensitive_params() -> None:
    redacted = redact_url("https://zakupki.gov.ru/x?sessionId=abc&token=secret&af=on")
    assert "secret" not in redacted
    assert "%3Credacted%3E" in redacted


def test_medium_complexity_web_profile_loads() -> None:
    profiles = load_search_profiles()
    selected = select_profiles(profiles, "medium_complexity_web")
    assert selected[0].queries
    assert "личный кабинет" in selected[0].queries


def test_offline_zero_open_result_reason() -> None:
    config = RadarConfig()
    cards, diagnostics = discover_cards(
        config,
        select_profiles(load_search_profiles(), "web_apps"),
        offline_input="tests/fixtures/radar_cards.json",
        as_of=datetime(2030, 1, 1, tzinfo=ZoneInfo("Europe/Moscow")),
        discovery_mode="ACTIVE_ONLY",
    )
    assert diagnostics["unique_cards"] == len(cards)


def test_status_mapping_price_submission() -> None:
    info = normalize_status_v2("Подача ценовых предложений")
    assert info.normalized_status == NormalizedStatus.PRICE_SUBMISSION
