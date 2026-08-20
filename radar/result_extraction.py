from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from lxml import html

from radar.analog_search import repair_mojibake
from radar import historical_result_extraction_version
from radar.live_collection import section_url
from radar.models import AnalogResultResolutionDiagnostic, AssembledHistoricalResult, HistoricalAnalog


FINAL_PROTOCOL = "FINAL_PROTOCOL"
AUCTION_PROTOCOL = "AUCTION_PROTOCOL"
APPLICATION_REVIEW_PROTOCOL = "APPLICATION_REVIEW_PROTOCOL"
SUMMARY_PROTOCOL = "SUMMARY_PROTOCOL"
CONTRACT = "CONTRACT"
RESULT_NOTICE = "RESULT_NOTICE"
CLARIFICATION = "CLARIFICATION"
OTHER = "OTHER"


@dataclass
class ResolvedPage:
    url: str
    page_type: str
    source_section: str
    status_code: int | None
    html_text: str
    cache_used: bool = False


@dataclass
class ProtocolExtractionDiagnostic:
    procurement_number: str
    document_url: str
    document_type: str
    classification_score: int
    classification_reasons: list[str]
    detected_format: str
    parser_used: str
    tables_found: int
    rows_inspected: int
    candidate_price_rows: list[dict[str, Any]]
    participant_rows: list[dict[str, Any]]
    winner_candidates: list[dict[str, Any]]
    rejected_numeric_candidates: list[str]
    extracted_fields: dict[str, Any]
    parser_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "procurement_number": self.procurement_number,
            "document_url": self.document_url,
            "document_type": self.document_type,
            "classification_score": self.classification_score,
            "classification_reasons": self.classification_reasons,
            "detected_format": self.detected_format,
            "parser_used": self.parser_used,
            "tables_found": self.tables_found,
            "rows_inspected": self.rows_inspected,
            "candidate_price_rows": self.candidate_price_rows,
            "participant_rows": self.participant_rows,
            "winner_candidates": self.winner_candidates,
            "rejected_numeric_candidates": self.rejected_numeric_candidates,
            "extracted_fields": self.extracted_fields,
            "parser_warnings": self.parser_warnings,
        }


def _default_fetch(url: str) -> tuple[int | None, str]:
    import requests

    response = requests.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    return response.status_code, response.text


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", repair_mojibake(value or "")).strip()


def parse_money(value: str) -> float | None:
    matches = re.findall(r"\d[\d\s\xa0]*(?:[,.]\d{1,2})?", value.replace("\xa0", " "))
    if not matches:
        return None
    try:
        return float(matches[-1].replace(" ", "").replace("\xa0", "").replace(",", "."))
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    match = re.search(r"\d{1,5}", value or "")
    return int(match.group(0)) if match else None


def parse_tables(page: ResolvedPage) -> list[list[list[str]]]:
    try:
        doc = html.fromstring(page.html_text)
    except Exception:
        return []
    result: list[list[list[str]]] = []
    for table in doc.xpath("//table"):
        rows: list[list[str]] = []
        for tr in table.xpath(".//tr"):
            cells = [normalize_space(" ".join(cell.xpath(".//text()"))) for cell in tr.xpath("./th|./td")]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        if rows:
            result.append(rows)
    return result


