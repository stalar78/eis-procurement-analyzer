from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
import requests

from radar import http
import radar.source_resolution as source_resolution
from radar.config import RadarConfig
from radar.discovery import _detail_unavailable_diagnostics, discover_cards, verify_cards_from_detail
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
from radar.state import RadarState


BASE = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
PROCUREMENT_NUMBER = "01234567890123456789"
OTHER_PROCUREMENT_NUMBER = "98765432109876543210"
ACTIVE_DETAIL_STATUS = "Подача заявок"
ACTIVE_DETAIL_DEADLINE = "20.08.2026 10:00"
COMPLETED_DETAIL_STATUS = "Определение поставщика завершено"
CANCELLED_DETAIL_STATUS = "Закупка отменена"


def _as_of() -> datetime:
    return datetime(2026, 8, 4, tzinfo=ZoneInfo("Europe/Moscow"))


def _verification_card():
    return normalize_card(
        {
            "procurement_number": PROCUREMENT_NUMBER,
            "status_raw": ACTIVE_DETAIL_STATUS,
            "application_deadline": "20.08.2026",
        }
    )


def _detail(*, number: str = PROCUREMENT_NUMBER, status: str = ACTIVE_DETAIL_STATUS, deadline: str = ACTIVE_DETAIL_DEADLINE) -> str:
    parts = [f"Номер закупки: {number}"]
    if status:
        parts.append(f"Статус: {status}")
    if deadline:
        parts.append(f"Дата и время окончания срока подачи заявок: {deadline}")
    return "\n".join(parts)


class DetailResponse:
    def __init__(self, status_code: int, text: str, url: str) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url


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


@pytest.mark.parametrize(
    ("detail", "expected_status"),
    [
        ("", "DETAIL_UNAVAILABLE"),
        ("<html><body>HTTP 200 OK</body></html>", "DETAIL_UNAVAILABLE"),
        (_detail(status=""), "DETAIL_UNAVAILABLE"),
        (_detail(deadline=""), "DETAIL_UNAVAILABLE"),
        (_detail(deadline="", status=ACTIVE_DETAIL_STATUS), "DETAIL_UNAVAILABLE"),
        (_detail(status="", deadline=ACTIVE_DETAIL_DEADLINE), "DETAIL_UNAVAILABLE"),
        (_detail(number=OTHER_PROCUREMENT_NUMBER), "DETAIL_UNAVAILABLE"),
        ("<html><body><div>" + PROCUREMENT_NUMBER + "<span>broken", "DETAIL_UNAVAILABLE"),
        (_detail(status="Неизвестный статус"), "STATUS_CONFLICT"),
    ],
)
def test_incomplete_detail_evidence_does_not_verify_open(detail: str, expected_status: str) -> None:
    result = verify_open_from_detail_text(_verification_card(), detail, _as_of())

    assert result.open_verification_status == expected_status
    assert result.open_verification_status != "VERIFIED_OPEN"


def test_valid_detail_page_verifies_open_procurement() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(), _as_of())

    assert result.open_verification_status == "VERIFIED_OPEN"
    assert result.detail_failure_code == ""


def test_exact_procurement_number_identity_verifies_open_procurement() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(number=PROCUREMENT_NUMBER), _as_of())

    assert result.open_verification_status == "VERIFIED_OPEN"


def test_different_procurement_number_identity_does_not_verify_open_procurement() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(number=OTHER_PROCUREMENT_NUMBER), _as_of())

    assert result.open_verification_status == "DETAIL_UNAVAILABLE"
    assert result.detail_failure_code == "IDENTITY_MISMATCH"


def test_unrelated_numeric_fields_are_not_concatenated_into_procurement_identity() -> None:
    detail = "\n".join(
        [
            "Номер позиции: 0123456789",
            "Номер редакции: 0123456789",
            f"Статус: {ACTIVE_DETAIL_STATUS}",
            f"Дата и время окончания срока подачи заявок: {ACTIVE_DETAIL_DEADLINE}",
        ]
    )
    result = verify_open_from_detail_text(_verification_card(), detail, _as_of())

    assert result.open_verification_status == "DETAIL_UNAVAILABLE"
    assert result.detail_failure_code == "IDENTITY_MISMATCH"


