from __future__ import annotations

from pathlib import Path

from radar.competition_metrics import calculate_competition_metrics
from radar.config import RadarConfig
from radar.models import HistoricalAnalog
from radar.result_extraction import (
    ResolvedPage,
    classify_result_document,
    collect_and_assemble_result,
    extract_from_pages,
    resolve_result_sources,
)


def fetch_from_map(mapping: dict[str, tuple[int, str]]):
    def _fetch(url: str) -> tuple[int, str]:
        if url not in mapping:
            raise AssertionError(f"unexpected url: {url}")
        return mapping[url]

    return _fetch


def test_classify_protocol_document_types() -> None:
    assert classify_result_document("https://zakupki.gov.ru/epz/order/notice/ea20/view/protocol/protocol-bid-list.html", "", "", "")[0] == "APPLICATION_REVIEW_PROTOCOL"
    assert classify_result_document("https://zakupki.gov.ru/epz/order/notice/protocol223/result-info-view-grade.html", "", "", "заключение договора")[0] == "FINAL_PROTOCOL"
    assert classify_result_document("https://zakupki.gov.ru/epz/order/notice/notice223/contract-info.html", "Договор", "", "")[0] == "CONTRACT"


def test_44fz_resolution_finds_protocol_pages() -> None:
    analog = HistoricalAnalog(
        source_procurement_number="s",
        analog_procurement_number="a1",
        law="44-FZ",
        source_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=a1",
    )
    result_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/supplier-results.html?regNumber=a1"
    protocol_main = "https://zakupki.gov.ru/epz/order/notice/ea20/view/protocol/protocol-main-info.html?regNumber=a1&type=iea&version=1"
    protocol_bids = "https://zakupki.gov.ru/epz/order/notice/ea20/view/protocol/protocol-bid-list.html?regNumber=a1&type=iea&version=1"
    mapping = {
        analog.source_url: (200, "<html><body></body></html>"),
        result_url: (200, f'<a href="{protocol_main}">Протокол</a>'),
        protocol_main: (200, f'<a href="{protocol_bids}">Список заявок</a>'),
        protocol_bids: (200, "<table><tr><th>Идентификационный номер участника</th><th>Дата</th><th>Результат рассмотрения заявки</th><th>Порядковый номер</th><th>Предлагаемая цена</th></tr></table>"),
    }
    diagnostic, pages = resolve_result_sources(analog, fetch=fetch_from_map(mapping))
    assert diagnostic.resolution_status == "RESOLVED_PROTOCOL_PAGE"
    assert diagnostic.protocol_url == protocol_main
    assert any("protocol-bid-list" in page.url for page in pages)


def test_223fz_resolution_finds_protocol_and_contract_paths() -> None:
    analog = HistoricalAnalog(
        source_procurement_number="s",
        analog_procurement_number="32616252409",
        law="223-FZ",
        source_url="https://zakupki.gov.ru/223/purchase/public/purchase/info/common-info.html?regNumber=32616252409",
    )
    protocols = "https://zakupki.gov.ru/epz/order/notice/notice223/protocols.html?purchaseNoticeNumber=32616252409"
    contract_info = "https://zakupki.gov.ru/epz/order/notice/notice223/contract-info.html?purchaseNoticeNumber=32616252409"
    protocol_common = "https://zakupki.gov.ru/epz/order/notice/protocol223/protocol-common-info.html?protocolGuid=p1&purchaseNoticeNumber=32616252409"
    protocol_bid = "https://zakupki.gov.ru/epz/order/notice/protocol223/protocol-bid-info.html?protocolGuid=p1&purchaseNoticeNumber=32616252409"
    mapping = {
        analog.source_url: (200, f'<a href="{protocols}">Протоколы</a><a href="{contract_info}">Договор</a>'),
        protocols: (200, f'<a href="{protocol_common}">Иной протокол №1</a>'),
        protocol_common: (200, f'<a href="{protocol_bid}">Список заявок</a>'),
        protocol_bid: (200, "<html><body></body></html>"),
        contract_info: (200, '<a href="/epz/contractfz223/card/contract-info.html?reestrNumber=1">Договор №1</a>'),
        "https://zakupki.gov.ru/epz/contractfz223/card/contract-info.html?reestrNumber=1": (200, "<html><body></body></html>"),
    }
    diagnostic, pages = resolve_result_sources(analog, fetch=fetch_from_map(mapping))
    assert diagnostic.resolution_status == "RESOLVED_PROTOCOL_PAGE"
    assert diagnostic.protocol_url == protocol_common
    assert diagnostic.contract_url == contract_info
    assert any("contractfz223/card/contract-info.html" in page.url for page in pages)