def classify_result_document(url: str, link_text: str = "", source_section: str = "", text: str = "") -> tuple[str, int, list[str]]:
    lowered_url = (url or "").lower()
    lowered_text = normalize_space(f"{link_text} {text}").lower()
    reasons: list[str] = []
    score = 0
    doc_type = OTHER
    if "contract" in lowered_url or "договор" in lowered_text:
        doc_type = CONTRACT
        score += 90
        reasons.append("contract path or label")
    if "protocol-bid-list" in lowered_url or "список заявок" in lowered_text:
        doc_type = APPLICATION_REVIEW_PROTOCOL
        score += 85
        reasons.append("bid list / application review structure")
    if "protocol-main-info" in lowered_url or "подведения итогов" in lowered_text:
        doc_type = FINAL_PROTOCOL
        score += 80
        reasons.append("final protocol label")
    if "protocol-results-info" in lowered_url or "решение комиссии" in lowered_text:
        doc_type = SUMMARY_PROTOCOL
        score += 70
        reasons.append("commission decision page")
    if "result-info-comparison" in lowered_url or "сопоставления" in lowered_text:
        doc_type = AUCTION_PROTOCOL
        score += 75
        reasons.append("comparison result page")
    if "result-info-view-grade" in lowered_url or "заключение договора" in lowered_text:
        doc_type = FINAL_PROTOCOL
        score += 80
        reasons.append("award/final grading page")
    if "result-info-review" in lowered_url or "рассмотрения" in lowered_text:
        doc_type = APPLICATION_REVIEW_PROTOCOL
        score += 75
        reasons.append("review result page")
    if "supplier-results" in lowered_url or source_section == "results":
        score += 20
        reasons.append("result section source")
        if doc_type == OTHER:
            doc_type = RESULT_NOTICE
    if "clarification" in lowered_url:
        doc_type = CLARIFICATION
        score += 60
        reasons.append("clarification path")
    return doc_type, score, reasons or ["no strong document-type signals"]


def _fetch_page(url: str, fetch: Callable[[str], tuple[int | None, str]], cache_dir: Path | None, cache_key: str, use_cache: bool) -> ResolvedPage:
    cache_path = cache_dir / f"{cache_key}.html" if cache_dir else None
    if use_cache and cache_path and cache_path.exists():
        return ResolvedPage(url=url, page_type=_page_type(url), source_section=cache_key, status_code=200, html_text=cache_path.read_text(encoding="utf-8", errors="ignore"), cache_used=True)
    status_code, text = fetch(url)
    if cache_path and status_code and status_code < 400:
        cache_path.write_text(text, encoding="utf-8")
    return ResolvedPage(url=url, page_type=_page_type(url), source_section=cache_key, status_code=status_code, html_text=text)


def _page_type(url: str) -> str:
    lowered = url.lower()
    if "protocol" in lowered:
        return "protocol"
    if "contract" in lowered:
        return "contract"
    if "supplier-results" in lowered:
        return "results"
    if "common-info" in lowered:
        return "common"
    return "other"


def _page_links(page: ResolvedPage) -> list[tuple[str, str]]:
    try:
        doc = html.fromstring(page.html_text)
    except Exception:
        return []
    links: list[tuple[str, str]] = []
    for anchor in doc.xpath("//a[@href]"):
        href = anchor.get("href") or ""
        text = normalize_space(" ".join(anchor.xpath(".//text()")))
        if href:
            links.append((urljoin(page.url, href), text))
    return links