def test_missing_detail_status_has_failure_code() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(status=""), _as_of())

    assert result.open_verification_status == "DETAIL_UNAVAILABLE"
    assert result.detail_failure_code == "DETAIL_STATUS_MISSING"


def test_missing_detail_deadline_has_failure_code() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(deadline=""), _as_of())

    assert result.open_verification_status == "DETAIL_UNAVAILABLE"
    assert result.detail_failure_code == "DETAIL_DEADLINE_MISSING"


def test_unparseable_detail_deadline_has_failure_code() -> None:
    detail = _detail(deadline="not-a-date")

    result = verify_open_from_detail_text(_verification_card(), detail, _as_of())

    assert result.open_verification_status == "DETAIL_UNAVAILABLE"
    assert result.detail_failure_code == "DETAIL_DEADLINE_MISSING"


def test_detail_deadline_conflict_blocks() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(deadline="19.08.2026 10:00"), _as_of())

    assert result.open_verification_status == "DEADLINE_CONFLICT"
    assert result.detail_failure_code == ""


def test_valid_cancelled_detail_blocks() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(status=CANCELLED_DETAIL_STATUS, deadline=""), _as_of())

    assert result.open_verification_status == "VERIFIED_CANCELLED"
    assert result.detail_failure_code == ""


def test_valid_closed_detail_blocks() -> None:
    result = verify_open_from_detail_text(_verification_card(), _detail(status=COMPLETED_DETAIL_STATUS, deadline=""), _as_of())

    assert result.open_verification_status == "VERIFIED_CLOSED"
    assert result.detail_failure_code == ""


def test_missing_source_url_has_failure_code() -> None:
    card = _verification_card()
    card.source_url = ""

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "MISSING_SOURCE_URL"


