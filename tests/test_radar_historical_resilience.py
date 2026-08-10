from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.historical_live_validation import (
    classify_run_quality,
    run_live_historical_validation,
    select_live_validation_analogs,
)
from radar.models import EligibilityStatus, HistoricalAnalog, RadarAssessment, RadarDecision
from radar.reporting import write_reports
from radar.source_resolution import (
    SourceResolutionPolicy,
    extract_matching_links,
    resolve_procurement_source,
    sibling_section_urls,
)


NUMBER = "0122300036525000031"


def valid_html(number: str = NUMBER, title: str = "Разработка интернет-портала") -> str:
    return f"""
    <html><body>
      <a href="/epz/order/notice/eap20/view/documents.html?regNumber={number}">docs</a>
      <div>Номер закупки {number}</div>
      <div>Объект закупки: {title}</div>
      <div>Заказчик: Администрация тестового района</div>
      <div>Начальная (максимальная) цена 750 000,00</div>
    </body></html>
    """


def source_card():
    return normalize_card(
        {
            "procurement_number": NUMBER,
            "title": "Разработка интернет-портала личный кабинет",
            "customer": "Администрация тестового района",
            "law": "44-FZ",
            "procedure_type": "Электронный аукцион",
            "nmck": 750000,
            "status_normalized": "COMPLETED",
            "source_url": f"https://zakupki.gov.ru/epz/order/notice/eap20/view/documents.html?regNumber={NUMBER}",
            "raw_text": "портал личный кабинет API",
        }
    )


def assessment(decision: RadarDecision = RadarDecision.PRIORITY) -> RadarAssessment:
    return RadarAssessment(procurement_number=NUMBER, eligibility_status=EligibilityStatus.CLOSED, days_to_deadline=None, total_score=80, radar_decision=decision)