def resolve_result_sources(
    analog: HistoricalAnalog,
    *,
    fetch: Callable[[str], tuple[int | None, str]] | None = None,
    cache_dir: Path | None = None,
    resume: bool = False,
) -> tuple[AnalogResultResolutionDiagnostic, list[ResolvedPage]]:
    fetch = fetch or _default_fetch
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = AnalogResultResolutionDiagnostic(
        procurement_number=analog.analog_procurement_number,
        law=analog.law,
        source_url=analog.source_url,
        common_url=analog.source_url,
    )
    pages: list[ResolvedPage] = []
    if not analog.source_url:
        diagnostic.errors.append("MISSING_SOURCE_URL")
        return diagnostic, pages

    def add_page(url: str, section: str) -> ResolvedPage:
        page = _fetch_page(url, fetch, cache_dir, f"{analog.analog_procurement_number}_{section}", resume)
        diagnostic.urls_attempted.append(url)
        diagnostic.http_statuses[url] = page.status_code
        diagnostic.page_types_detected.append(page.page_type)
        if page.cache_used:
            diagnostic.cache_used = True
        pages.append(page)
        return page

    common_page = add_page(analog.source_url, "common")
    links = _page_links(common_page)
    diagnostic.document_links_found.extend(url for url, _ in links if "print" in url or "signview" in url)

    if analog.law == "44-FZ":
        result_url = section_url(analog.source_url, "results")
        diagnostic.result_url = result_url
        result_page = add_page(result_url, "results")
        result_links = _page_links(result_page)
        protocol_links = [url for url, _ in result_links if "protocol/protocol-main-info.html" in url]
        if protocol_links:
            diagnostic.protocol_url = protocol_links[0]
            diagnostic.protocol_documents_found.extend(protocol_links)
            protocol_page = add_page(protocol_links[0], "protocol_main")
            for url, _ in _page_links(protocol_page):
                if "protocol-bid-list.html" in url:
                    add_page(url, "protocol_bid_list")
                    diagnostic.protocol_documents_found.append(url)
                elif "protocol-docs.html" in url:
                    add_page(url, "protocol_docs")
                    diagnostic.protocol_documents_found.append(url)
            diagnostic.resolution_strategy = "DIRECT_RESULT_URL"
            diagnostic.resolution_status = "RESOLVED_PROTOCOL_PAGE"
            diagnostic.final_resolved_url = protocol_links[0]
            diagnostic.result_source_type = "PROTOCOL_PAGE"
        elif result_page.status_code and result_page.status_code < 400:
            diagnostic.resolution_strategy = "DIRECT_RESULT_URL"
            diagnostic.resolution_status = "PARTIAL"
            diagnostic.final_resolved_url = result_url
            diagnostic.result_source_type = "RESULT_PAGE"
        else:
            diagnostic.resolution_status = "NOT_FOUND"
    else:
        protocols_url = next((url for url, _ in links if "notice223/protocols.html" in url), "")
        contract_url = next((url for url, _ in links if "notice223/contract-info.html" in url), "")
        if protocols_url:
            diagnostic.result_url = protocols_url
            protocols_page = add_page(protocols_url, "protocols")
            protocol_links = _page_links(protocols_page)
            common_protocol = next((url for url, text in protocol_links if "protocol223/protocol-common-info.html" in url or "Иной протокол" in text), "")
            if common_protocol:
                diagnostic.protocol_url = common_protocol
                protocol_page = add_page(common_protocol, "protocol_common")
                diagnostic.protocol_documents_found.append(common_protocol)
                for url, _ in _page_links(protocol_page):
                    if any(key in url for key in ["protocol-bid-info", "protocol-results-info", "result-info-review", "result-info-comparison", "result-info-view-grade", "document-info"]):
                        add_page(url, _page_type(url))
                        diagnostic.protocol_documents_found.append(url)
        if contract_url:
            diagnostic.contract_url = contract_url
            contract_page = add_page(contract_url, "contract_info")
            for url, _ in _page_links(contract_page):
                if "/epz/contractfz223/card/contract-info.html" in url:
                    add_page(url, "contract_registry")
                    diagnostic.document_links_found.append(url)
        if diagnostic.protocol_url:
            diagnostic.resolution_strategy = "NAVIGATION_FROM_COMMON"
            diagnostic.resolution_status = "RESOLVED_PROTOCOL_PAGE"
            diagnostic.final_resolved_url = diagnostic.protocol_url
            diagnostic.result_source_type = "PROTOCOL_PAGE"
        elif diagnostic.contract_url:
            diagnostic.resolution_strategy = "CONTRACT_REGISTRY"
            diagnostic.resolution_status = "PARTIAL"
            diagnostic.final_resolved_url = diagnostic.contract_url
            diagnostic.result_source_type = "CONTRACT_REGISTRY"
        else:
            diagnostic.resolution_status = "NOT_FOUND"

    return diagnostic, pages