def test_extract_44_bid_list_fields() -> None:
    analog = HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a1", nmck=100000)
    page = ResolvedPage(
        url="https://zakupki.gov.ru/epz/order/notice/ea20/view/protocol/protocol-bid-list.html?regNumber=a1&type=iea&version=1",
        page_type="protocol",
        source_section="protocol_bid_list",
        status_code=200,
        html_text="""
        <table>
          <tr><th>Идентификационный номер участника</th><th>Дата и время подачи заявки</th><th>Результат рассмотрения заявки</th><th>Порядковый номер</th><th>Предлагаемая цена</th></tr>
          <tr><td>111</td><td>01.01.2026</td><td>Соответствует требованиям</td><td>1 - Победитель</td><td>90 000,00 ₽</td></tr>
          <tr><td>222</td><td>01.01.2026</td><td>Соответствует требованиям</td><td>2 - Второй номер</td><td>91 000,00 ₽</td></tr>
        </table>
        """,
    )
    assembled, diagnostics = extract_from_pages(analog, [page])
    assert assembled.participant_count == 2
    assert assembled.admitted_participant_count == 2
    assert assembled.final_price == 90000
    assert assembled.winner_identifier == "111"
    assert diagnostics


def test_extract_223_protocol_pages_and_assemble_partial_and_final_fields() -> None:
    analog = HistoricalAnalog(source_procurement_number="s", analog_procurement_number="p1", nmck=730000)
    bid_page = ResolvedPage(
        url="https://zakupki.gov.ru/epz/order/notice/protocol223/protocol-bid-info.html?protocolGuid=p1&purchaseNoticeNumber=1",
        page_type="protocol",
        source_section="protocol-bid-info",
        status_code=200,
        html_text="""
        <table>
          <tr><th>Номер, наименование лота</th><th>Сведения о цене договора</th><th>Количество заявок</th></tr>
          <tr><td>1 Лот</td><td>Начальная (максимальная) цена договора: 730 000,00 ₽</td><td>1</td></tr>
        </table>
        <table>
          <tr><th>№</th><th>Участник</th><th>Дата и время регистрации заявки</th><th>Ценовое предложение</th></tr>
          <tr><td>-</td><td>ООО "ПАРАВЕБ" ИНН:7017421754</td><td>30.07.2026 15:45</td><td>730000</td></tr>
        </table>
        """,
    )
    review_page = ResolvedPage(
        url="https://zakupki.gov.ru/epz/order/notice/protocol223/result-info-review.html?protocolGuid=p1&purchaseNoticeNumber=1",
        page_type="protocol",
        source_section="result-info-review",
        status_code=200,
        html_text="""
        <table>
          <tr><th>Порядковый номер заявки</th><th>Дата и время регистрации заявки</th><th>Участник</th><th>Решение комиссии</th></tr>
          <tr><td>-</td><td>30.07.2026 15:45</td><td>ООО "ПАРАВЕБ" ИНН:7017421754</td><td>Допущен</td></tr>
        </table>
        """,
    )
    assembled, _ = extract_from_pages(analog, [bid_page, review_page])
    assert assembled.final_price == 730000
    assert assembled.participant_count == 1
    assert assembled.admitted_participant_count == 1
    assert 'ПАРАВЕБ' in assembled.winner_name
    assert assembled.completeness == "COMPLETE"


def test_collect_and_assemble_result_uses_cache_metadata(tmp_path: Path) -> None:
    analog = HistoricalAnalog(
        source_procurement_number="s",
        analog_procurement_number="a1",
        law="44-FZ",
        nmck=100000,
        source_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=a1",
    )
    result_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/supplier-results.html?regNumber=a1"
    protocol_main = "https://zakupki.gov.ru/epz/order/notice/ea20/view/protocol/protocol-main-info.html?regNumber=a1&type=iea&version=1"
    protocol_bids = "https://zakupki.gov.ru/epz/order/notice/ea20/view/protocol/protocol-bid-list.html?regNumber=a1&type=iea&version=1"
    mapping = {
        analog.source_url: (200, "<html><body></body></html>"),
        result_url: (200, f'<a href="{protocol_main}">Протокол</a>'),
        protocol_main: (200, f'<a href="{protocol_bids}">Список заявок</a>'),
        protocol_bids: (200, "<table><tr><th>Идентификационный номер участника</th><th>Дата</th><th>Результат рассмотрения заявки</th><th>Порядковый номер</th><th>Предлагаемая цена</th></tr><tr><td>1</td><td>d</td><td>Соответствует требованиям</td><td>1 - Победитель</td><td>90 000,00 ₽</td></tr></table>"),
    }
    updated, diagnostic, assembled, _ = collect_and_assemble_result(analog, fetch=fetch_from_map(mapping), cache_dir=tmp_path, resume=False)
    assert updated.contract_price == 90000
    assert assembled.completeness == "COMPLETE"
    assert (tmp_path / "a1_result_meta.json").exists()
    assert diagnostic.protocol_url == protocol_main


def test_partial_results_contribute_to_separate_metric_samples() -> None:
    config = RadarConfig()
    analogs = [
        HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a1", participant_count=5, result_data_status="PARTIAL_PARTICIPANTS"),
        HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a2", reduction_percent=12.5, result_data_status="PARTIAL_PRICE"),
        HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a3", winner_name="ООО Тест", result_data_status="PARTIAL_OTHER"),
    ]
    metrics = calculate_competition_metrics(analogs, config)
    assert metrics.participant_sample_size == 1
    assert metrics.reduction_sample_size == 1
    assert metrics.winner_sample_size == 1
    assert metrics.complete_result_sample_size == 0
    assert metrics.median_participants == 5
    assert metrics.median_reduction_percent == 12.5