def test_single_404_does_not_confirm_not_found() -> None:
    def fetch(_url: str):
        return 404, _url, "<html>404 Not Found</html>"

    result = resolve_procurement_source(NUMBER, source_url=f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={NUMBER}", fetch=fetch, policy=SourceResolutionPolicy(max_attempts_per_strategy=1))
    assert result.status == "TEMPORARILY_UNAVAILABLE"
    assert result.attempts[0].error_code == "SOURCE_404_TRANSIENT"


def test_exact_number_search_recovers_stale_direct_url() -> None:
    def fetch(url: str):
        if "common-info" in url:
            return 404, url, "<html>404 Not Found</html>"
        if "extendedsearch" in url:
            return 200, url, valid_html()
        return 200, url, valid_html()

    result = resolve_procurement_source(NUMBER, source_url=f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={NUMBER}", fetch=fetch)
    assert result.status == "RESOLVED_SEARCH_RECOVERY"
    assert result.source_card is not None
    assert result.source_card.nmck == 750000


def test_cached_last_known_good_url_is_reused(tmp_path: Path) -> None:
    cached = source_card().to_dict()
    (tmp_path / "latest.json").write_text(json.dumps({"items": [{"card": cached}]}, ensure_ascii=False), encoding="utf-8")

    def fetch(url: str):
        return 404, url, "<html>404 Not Found</html>"

    result = resolve_procurement_source(NUMBER, source_url=cached["source_url"], output_dir=tmp_path, fetch=fetch)
    assert result.status == "RESOLVED_CACHED"
    assert result.cache_used


def test_alternate_section_can_recover_sibling_links() -> None:
    urls = sibling_section_urls(f"https://zakupki.gov.ru/epz/order/notice/eap20/view/documents.html?regNumber={NUMBER}", NUMBER)
    assert any("common-info" in url for url in urls)
    assert any("supplier-results" in url for url in urls)


def test_source_mismatch_still_fails_hard() -> None:
    result = resolve_procurement_source(NUMBER, source_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=9999999999999999999", fetch=lambda url: (200, url, valid_html()))
    assert result.status == "NUMBER_MISMATCH"


def test_confirmed_exact_search_absence_produces_not_found() -> None:
    def fetch(url: str):
        if "extendedsearch" in url:
            return 200, url, "<html>Поиск не дал результатов</html>"
        return 404, url, "<html>404 Not Found</html>"

    result = resolve_procurement_source(NUMBER, fetch=fetch)
    assert result.status == "NOT_FOUND_CONFIRMED"


def test_extract_matching_links_requires_exact_number() -> None:
    html = valid_html(NUMBER) + valid_html("0122300036525000032")
    links = extract_matching_links(NUMBER, html)
    assert links
    assert all(NUMBER in link for link in links)


def test_blocked_run_does_not_overwrite_latest_success(tmp_path: Path) -> None:
    started = datetime.fromisoformat("2026-08-09T12:00:00+03:00")
    card = source_card()
    assess = assessment()
    write_reports(tmp_path, "success", started, started, started, [], {"run_quality_status": "SUCCESS"}, [card], [assess], [])
    latest_before = (tmp_path / "latest.json").read_text(encoding="utf-8")
    write_reports(tmp_path, "blocked", started, started, started, [], {"run_quality_status": "BLOCKED_EXTERNAL"}, [card], [assess], [])
    assert (tmp_path / "latest.json").read_text(encoding="utf-8") == latest_before
    assert (tmp_path / "latest_attempt.json").exists()
    assert (tmp_path / "runs_failed" / "blocked").exists()


def test_success_run_atomically_replaces_latest(tmp_path: Path) -> None:
    started = datetime.fromisoformat("2026-08-09T12:00:00+03:00")
    card = source_card()
    assess = assessment()
    write_reports(tmp_path, "r1", started, started, started, [], {"run_quality_status": "SUCCESS"}, [card], [assess], [])
    payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert payload["summary"]["run_id"] == "r1"
    assert not (tmp_path / "runs" / "r1.tmp").exists()


def test_raw_candidates_survive_result_extraction_failure(tmp_path: Path) -> None:
    config = RadarConfig()
    config.historical.similarity.minimum_score = 20

    def collector(_request, _config, _limit, _pages):
        return [source_card(), normalize_card({**source_card().to_dict(), "procurement_number": "90000000000000000001"})]

    result = run_live_historical_validation(source_card(), assessment(), config, output_dir=tmp_path, collector=collector, fetch=lambda _url: (_ for _ in ()).throw(RuntimeError("temporary result failure")))
    assert result.diagnostics["candidate_count_raw"] >= 1
    assert Path(result.output_paths["historical_live_diagnostics_json"]).exists()


def test_relaxed_similarity_fallback_is_labelled_and_floor_applied() -> None:
    config = RadarConfig()
    config.historical.similarity.minimum_score = 45
    src = source_card()
    analogs = [
        HistoricalAnalog(source_procurement_number=NUMBER, analog_procurement_number="a1", title="Разработка портала", customer=src.customer, nmck=740000),
        HistoricalAnalog(source_procurement_number=NUMBER, analog_procurement_number="a2", title="Поставка бумаги", customer="Other", nmck=1000),
    ]
    selected = select_live_validation_analogs(src, analogs, config)
    assert selected
    assert any("RELAXED_THRESHOLD" in item.mismatch_reasons or "SAME_CUSTOMER_FALLBACK" in item.mismatch_reasons for item in selected)
    assert all(item.similarity_score >= 30 for item in selected)


def test_insufficient_history_does_not_produce_reject_automatically(tmp_path: Path) -> None:
    config = RadarConfig()
    result = run_live_historical_validation(source_card(), assessment(RadarDecision.PRIORITY), config, output_dir=tmp_path, dry_run=True)
    adjusted = result.bundle.history_adjusted_assessment
    assert adjusted is not None
    assert adjusted.historical_adjustment == 0
    assert adjusted.history_adjusted_decision == RadarDecision.PRIORITY
    assert result.bundle.diagnostics["retrospective_history_adjusted_decision"] is None


def test_run_quality_classification() -> None:
    assert classify_run_quality(source_status="RESOLVED_LIVE", queries_attempted=1, raw_candidates=5, selected_analogs=1, usable_results=1, error_codes=[]) == "SUCCESS"
    assert classify_run_quality(source_status="RESOLVED_LIVE", queries_attempted=1, raw_candidates=5, selected_analogs=0, usable_results=0, error_codes=[]) == "PARTIAL_SUCCESS"
    assert classify_run_quality(source_status="TEMPORARILY_UNAVAILABLE", queries_attempted=0, raw_candidates=0, selected_analogs=0, usable_results=0, error_codes=["SOURCE_404_TRANSIENT"]) == "BLOCKED_EXTERNAL"


def test_session_parameters_are_redacted() -> None:
    def fetch(url: str):
        return 404, url + "&token=secret&session=abc", "<html>404 Not Found</html>"

    result = resolve_procurement_source(NUMBER, source_url=f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={NUMBER}", fetch=fetch, policy=SourceResolutionPolicy(max_attempts_per_strategy=1))
    serialized = json.dumps(result.to_dict(), ensure_ascii=False).lower()
    assert "secret" not in serialized
    assert "session=abc" not in serialized