def _extract_from_44_bid_list(page: ResolvedPage, analog: HistoricalAnalog) -> tuple[dict[str, Any], ProtocolExtractionDiagnostic]:
    tables = parse_tables(page)
    participant_rows: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []
    winner_candidates: list[dict[str, Any]] = []
    fields: dict[str, Any] = {}
    warnings: list[str] = []
    for table in tables:
        if not table:
            continue
        header = " | ".join(table[0]).lower()
        if "идентификационный номер участника" not in header or "предлагаемая цена" not in header:
            continue
        for row in table[1:]:
            if len(row) < 5:
                continue
            price = parse_money(row[-1])
            participant_rows.append({"participant_id": row[0], "review_result": row[2], "ordinal": row[3], "price": price})
            if price is not None:
                price_rows.append({"price": price, "row": row})
            if "победител" in row[3].lower():
                winner_candidates.append({"winner_identifier": row[0], "row": row})
        if participant_rows:
            fields["participant_count"] = len(participant_rows)
            fields["admitted_participant_count"] = sum(1 for row in participant_rows if "соответствует" in row["review_result"].lower() or "допущ" in row["review_result"].lower())
        if price_rows:
            winner_price = price_rows[0]["price"]
            for row in participant_rows:
                if "победител" in row["ordinal"].lower() and row["price"] is not None:
                    winner_price = row["price"]
                    fields["winner_identifier"] = row["participant_id"]
                    break
            fields["final_price"] = winner_price
    diagnostic = ProtocolExtractionDiagnostic(
        procurement_number=analog.analog_procurement_number,
        document_url=page.url,
        document_type=APPLICATION_REVIEW_PROTOCOL,
        classification_score=90,
        classification_reasons=["44-FZ protocol-bid-list table"],
        detected_format="HTML",
        parser_used="LXML_TABLE_44_BID_LIST",
        tables_found=len(tables),
        rows_inspected=sum(len(table) for table in tables),
        candidate_price_rows=price_rows,
        participant_rows=participant_rows,
        winner_candidates=winner_candidates,
        rejected_numeric_candidates=[],
        extracted_fields=fields,
        parser_warnings=warnings,
    )
    return fields, diagnostic


def _extract_from_223_bid_info(page: ResolvedPage, analog: HistoricalAnalog) -> tuple[dict[str, Any], ProtocolExtractionDiagnostic]:
    tables = parse_tables(page)
    fields: dict[str, Any] = {}
    participant_rows: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []
    winner_candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    for table in tables:
        if not table:
            continue
        header = " | ".join(table[0]).lower()
        if "количество заявок" in header and len(table) > 1:
            count = parse_int(" ".join(table[1]))
            if count is not None:
                fields["participant_count"] = count
        if "ценовое предложение" in header or "участник" in header:
            for row in table[1:]:
                if len(row) < 4:
                    continue
                price = parse_money(row[-1])
                participant_rows.append({"participant": row[1], "price": price, "submitted_at": row[2]})
                if price is not None:
                    price_rows.append({"price": price, "row": row})
                    winner_candidates.append({"winner_name": row[1], "price": price})
    if participant_rows:
        fields["participant_count"] = fields.get("participant_count", len(participant_rows))
        fields["final_price"] = min((row["price"] for row in participant_rows if row["price"] is not None), default=None)
        if winner_candidates:
            fields["winner_name"] = winner_candidates[0]["winner_name"]
    diagnostic = ProtocolExtractionDiagnostic(
        procurement_number=analog.analog_procurement_number,
        document_url=page.url,
        document_type=FINAL_PROTOCOL,
        classification_score=85,
        classification_reasons=["223-FZ protocol-bid-info table"],
        detected_format="HTML",
        parser_used="LXML_TABLE_223_BID_INFO",
        tables_found=len(tables),
        rows_inspected=sum(len(table) for table in tables),
        candidate_price_rows=price_rows,
        participant_rows=participant_rows,
        winner_candidates=winner_candidates,
        rejected_numeric_candidates=[],
        extracted_fields=fields,
        parser_warnings=warnings,
    )
    return fields, diagnostic


