from datetime import datetime
from zoneinfo import ZoneInfo

import radar.discovery as discovery
from radar.config import RadarConfig
from radar.discovery import discover_cards, normalize_card
from radar.models import NormalizedStatus
from radar.search_profiles import SearchProfile


ACTIVE_STATUS_RAW = "РџРѕРґР°С‡Р° Р·Р°СЏРІРѕРє"


def _as_of() -> datetime:
    return datetime(2026, 8, 11, tzinfo=ZoneInfo("Europe/Moscow"))


def _profile() -> list[SearchProfile]:
    return [SearchProfile(name="test_profile", queries=["test query"])]


def _active_card(number: str, deadline: str) -> dict[str, str]:
    return {
        "procurement_number": number,
        "status_raw": ACTIVE_STATUS_RAW,
        "application_deadline": deadline,
        "source_url": f"https://example.test/{number}",
    }


def _run_with_cards(monkeypatch, raw_cards, verifications, limit: int = 20):
    config = RadarConfig()
    config.discovery.verify_open_status_from_detail_page = True
    config.discovery.verify_top_candidates_limit = limit

    async def fake_collect(request, config, remaining, max_pages):
        return [normalize_card(card, profile=request.source_profile, query=request.query_text) for card in raw_cards]

    monkeypatch.setattr(discovery, "_collect_with_existing_collector", fake_collect)
    monkeypatch.setattr(discovery, "verify_cards_from_detail", lambda cards, as_of, limit: verifications)
    monkeypatch.setattr(
        discovery,
        "is_provisionally_open",
        lambda card, as_of: (True, ["active status and future deadline"], type("Info", (), {"normalized_status": NormalizedStatus.APPLICATION_SUBMISSION})()),
    )

    return discover_cards(
        config,
        _profile(),
        as_of=_as_of(),
        discovery_mode="ACTIVE_ONLY",
    )


def test_provisionally_open_candidate_survives_detail_unavailable(monkeypatch) -> None:
    cards, diagnostics = _run_with_cards(
        monkeypatch,
        [_active_card("1", "2026-08-20")],
        [{"procurement_number": "1", "open_verification_status": "DETAIL_UNAVAILABLE", "open_verification_reasons": ["HTTP 500"]}],
    )

    assert [card.procurement_number for card in cards] == ["1"]
    assert diagnostics["detail_unavailable"] == 1
    assert diagnostics["detail_verifications_attempted"] == 1
    assert diagnostics["unique_cards"] == 1


def test_verified_open_candidate_survives(monkeypatch) -> None:
    cards, diagnostics = _run_with_cards(
        monkeypatch,
        [_active_card("1", "2026-08-20")],
        [{"procurement_number": "1", "open_verification_status": "VERIFIED_OPEN"}],
    )

    assert [card.procurement_number for card in cards] == ["1"]
    assert diagnostics["verified_open"] == 1


def test_verified_closed_candidate_is_removed(monkeypatch) -> None:
    cards, diagnostics = _run_with_cards(
        monkeypatch,
        [_active_card("1", "2026-08-20")],
        [{"procurement_number": "1", "open_verification_status": "VERIFIED_CLOSED"}],
    )

    assert cards == []
    assert diagnostics["verified_closed"] == 1
    assert diagnostics["detail_verification_rejected"] == 1
    assert diagnostics["no_open_candidate_reason"] == "ALL_PROVISIONAL_CANDIDATES_REJECTED_BY_DETAIL_VERIFICATION"


def test_verified_cancelled_candidate_is_removed(monkeypatch) -> None:
    cards, diagnostics = _run_with_cards(
        monkeypatch,
        [_active_card("1", "2026-08-20")],
        [{"procurement_number": "1", "open_verification_status": "VERIFIED_CANCELLED"}],
    )

    assert cards == []
    assert diagnostics["verified_cancelled"] == 1
    assert diagnostics["detail_verification_rejected"] == 1


def test_candidates_beyond_verification_limit_are_preserved(monkeypatch) -> None:
    cards, diagnostics = _run_with_cards(
        monkeypatch,
        [_active_card("1", "2026-08-20"), _active_card("2", "2026-08-21")],
        [{"procurement_number": "1", "open_verification_status": "VERIFIED_OPEN"}],
        limit=1,
    )

    assert [card.procurement_number for card in cards] == ["1", "2"]
    assert diagnostics["detail_verifications_attempted"] == 1
    assert diagnostics["detail_verification_skipped_due_to_limit"] == 1


def test_detail_unavailable_diagnostics_are_preserved(monkeypatch) -> None:
    cards, diagnostics = _run_with_cards(
        monkeypatch,
        [_active_card("1", "2026-08-20"), _active_card("2", "2026-08-21")],
        [
            {"procurement_number": "1", "open_verification_status": "DETAIL_UNAVAILABLE", "open_verification_reasons": ["timeout"], "detail_failure_code": "REQUEST_ERROR"},
            {"procurement_number": "2", "open_verification_status": "VERIFIED_CLOSED"},
        ],
    )

    assert [card.procurement_number for card in cards] == ["1"]
    assert diagnostics["detail_unavailable"] == 1
    assert diagnostics["detail_unavailable_by_code"] == {"REQUEST_ERROR": 1}
    assert diagnostics["detail_unavailable_examples_by_code"] == {"REQUEST_ERROR": ["1"]}
    assert diagnostics["detail_verification_rejected"] == 1
    assert diagnostics["open_verifications"][0]["open_verification_status"] == "DETAIL_UNAVAILABLE"


def test_detail_unavailable_by_code_counts_only_unavailable_rows(monkeypatch) -> None:
    cards, diagnostics = _run_with_cards(
        monkeypatch,
        [
            _active_card("1", "2026-08-20"),
            _active_card("2", "2026-08-21"),
            _active_card("3", "2026-08-22"),
            _active_card("4", "2026-08-23"),
        ],
        [
            {"procurement_number": "1", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "HTTP_ERROR"},
            {"procurement_number": "2", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "HTTP_ERROR"},
            {"procurement_number": "3", "open_verification_status": "DETAIL_UNAVAILABLE", "detail_failure_code": "DETAIL_STATUS_MISSING"},
            {"procurement_number": "4", "open_verification_status": "DEADLINE_CONFLICT", "detail_failure_code": ""},
        ],
    )

    assert [card.procurement_number for card in cards] == ["1", "2", "3"]
    assert diagnostics["detail_unavailable"] == 3
    assert diagnostics["detail_unavailable_by_code"] == {"DETAIL_STATUS_MISSING": 1, "HTTP_ERROR": 2}
    assert diagnostics["detail_unavailable_examples_by_code"] == {"DETAIL_STATUS_MISSING": ["3"], "HTTP_ERROR": ["1", "2"]}