def test_http_error_has_failure_code(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"

    class Response:
        status_code = 503
        text = ""

    monkeypatch.setattr(http, "get", lambda *_args, **_kwargs: Response())

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "HTTP_ERROR"


def test_detail_verification_successful_https_fetch_uses_default_tls(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
    calls = []

    class Response:
        status_code = 200
        text = _detail()

    def fake_get(url: str, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert calls == [(card.source_url, {"timeout": 30})]
    assert result["detail_source_recovery_status"] == "NOT_ATTEMPTED"


def test_detail_verification_404_recovers_canonical_source(monkeypatch) -> None:
    card = _verification_card()
    stale_url = "https://zakupki.gov.ru/epz/order/notice/zk20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    recovered_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card.source_url = stale_url
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return Response(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return Response(200, f'<html>{PROCUREMENT_NUMBER}<a href="/epz/order/notice/ea20/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">detail</a></html>', url)
        if url == recovered_url:
            return Response(200, _detail(), url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_failure_code"] == ""
    assert result["detail_source_recovery_status"] == "RECOVERED"
    assert result["detail_source_resolution_status"] == "RESOLVED_SEARCH_RECOVERY"
    assert PROCUREMENT_NUMBER not in result["detail_recovered_url"]
    assert calls == [stale_url, stale_url, calls[2], recovered_url]


def test_detail_verification_recovered_identity_mismatch_fails_closed(monkeypatch) -> None:
    card = _verification_card()
    stale_url = "https://zakupki.gov.ru/epz/order/notice/zk20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    recovered_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card.source_url = stale_url

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        if url == stale_url:
            return Response(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return Response(200, f'<html>{PROCUREMENT_NUMBER}<a href="/epz/order/notice/ea20/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">detail</a></html>', url)
        if url == recovered_url:
            return Response(200, _detail(number=OTHER_PROCUREMENT_NUMBER), url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "SOURCE_RECOVERY_FAILED"
    assert result["detail_source_recovery_status"] == "FAILED"


def test_detail_verification_404_recovery_failure_is_structured(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/zk20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if "extendedsearch" in url:
            return Response(200, '<html><form action="/epz/order/extendedsearch/results.html"><input name="searchString" value="other"></form><div>no matching procurement</div></html>', url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "SOURCE_URL_NOT_FOUND"
    assert result["detail_source_recovery_status"] == "FAILED"
    assert result["detail_source_resolution_status"] == "NOT_FOUND_CONFIRMED"
    assert len(calls) == 3


def test_detail_verification_echoed_exact_search_input_does_not_partially_resolve(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/zk20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        if "extendedsearch" in url:
            return Response(200, f'<html><form action="/epz/order/extendedsearch/results.html"><input name="searchString" value="{PROCUREMENT_NUMBER}"></form></html>', url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "SOURCE_URL_NOT_FOUND"
    assert result["detail_source_recovery_status"] == "FAILED"
    assert result["detail_source_resolution_status"] == "NOT_FOUND_CONFIRMED"


def test_detail_verification_223_stale_url_recovers_without_forcing_44fz_path(monkeypatch) -> None:
    card = _verification_card()
    stale_url = "https://zakupki.gov.ru/223/purchase/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    recovered_url = "https://zakupki.gov.ru/223/purchase/notice.html?regNumber=" + PROCUREMENT_NUMBER
    card.source_url = stale_url
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return Response(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return Response(200, f'<html>{PROCUREMENT_NUMBER}<a href="/223/purchase/notice.html?regNumber={PROCUREMENT_NUMBER}">223 detail</a></html>', url)
        if url == recovered_url:
            return Response(200, _detail(), url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_recovery_status"] == "RECOVERED"
    assert PROCUREMENT_NUMBER not in result["detail_recovered_url"]
    assert all("/epz/order/notice/" not in url for url in calls)


def test_last_known_good_detail_source_survives_separate_runs(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    recovered_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    calls = []

    def first_run_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return DetailResponse(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return DetailResponse(200, f'<html><a href="/epz/order/notice/ea20/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">result</a></html>', url)
        if url == recovered_url:
            return DetailResponse(200, _detail(), url)
        return DetailResponse(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", first_run_get)
    state = RadarState(db)
    first = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    remembered = state.get_last_successful_source_url(PROCUREMENT_NUMBER)
    state.close()

    assert first["open_verification_status"] == "VERIFIED_OPEN"
    assert remembered == recovered_url

    calls.clear()

    def second_run_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return DetailResponse(404, "<html>404 Not Found</html>", url)
        if url == recovered_url:
            return DetailResponse(200, _detail(), url)
        raise AssertionError(f"unexpected network request: {url}")

    monkeypatch.setattr(http, "get", second_run_get)
    state = RadarState(db)
    second = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert second["open_verification_status"] == "VERIFIED_OPEN"
    assert second["detail_source_strategy"] == "LAST_KNOWN_GOOD"
    assert second["detail_source_recovery_status"] == "REUSED"
    assert calls == [stale_url, recovered_url]


def test_failed_last_known_good_source_does_not_replace_it_until_new_source_succeeds(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    old_url = "https://zakupki.gov.ru/epz/order/notice/old/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    new_url = "https://zakupki.gov.ru/epz/order/notice/new/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    state = RadarState(db)
    state.save_successful_source_url(
        procurement_number=PROCUREMENT_NUMBER,
        source_url=old_url,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        latest_known_validation_status="VERIFIED_OPEN",
    )
    state.close()
    calls = []

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url in {stale_url, old_url}:
            return DetailResponse(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return DetailResponse(200, f'<html><a href="/epz/order/notice/new/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">new result</a></html>', url)
        if url == new_url:
            return DetailResponse(200, _detail(), url)
        return DetailResponse(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    replacement = state.get_last_successful_source_url(PROCUREMENT_NUMBER)
    state.close()

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_strategy"] == "SEARCH_RECOVERED_LINK"
    assert replacement == new_url
    assert calls.count(old_url) == 1
    assert new_url in calls


def test_direct_request_exception_falls_through_to_last_known_good(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    remembered_url = "https://zakupki.gov.ru/epz/order/notice/remembered/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    state = RadarState(db)
    state.save_successful_source_url(
        procurement_number=PROCUREMENT_NUMBER,
        source_url=remembered_url,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        latest_known_validation_status="VERIFIED_OPEN",
    )
    state.close()
    calls = []

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            raise requests.exceptions.Timeout("timeout for https://zakupki.gov.ru/detail")
        if url == remembered_url:
            return DetailResponse(200, _detail(), url)
        raise AssertionError(f"unexpected network request: {url}")

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_strategy"] == "LAST_KNOWN_GOOD"
    assert result["detail_source_recovery_status"] == "REUSED"
    assert calls == [stale_url, remembered_url]


def test_direct_request_exception_without_last_known_good_reaches_exact_search(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == card.source_url:
            raise requests.exceptions.Timeout("timeout for https://zakupki.gov.ru/detail")
        if "extendedsearch" in url:
            return Response(200, f'<html><a href="/epz/order/notice/ea20/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">detail</a></html>', url)
        if url.endswith(f"regNumber={PROCUREMENT_NUMBER}"):
            return Response(200, _detail(), url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_resolution_status"] == "RESOLVED_SEARCH_RECOVERY"
    assert any("extendedsearch" in url for url in calls)


def test_direct_transient_http_5xx_falls_through_to_last_known_good(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    remembered_url = "https://zakupki.gov.ru/epz/order/notice/remembered/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    state = RadarState(db)
    state.save_successful_source_url(
        procurement_number=PROCUREMENT_NUMBER,
        source_url=remembered_url,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        latest_known_validation_status="VERIFIED_OPEN",
    )
    state.close()
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return Response(503, "<html>Service Unavailable</html>", url)
        if url == remembered_url:
            return Response(200, _detail(), url)
        raise AssertionError(f"unexpected network request: {url}")

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_strategy"] == "LAST_KNOWN_GOOD"
    assert result["detail_source_recovery_status"] == "REUSED"
    assert calls == [stale_url, remembered_url]


def test_direct_http_503_without_last_known_good_reaches_exact_search(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == card.source_url:
            return Response(503, "<html>Service Unavailable</html>", url)
        if "extendedsearch" in url:
            return Response(200, f'<html><a href="/epz/order/notice/ea20/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">detail</a></html>', url)
        if url.endswith(f"regNumber={PROCUREMENT_NUMBER}"):
            return Response(200, _detail(), url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_resolution_status"] == "RESOLVED_SEARCH_RECOVERY"
    assert any("extendedsearch" in url for url in calls)


def test_direct_transient_failure_with_failed_last_known_good_reaches_exact_search(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    remembered_url = "https://zakupki.gov.ru/epz/order/notice/remembered/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    state = RadarState(db)
    state.save_successful_source_url(
        procurement_number=PROCUREMENT_NUMBER,
        source_url=remembered_url,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        latest_known_validation_status="VERIFIED_OPEN",
    )
    state.close()
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return Response(503, "<html>Service Unavailable</html>", url)
        if url == remembered_url:
            return Response(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return Response(200, f'<html><a href="/epz/order/notice/ea20/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">detail</a></html>', url)
        if url.endswith(f"regNumber={PROCUREMENT_NUMBER}"):
            return Response(200, _detail(), url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_resolution_status"] == "RESOLVED_SEARCH_RECOVERY"
    assert any("extendedsearch" in url for url in calls)


def test_public_verification_row_redacts_last_known_good_url(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    recovered_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url

    def fake_get(url: str, **_kwargs):
        if url == stale_url:
            return DetailResponse(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return DetailResponse(200, f'<html><a href="/epz/order/notice/ea20/view/common-info.html?regNumber={PROCUREMENT_NUMBER}">result</a></html>', url)
        if url == recovered_url:
            return DetailResponse(200, _detail(), url)
        return DetailResponse(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert PROCUREMENT_NUMBER not in result["detail_last_known_good_url"]
    assert "%3Credacted%3E" in result["detail_last_known_good_url"]
    assert "_detail_last_known_good_url" not in result


def test_non_recoverable_direct_http_failure_does_not_trigger_unintended_recovery(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    calls = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == card.source_url:
            return Response(403, "<html>Forbidden</html>", url)
        if "extendedsearch" in url:
            raise AssertionError("unexpected recovery attempt")
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "HTTP_ERROR"
    assert result.get("detail_source_resolution_status", "") == ""
    assert calls == [card.source_url]


def test_last_known_good_identity_mismatch_fails_closed_and_continues_recovery(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    remembered_url = "https://zakupki.gov.ru/223/purchase/old.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    state = RadarState(db)
    state.save_successful_source_url(
        procurement_number=PROCUREMENT_NUMBER,
        source_url=remembered_url,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        latest_known_validation_status="VERIFIED_OPEN",
    )
    state.close()

    def fake_get(url: str, **_kwargs):
        if url == stale_url or url == remembered_url:
            return DetailResponse(404 if url == stale_url else 200, "<html>404 Not Found</html>" if url == stale_url else _detail(number=OTHER_PROCUREMENT_NUMBER), url)
        if "extendedsearch" in url:
            return DetailResponse(200, '<html><form action="/epz/order/extendedsearch/results.html"><input name="searchString" value="other"></form></html>', url)
        return DetailResponse(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_source_recovery_status"] == "FAILED"
    assert result["detail_failure_code"] == "SOURCE_URL_NOT_FOUND"


def test_stale_last_known_good_metadata_is_not_used_without_live_fetch(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/epz/order/notice/stale/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    remembered_url = "https://zakupki.gov.ru/epz/order/notice/old/view/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    state = RadarState(db)
    state.save_successful_source_url(
        procurement_number=PROCUREMENT_NUMBER,
        source_url=remembered_url,
        fetched_at=(datetime.now().astimezone() - timedelta(hours=337)).isoformat(timespec="seconds"),
        latest_known_validation_status="VERIFIED_OPEN",
    )
    state.close()
    calls = []

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if "extendedsearch" in url:
            return DetailResponse(200, '<html><form action="/epz/order/extendedsearch/results.html"><input name="searchString" value="other"></form></html>', url)
        return DetailResponse(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert remembered_url not in calls
    assert any("extendedsearch" in url for url in calls)


def test_223_last_known_good_source_is_reused_without_44fz_fallback(monkeypatch, tmp_path) -> None:
    db = tmp_path / "radar.db"
    stale_url = "https://zakupki.gov.ru/223/purchase/stale.html?regNumber=" + PROCUREMENT_NUMBER
    remembered_url = "https://zakupki.gov.ru/223/purchase/live.html?regNumber=" + PROCUREMENT_NUMBER
    card = _verification_card()
    card.source_url = stale_url
    state = RadarState(db)
    state.save_successful_source_url(
        procurement_number=PROCUREMENT_NUMBER,
        source_url=remembered_url,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        latest_known_validation_status="VERIFIED_OPEN",
    )
    state.close()
    calls = []

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return DetailResponse(404, "<html>404 Not Found</html>", url)
        if url == remembered_url:
            return DetailResponse(200, _detail(), url)
        raise AssertionError(f"unexpected cross-family request: {url}")

    monkeypatch.setattr(http, "get", fake_get)
    state = RadarState(db)
    result = verify_cards_from_detail([card], _as_of(), limit=1, state=state)[0]
    state.close()

    assert result["open_verification_status"] == "VERIFIED_OPEN"
    assert result["detail_source_strategy"] == "LAST_KNOWN_GOOD"
    assert all("/epz/order/notice/" not in url for url in calls)


def test_223_stale_url_alternate_recovery_does_not_request_44fz(monkeypatch) -> None:
    card = _verification_card()
    stale_url = "https://zakupki.gov.ru/223/purchase/common-info.html?regNumber=" + PROCUREMENT_NUMBER
    recovered_link = "https://zakupki.gov.ru/223/purchase/notice.html?regNumber=" + PROCUREMENT_NUMBER
    card.source_url = stale_url
    calls = []
    sibling_seeds = []

    class Response:
        def __init__(self, status_code: int, text: str, url: str) -> None:
            self.status_code = status_code
            self.text = text
            self.url = url

    original_sibling_section_urls = source_resolution.sibling_section_urls

    def tracked_sibling_section_urls(url: str, number: str):
        sibling_seeds.append(url)
        return original_sibling_section_urls(url, number)

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        if url == stale_url:
            return Response(404, "<html>404 Not Found</html>", url)
        if "extendedsearch" in url:
            return Response(200, f'<html>{PROCUREMENT_NUMBER}<a href="/223/purchase/notice.html?regNumber={PROCUREMENT_NUMBER}">223 detail</a></html>', url)
        return Response(404, "<html>404 Not Found</html>", url)

    monkeypatch.setattr(source_resolution, "sibling_section_urls", tracked_sibling_section_urls)
    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "SOURCE_RECOVERY_FAILED"
    assert result["detail_source_recovery_status"] == "FAILED"
    assert sibling_seeds == [recovered_link]
    assert all("/epz/order/notice/" not in url for url in calls)


def test_detail_verification_ssl_error_degrades_to_detail_unavailable(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"

    def fake_get(_url: str, **_kwargs):
        raise requests.exceptions.SSLError("certificate verify failed")

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["open_verification_status"] != "VERIFIED_OPEN"
    assert result["detail_failure_code"] == "REQUEST_ERROR"
    assert result["open_verification_reasons"] == ["detail request failed"]


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("failed via C:/Users/example/cert.pem https://secret.example/path"),
        requests.exceptions.Timeout("timeout for https://secret.example/path"),
    ],
)
def test_detail_verification_request_errors_use_sanitized_reason(monkeypatch, error: requests.RequestException) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"

    def fake_get(_url: str, **_kwargs):
        raise error

    monkeypatch.setattr(http, "get", fake_get)

    result = verify_cards_from_detail([card], _as_of(), limit=1)[0]

    assert result["open_verification_status"] == "DETAIL_UNAVAILABLE"
    assert result["detail_failure_code"] == "REQUEST_ERROR"
    assert result["open_verification_reasons"] == ["detail request failed"]
    assert str(error) not in result["open_verification_reasons"][0]


def test_detail_verification_non_request_exception_is_not_request_error(monkeypatch) -> None:
    card = _verification_card()
    card.source_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"

    def fake_get(_url: str, **_kwargs):
        raise RuntimeError("programming bug")

    monkeypatch.setattr(http, "get", fake_get)

    with pytest.raises(RuntimeError, match="programming bug"):
        verify_cards_from_detail([card], _as_of(), limit=1)


def test_detail_unavailable_diagnostics_count_codes_and_examples() -> None:
    counts, examples = _detail_unavailable_diagnostics(
        [
            {"procurement_number": "1", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "HTTP_ERROR"},
            {"procurement_number": "2", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "HTTP_ERROR"},
            {"procurement_number": "3", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "HTTP_ERROR"},
            {"procurement_number": "4", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "HTTP_ERROR"},
            {"procurement_number": "5", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "DETAIL_STATUS_MISSING"},
            {"procurement_number": "6", "open_verification_status": "VERIFIED_OPEN", "detail_failure_code": ""},
        ]
    )

    assert counts == {"DETAIL_STATUS_MISSING": 1, "HTTP_ERROR": 4}
    assert examples == {"DETAIL_STATUS_MISSING": ["5"], "HTTP_ERROR": ["1", "2", "3"]}


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