def _extract_from_223_review(page: ResolvedPage, analog: HistoricalAnalog) -> tuple[dict[str, Any], ProtocolExtractionDiagnostic]:
    tables = parse_tables(page)
    fields: dict[str, Any] = {}
    participant_rows: list[dict[str, Any]] = []
    winner_candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    for table in tables:
        if not table:
            continue
        header = " | ".join(table[0]).lower()
        if "участник" not in header or "решение комиссии" not in header:
            continue
        for row in table[1:]:
            if len(row) < 4:
                continue
            participant_rows.append({"participant": row[2], "decision": row[-1]})
            if "допущ" in row[-1].lower():
                winner_candidates.append({"winner_name": row[2], "decision": row[-1]})
        if participant_rows:
            fields["admitted_participant_count"] = sum(1 for row in participant_rows if "допущ" in row["decision"].lower())
            if len(participant_rows) == 1:
                fields["winner_name"] = participant_rows[0]["participant"]
    diagnostic = ProtocolExtractionDiagnostic(
        procurement_number=analog.analog_procurement_number,
        document_url=page.url,
        document_type=APPLICATION_REVIEW_PROTOCOL,
        classification_score=80,
        classification_reasons=["223-FZ result-info-review table"],
        detected_format="HTML",
        parser_used="LXML_TABLE_223_REVIEW",
        tables_found=len(tables),
        rows_inspected=sum(len(table) for table in tables),
        candidate_price_rows=[],
        participant_rows=participant_rows,
        winner_candidates=winner_candidates,
        rejected_numeric_candidates=[],
        extracted_fields=fields,
        parser_warnings=warnings,
    )
    return fields, diagnostic


def extract_from_pages(analog: HistoricalAnalog, pages: list[ResolvedPage]) -> tuple[AssembledHistoricalResult, list[ProtocolExtractionDiagnostic]]:
    assembled = AssembledHistoricalResult(procurement_number=analog.analog_procurement_number, nmck=analog.nmck)
    if analog.nmck is not None:
        assembled.nmck_evidence.append({"source": analog.source_url, "value": analog.nmck, "field": "nmck"})
    diagnostics: list[ProtocolExtractionDiagnostic] = []
    extracted_chunks: list[dict[str, Any]] = []
    for page in pages:
        fields: dict[str, Any] = {}
        extraction_diag: ProtocolExtractionDiagnostic | None = None
        if "protocol-bid-list" in page.url:
            fields, extraction_diag = _extract_from_44_bid_list(page, analog)
        elif "protocol-bid-info" in page.url:
            fields, extraction_diag = _extract_from_223_bid_info(page, analog)
        elif "result-info-review" in page.url or "protocol-results-info" in page.url or "result-info-view-grade" in page.url:
            fields, extraction_diag = _extract_from_223_review(page, analog)
        if extraction_diag is not None:
            diagnostics.append(extraction_diag)
        if fields:
            extracted_chunks.append({"url": page.url, "fields": fields})

    price_values = [(chunk["fields"]["final_price"], chunk["url"]) for chunk in extracted_chunks if chunk["fields"].get("final_price") is not None]
    participant_values = [(chunk["fields"]["participant_count"], chunk["url"]) for chunk in extracted_chunks if chunk["fields"].get("participant_count") is not None]
    admitted_values = [(chunk["fields"]["admitted_participant_count"], chunk["url"]) for chunk in extracted_chunks if chunk["fields"].get("admitted_participant_count") is not None]
    winner_values = [(chunk["fields"]["winner_name"], chunk["url"]) for chunk in extracted_chunks if chunk["fields"].get("winner_name")]
    winner_id_values = [(chunk["fields"]["winner_identifier"], chunk["url"]) for chunk in extracted_chunks if chunk["fields"].get("winner_identifier")]

    if price_values:
        unique_prices = {round(value, 2) for value, _ in price_values}
        if len(unique_prices) > 1:
            assembled.conflicts.append(f"multiple final price candidates: {sorted(unique_prices)}")
        assembled.final_price = min(unique_prices)
        assembled.final_price_evidence = [{"source": url, "value": value} for value, url in price_values]
    if participant_values:
        unique_counts = {value for value, _ in participant_values}
        assembled.participant_count = max(unique_counts)
        assembled.participant_count_evidence = [{"source": url, "value": value} for value, url in participant_values]
    if admitted_values:
        unique_counts = {value for value, _ in admitted_values}
        assembled.admitted_participant_count = max(unique_counts)
        assembled.admitted_count_evidence = [{"source": url, "value": value} for value, url in admitted_values]
    if winner_values:
        assembled.winner_name = winner_values[0][0]
        assembled.winner_evidence = [{"source": url, "value": value} for value, url in winner_values]
    if winner_id_values:
        assembled.winner_identifier = winner_id_values[0][0]
        if not assembled.winner_evidence:
            assembled.winner_evidence = [{"source": url, "value": value} for value, url in winner_id_values]
    if assembled.nmck is not None and assembled.final_price is not None and assembled.final_price <= assembled.nmck:
        assembled.reduction_percent = round((assembled.nmck - assembled.final_price) / assembled.nmck * 100, 2)
        assembled.reduction_inputs = {"nmck": assembled.nmck, "final_price": assembled.final_price}
    elif assembled.final_price is not None and assembled.nmck is not None:
        assembled.warnings.append("final_price exceeds nmck; reduction not calculated")

    if assembled.nmck is not None and assembled.final_price is not None and (assembled.participant_count is not None or assembled.admitted_participant_count is not None):
        assembled.completeness = "COMPLETE"
        assembled.confidence = "MEDIUM"
    elif assembled.nmck is not None and assembled.final_price is not None:
        assembled.completeness = "PARTIAL_PRICE"
        assembled.confidence = "MEDIUM"
    elif assembled.participant_count is not None or assembled.admitted_participant_count is not None:
        assembled.completeness = "PARTIAL_PARTICIPANTS"
        assembled.confidence = "LOW"
    elif assembled.winner_name or assembled.winner_identifier:
        assembled.completeness = "PARTIAL_OTHER"
        assembled.confidence = "LOW"
    else:
        assembled.completeness = "NO_USABLE_RESULT"
        assembled.confidence = "LOW"
    return assembled, diagnostics


def collect_and_assemble_result(
    analog: HistoricalAnalog,
    *,
    fetch: Callable[[str], tuple[int | None, str]] | None = None,
    cache_dir: Path | None = None,
    resume: bool = False,
) -> tuple[HistoricalAnalog, AnalogResultResolutionDiagnostic, AssembledHistoricalResult, list[ProtocolExtractionDiagnostic]]:
    diagnostic, pages = resolve_result_sources(analog, fetch=fetch, cache_dir=cache_dir, resume=resume)
    assembled, protocol_diags = extract_from_pages(analog, pages)

    analog.result_url = diagnostic.result_url
    analog.protocol_url = diagnostic.protocol_url
    analog.contract_url = diagnostic.contract_url
    analog.result_source_type = diagnostic.result_source_type
    analog.result_resolution_status = diagnostic.resolution_status
    analog.result_cache_used = diagnostic.cache_used
    analog.contract_price = assembled.final_price
    analog.participant_count = assembled.participant_count
    analog.admitted_participant_count = assembled.admitted_participant_count
    analog.winner_name = assembled.winner_name
    analog.winner_identifier = assembled.winner_identifier
    analog.reduction_percent = assembled.reduction_percent
    analog.result_data_status = assembled.completeness
    analog.result_confidence = assembled.confidence
    analog.evidence.append(
        {
            "type": "assembled_historical_result",
            "version": historical_result_extraction_version,
            "resolution_status": diagnostic.resolution_status,
            "result_source_type": diagnostic.result_source_type,
            "assembled_result": assembled.to_dict(),
        }
    )
    if cache_dir:
        meta_path = cache_dir / f"{analog.analog_procurement_number}_result_meta.json"
        meta_payload = {
            "historical_result_extraction_version": historical_result_extraction_version,
            "diagnostic": diagnostic.to_dict(),
            "assembled_result": assembled.to_dict(),
            "fingerprint": hash(json.dumps(assembled.to_dict(), ensure_ascii=False, sort_keys=True)),
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return analog, diagnostic, assembled, protocol_diags
