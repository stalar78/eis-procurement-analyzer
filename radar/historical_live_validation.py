from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urljoin

from radar.analog_search import completed_only_params, generate_historical_queries
from radar.competition_metrics import calculate_competition_metrics
from radar.config import RadarConfig
from radar.discovery import deduplicate_cards, normalize_card
from radar.historical import (
    HistoricalAssessmentBundle,
    assess_dumping_risk,
    build_customer_history,
    build_supplier_history,
    detect_repeated_procurements,
    history_adjustment,
    score_similarity,
    select_analogs,
)
from radar.live_collection import canonical_url_for_number, normalize_eis_url, section_url
from radar.models import HistoricalAnalog, RadarAssessment, RadarCard, RadarDecision
from radar.result_extraction import collect_and_assemble_result
from radar.search_request import build_eis_search_request, redact_url, request_from_url, serialize_eis_search_request
from radar.source_resolution import SourceResolutionResult


SOURCE_LABEL = "HISTORICAL_VALIDATION_SOURCE"
DECISION_CONTEXT = "HISTORICAL_VALIDATION"
MAX_RAW_CANDIDATES = 50
MAX_RESULT_COLLECTIONS = 10
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 30 * 1024 * 1024
RUN_QUALITY_SUCCESS = "SUCCESS"
RUN_QUALITY_PARTIAL = "PARTIAL_SUCCESS"
RUN_QUALITY_BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
RUN_QUALITY_BLOCKED_INTERNAL = "BLOCKED_INTERNAL"
RUN_QUALITY_FAILED = "FAILED"
EXPECTED_REFERENCES = {
    "0122300036525000031": {
        "nmck": 750000.0,
        "contract_price": 41500.0,
        "reduction_percent": 94.47,
        "participant_count_min": 51,
    },
    "0360100030524000979": {
        "nmck": 569066.67,
        "contract_price": 138783.88,
        "participant_count": 11,
        "winner_application_number": "52",
        "reduction_percent": 75.61,
    },
}


@dataclass
class LiveHistoricalValidationResult:
    source_card: RadarCard
    bundle: HistoricalAssessmentBundle
    historical_query_plan: list[dict[str, Any]]
    source_validation: dict[str, Any]
    analog_review: list[dict[str, Any]]
    competition_metric_evidence: dict[str, Any]
    diagnostics: dict[str, Any]
    raw_candidates: list[dict[str, Any]] = field(default_factory=list)
    unique_candidates: list[dict[str, Any]] = field(default_factory=list)
    scored_candidates: list[dict[str, Any]] = field(default_factory=list)
    analog_result_resolution: list[dict[str, Any]] = field(default_factory=list)
    protocol_extraction_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    assembled_historical_results: list[dict[str, Any]] = field(default_factory=list)
    competition_metric_samples: dict[str, Any] = field(default_factory=dict)
    markdown_path: str = ""
    output_paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_card": self.source_card.to_dict(),
            "bundle": self.bundle.to_dict(),
            "historical_query_plan": self.historical_query_plan,
            "source_validation": self.source_validation,
            "analog_review": self.analog_review,
            "competition_metric_evidence": self.competition_metric_evidence,
            "diagnostics": self.diagnostics,
            "raw_candidates": self.raw_candidates,
            "unique_candidates": self.unique_candidates,
            "scored_candidates": self.scored_candidates,
            "analog_result_resolution": self.analog_result_resolution,
            "protocol_extraction_diagnostics": self.protocol_extraction_diagnostics,
            "assembled_historical_results": self.assembled_historical_results,
            "competition_metric_samples": self.competition_metric_samples,
            "markdown_path": self.markdown_path,
            "output_paths": self.output_paths,
        }


def classify_run_quality(
    *,
    source_status: str,
    queries_attempted: int,
    raw_candidates: int,
    selected_analogs: int,
    usable_results: int,
    error_codes: list[str],
) -> str:
    source_resolved = source_status in {"RESOLVED_LIVE", "RESOLVED_SEARCH_RECOVERY", "RESOLVED_ALTERNATE_SECTION", "RESOLVED_CACHED", "PARTIAL_RESOLUTION"}
    if source_resolved and queries_attempted > 0 and selected_analogs > 0 and usable_results > 0:
        return RUN_QUALITY_SUCCESS
    if source_resolved and (raw_candidates > 0 or selected_analogs > 0):
        return RUN_QUALITY_PARTIAL
    external_errors = any(
        token in " ".join(error_codes)
        for token in ["SOURCE_", "EIS_", "404", "429", "timeout", "Timeout", "ERR_", "net::"]
    )
    if not source_resolved or external_errors:
        return RUN_QUALITY_BLOCKED_EXTERNAL
    return RUN_QUALITY_BLOCKED_INTERNAL


def validate_live_history_args(*, history_only: bool, allow_completed_source: bool, procurement_numbers: list[str], source_url: str | None) -> None:
    if allow_completed_source and not history_only:
        raise ValueError("--allow-completed-source is valid only with --history-only")
    if allow_completed_source and len(procurement_numbers) != 1:
        raise ValueError("--allow-completed-source requires exactly one --procurement-number")
    if source_url and len(procurement_numbers) == 1:
        normalize_eis_url(source_url, procurement_numbers[0])


def default_source_url(number: str, source_url: str | None = None) -> str:
    if source_url:
        return normalize_eis_url(source_url, number)[0]
    return canonical_url_for_number(number)


def mark_validation_source(card: RadarCard) -> RadarCard:
    if SOURCE_LABEL not in card.search_profiles:
        card.search_profiles.append(SOURCE_LABEL)
    card.status_normalized = "COMPLETED"
    card.raw_text = f"{card.raw_text}\n{SOURCE_LABEL}".strip()
    return card


def exclude_validation_source_from_active_assessment(assessment: RadarAssessment) -> None:
    assessment.radar_decision = RadarDecision.INSUFFICIENT_DATA
    assessment.total_score = 0
    assessment.positive_reasons = []
    assessment.negative_reasons.append("historical validation source only; no active participation recommendation")
    assessment.manual_review_questions = []


def parse_money(value: str) -> float | None:
    matches = re.findall(r"\d[\d\s]*(?:[,.]\d{1,2})?", value.replace("\xa0", " "))
    if not matches:
        return None
    candidate = matches[-1].replace(" ", "").replace(",", ".")
    try:
        return float(candidate)
    except ValueError:
        return None


def parse_first_int_near(text: str, labels: list[str]) -> int | None:
    for label in labels:
        match = re.search(rf"{label}.{{0,80}}?(\d{{1,4}})", text, re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))
    return None


def extract_result_values(text: str, nmck: float | None = None) -> dict[str, Any]:
    compact = re.sub(r"\s+", " ", text or "")
    money_labels = [
        r"цена контракта",
        r"предложение о цене",
        r"итоговая цена",
        r"contract price",
    ]
    contract_price = None
    for label in money_labels:
        match = re.search(rf"{label}.{{0,120}}?(\d[\d\s]*(?:[,.]\d{{1,2}})?)", compact, re.IGNORECASE)
        if match:
            contract_price = parse_money(match.group(1))
            break
    if contract_price is None:
        reductions = [parse_money(item) for item in re.findall(r"(\d[\d\s]*(?:[,.]\d{1,2})?)\s*(?:руб|₽)", compact, re.IGNORECASE)]
        plausible = [value for value in reductions if value is not None and (nmck is None or value <= nmck)]
        contract_price = min(plausible) if plausible else None
    reduction_percent = None
    if nmck and contract_price is not None and nmck > 0:
        reduction_percent = round((nmck - contract_price) / nmck * 100, 2)
    participant_count = parse_first_int_near(compact, [r"участник", r"заявок", r"допущен"])
    winner = ""
    winner_match = re.search(r"(?:победител[ья]|winner).{0,80}?([A-ZА-ЯЁ][^.;,\n]{3,120})", compact, re.IGNORECASE)
    if winner_match:
        candidate = winner_match.group(1).strip()
        if not re.fullmatch(r"[\d\s.,]+", candidate):
            winner = candidate
    return {
        "contract_price": contract_price,
        "participant_count": participant_count,
        "admitted_participant_count": participant_count,
        "reduction_percent": reduction_percent,
        "winner_name": winner,
    }


def extract_source_card_from_html(number: str, url: str, html: str) -> RadarCard:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text)
    title = ""
    title_match = re.search(r"(?:Объект закупки|Наименование объекта закупки|Наименование закупки|Object).{0,120}?([^|]{20,260})", text, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip(" :-")
    if not title:
        portal_match = re.search(r"([^.]{0,120}(?:портал|сайт|информационн\w+ систем\w+)[^.]{10,180})", text, re.IGNORECASE)
        if portal_match:
            title = portal_match.group(1).strip(" :-")
    customer = ""
    customer_match = re.search(r"(?:Заказчик|Организация).{0,80}?([A-ZА-ЯЁ][^|]{10,180})", text, re.IGNORECASE)
    if customer_match:
        customer = customer_match.group(1).strip(" :-")
    nmck = None
    nmck_match = re.search(r"(?:НМЦК|Начальная\s+\(максимальная\)\s+цена|Начальная цена).{0,120}?(\d[\d\s]*(?:[,.]\d{1,2})?)", text, re.IGNORECASE)
    if nmck_match:
        nmck = parse_money(nmck_match.group(1))
    return mark_validation_source(
        normalize_card(
            {
                "procurement_number": number,
                "title": title,
                "customer": customer,
                "law": "44-FZ" if "44" in text else "",
                "procedure_type": "Электронный аукцион" if "аукцион" in text.lower() else "",
                "status": "Определение поставщика завершено",
                "status_normalized": "COMPLETED",
                "nmck": nmck,
                "source_url": url,
                "raw_text": text[:5000],
            }
        )
    )


def resolve_source_card(number: str, source_url: str | None, fetch: Callable[[str], str] | None = None) -> tuple[RadarCard, dict[str, Any]]:
    url = default_source_url(number, source_url)
    diagnostics = {"procurement_number": number, "canonical_source_url": url, "status": "NOT_REQUESTED", "warnings": []}
    if fetch is None:
        import requests

        def fetch(target: str) -> str:
            response = requests.get(target, timeout=45)
            response.raise_for_status()
            return response.text

    attempted_urls = [url]
    search_url = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?" + urlencode(
        {
            "searchString": number,
            "morphology": "on",
            "search-filter": "Дате размещения",
            "pageNumber": "1",
            "sortDirection": "false",
            "recordsPerPage": "_50",
            "showLotsInfoHidden": "false",
            "sortBy": "UPDATE_DATE",
            "fz44": "on",
            "fz223": "on",
            "pc": "on",
            "selectedLaws": "FZ44,FZ223",
            "currencyIdGeneral": "-1",
        }
    )
    attempted_urls.append(search_url)
    attempted_urls.extend(
        [
            f"https://zakupki.gov.ru/epz/order/notice/eap20/view/documents.html?regNumber={number}",
            f"https://zakupki.gov.ru/epz/order/notice/printForm/view.html?regNumber={number}",
        ]
    )
    errors: list[str] = []
    for candidate_url in attempted_urls:
        try:
            html = fetch(candidate_url)
            if "404 Not Found" in html[:1000]:
                raise RuntimeError("HTTP 404 body")
            card = extract_source_card_from_html(number, candidate_url, html)
            if candidate_url == search_url:
                links = re.findall(r'href="([^"]*regNumber=' + re.escape(number) + r'[^"]*)"', html)
                document_links = [urljoin("https://zakupki.gov.ru", link) for link in links if "/notice/" in link and "documents" in link]
                if document_links:
                    card.source_url = document_links[0]
            diagnostics["canonical_source_url"] = card.source_url
            diagnostics["attempted_urls"] = attempted_urls
            diagnostics["status"] = "RESOLVED"
            if not card.title:
                diagnostics["warnings"].append("SOURCE_TITLE_NOT_EXTRACTED")
            if card.nmck is None:
                diagnostics["warnings"].append("SOURCE_NMCK_NOT_EXTRACTED")
            return card, diagnostics
        except Exception as error:
            errors.append(f"{candidate_url}: {error}")
    try:
        html = fetch(url)
        card = extract_source_card_from_html(number, url, html)
        diagnostics["status"] = "RESOLVED"
        if not card.title:
            diagnostics["warnings"].append("SOURCE_TITLE_NOT_EXTRACTED")
        if card.nmck is None:
            diagnostics["warnings"].append("SOURCE_NMCK_NOT_EXTRACTED")
        return card, diagnostics
    except Exception as error:
        diagnostics["status"] = "SOURCE_UNAVAILABLE"
        diagnostics["error"] = str(error)
        diagnostics["attempted_urls"] = attempted_urls
        diagnostics["errors"] = errors
        return mark_validation_source(normalize_card({"procurement_number": number, "source_url": url, "status_normalized": "COMPLETED"})), diagnostics


def load_cached_source_card(output_dir: str | Path, number: str) -> RadarCard | None:
    for path in [Path(output_dir) / "latest.json", Path(output_dir) / "historical_live_diagnostics.json"]:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "items" in data:
                for item in data.get("items", []):
                    card = item.get("card", {})
                    if card.get("procurement_number") == number and (card.get("title") or card.get("nmck") is not None):
                        return mark_validation_source(RadarCard(**card))
            card_data = data.get("source_resolution", {})
            if card_data.get("procurement_number") == number and (card_data.get("title") or card_data.get("nmck") is not None):
                return mark_validation_source(RadarCard(**card_data))
        except Exception:
            continue
    return None


def build_query_plan(card: RadarCard, config: RadarConfig) -> list[dict[str, Any]]:
    queries = generate_historical_queries(card, config, profile="r3a-live-validation")
    plan = []
    for query in queries[: config.historical.search.maximum_queries_per_procurement]:
        plan.append(
            {
                "source_procurement_number": card.procurement_number,
                "normalized_title": card.title,
                "customer": card.customer,
                "source_profile": SOURCE_LABEL,
                "extracted_high_value_terms": query.query_text.split()[:8],
                "query_text": query.query_text,
                "query_type": query.query_type,
                "query_weight": query.weight,
                "date_window": {"from": query.date_from, "to": query.date_to},
                "law_filter": query.law or "all",
                "completed_status_filter": completed_only_params(),
                "maximum_pages": config.historical.search.maximum_pages_per_query,
                "expected_candidate_budget": min(MAX_RAW_CANDIDATES, config.historical.search.maximum_raw_candidates),
            }
        )
    return plan


def search_filter_audit(plan: list[dict[str, Any]], config: RadarConfig, as_of: datetime | None = None) -> list[dict[str, Any]]:
    import collect_results

    rows = []
    for item in plan:
        request = build_eis_search_request(
            item["query_text"],
            config,
            source_profile="r3a-live-validation",
            as_of=as_of,
            discovery_mode="COMPLETED_ONLY",
        )
        url = serialize_eis_search_request(request, collect_results.DEFAULT_URL)
        roundtrip = request_from_url(url, source_profile="r3a-live-validation")
        rows.append(
            {
                "query_text": item["query_text"],
                "request_params": {"pc": "on", "af": "", "ca": ""},
                "resolved_url": redact_url(url),
                "filter_fingerprint": request.fingerprint(),
                "pagination_behavior": "pageNumber is changed only; completed pc=on is preserved",
                "completed_filter_present": "completed" in roundtrip.included_statuses,
                "active_only_params_absent": "application_submission" not in roundtrip.included_statuses,
                "status_distribution": {},
                "eis_limitations": ["EIS layout and availability may vary; result extraction is evidence-bounded."],
            }
        )
    return rows


def discover_historical_candidates(
    card: RadarCard,
    plan: list[dict[str, Any]],
    config: RadarConfig,
    *,
    dry_run: bool = False,
    collector: Callable[[Any, RadarConfig, int | None, int | None], list[RadarCard]] | None = None,
) -> tuple[list[HistoricalAnalog], dict[str, Any]]:
    diagnostics = {"queries_attempted": 0, "pages_requested": 0, "raw_cards": 0, "unique_cards": 0, "errors": [], "search_rows": [], "raw_candidate_cards": [], "unique_candidate_cards": []}
    if dry_run:
        return [], diagnostics
    if collector is None:
        from radar.discovery import _collect_with_existing_collector
        import asyncio

        def collector(request: Any, cfg: RadarConfig, limit: int | None, max_pages: int | None) -> list[RadarCard]:
            return asyncio.run(_collect_with_existing_collector(request, cfg, limit, max_pages))

    raw_cards: list[RadarCard] = []
    import collect_results

    for row in plan[: config.historical.search.maximum_queries_per_procurement]:
        if len(raw_cards) >= MAX_RAW_CANDIDATES:
            break
        request = build_eis_search_request(row["query_text"], config, source_profile="r3a-live-validation", discovery_mode="COMPLETED_ONLY")
        url = serialize_eis_search_request(request, collect_results.DEFAULT_URL)
        diagnostics["queries_attempted"] += 1
        diagnostics["pages_requested"] += config.historical.search.maximum_pages_per_query
        try:
            cards = collector(request, config, MAX_RAW_CANDIDATES - len(raw_cards), config.historical.search.maximum_pages_per_query)
            diagnostics["search_rows"].append({"query_text": row["query_text"], "requested_url": redact_url(url), "cards_found": len(cards), "filter_fingerprint": request.fingerprint()})
            raw_cards.extend(cards)
        except Exception as error:
            diagnostics["errors"].append(f"{row['query_text']}: {error}")
    unique = [item for item in deduplicate_cards(raw_cards) if item.procurement_number != card.procurement_number]
    diagnostics["raw_cards"] = len(raw_cards)
    diagnostics["unique_cards"] = len(unique)
    diagnostics["raw_candidate_cards"] = [item.to_dict() for item in raw_cards]
    diagnostics["unique_candidate_cards"] = [item.to_dict() for item in unique]
    analogs = [
        HistoricalAnalog(
            source_procurement_number=card.procurement_number,
            analog_procurement_number=item.procurement_number,
            title=item.title,
            customer=item.customer,
            law=item.law,
            procedure_type=item.procedure_type,
            region=item.region,
            nmck=item.nmck,
            source_url=item.source_url,
            published_at=item.published_at,
            result_data_status="PARTIAL",
            evidence=[{"type": "search_card", "source_url": item.source_url, "query": item.search_queries[:1]}],
        )
        for item in unique[:MAX_RAW_CANDIDATES]
    ]
    return analogs, diagnostics


def collect_result_for_analog(
    analog: HistoricalAnalog,
    *,
    fetch: Callable[[str], str] | None = None,
    cache_dir: Path | None = None,
    resume: bool = False,
    byte_budget: dict[str, int] | None = None,
) -> tuple[HistoricalAnalog, dict[str, Any]]:
    byte_budget = byte_budget if byte_budget is not None else {"total": 0}
    diagnostics = {
        "procurement_number": analog.analog_procurement_number,
        "attempted": False,
        "cache_hit": False,
        "bytes": 0,
        "status": "SKIPPED",
        "errors": [],
        "resolution_diagnostic": {},
        "assembled_result": {},
        "protocol_extraction_diagnostics": [],
    }
    if not analog.source_url:
        diagnostics["errors"].append("MISSING_SOURCE_URL")
        return analog, diagnostics
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    legacy_cache_path = cache_dir / f"{analog.analog_procurement_number}_result.html" if cache_dir else None

    def apply_legacy_text(text: str, *, cache_hit: bool = False) -> tuple[HistoricalAnalog, dict[str, Any]]:
        values = extract_result_values(text, analog.nmck)
        analog.contract_price = values["contract_price"]
        analog.participant_count = values["participant_count"]
        analog.admitted_participant_count = values["admitted_participant_count"]
        analog.reduction_percent = values["reduction_percent"]
        analog.winner_name = values["winner_name"]
        if analog.contract_price is not None and analog.participant_count is not None:
            analog.result_data_status = "COMPLETE"
            analog.result_confidence = "MEDIUM"
        elif analog.contract_price is not None:
            analog.result_data_status = "PARTIAL_PRICE"
            analog.result_confidence = "LOW"
        elif analog.participant_count is not None:
            analog.result_data_status = "PARTIAL_PARTICIPANTS"
            analog.result_confidence = "LOW"
        else:
            analog.result_data_status = "NO_USABLE_RESULT"
            analog.result_confidence = "LOW"
        analog.evidence.append({"type": "legacy_result_page", "confidence": analog.result_confidence, "fields": values})
        diagnostics["cache_hit"] = cache_hit
        diagnostics["assembled_result"] = {
            "procurement_number": analog.analog_procurement_number,
            "nmck": analog.nmck,
            "final_price": analog.contract_price,
            "participant_count": analog.participant_count,
            "admitted_participant_count": analog.admitted_participant_count,
            "winner_name": analog.winner_name,
            "reduction_percent": analog.reduction_percent,
            "completeness": analog.result_data_status,
            "confidence": analog.result_confidence,
        }
        diagnostics["status"] = analog.result_data_status
        return analog, diagnostics

    if resume and legacy_cache_path and legacy_cache_path.exists():
        return apply_legacy_text(legacy_cache_path.read_text(encoding="utf-8", errors="ignore"), cache_hit=True)

    def tuple_fetch(target: str) -> tuple[int | None, str]:
        if fetch is None:
            import requests

            response = requests.get(target, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
            return response.status_code, response.text
        result = fetch(target)
        if isinstance(result, tuple):
            if len(result) == 3:
                return result[0], result[2]
            if len(result) == 2:
                return result[0], result[1]
        return 200, str(result)

    diagnostics["attempted"] = True
    try:
        updated, resolution_diag, assembled_result, protocol_diags = collect_and_assemble_result(
            analog,
            fetch=tuple_fetch,
            cache_dir=cache_dir,
            resume=resume,
        )
        analog = updated
        diagnostics["cache_hit"] = resolution_diag.cache_used
        diagnostics["resolution_diagnostic"] = resolution_diag.to_dict()
        diagnostics["assembled_result"] = assembled_result.to_dict()
        diagnostics["protocol_extraction_diagnostics"] = [item.to_dict() for item in protocol_diags]
        size = 0
        if cache_dir:
            for path in cache_dir.glob(f"{analog.analog_procurement_number}_*.html"):
                size += path.stat().st_size
        diagnostics["bytes"] = size
        byte_budget["total"] += size
        if analog.result_data_status == "NO_USABLE_RESULT" and fetch is not None:
            legacy_text = ""
            for target in [section_url(analog.source_url, "results"), section_url(analog.source_url, "protocols"), analog.source_url]:
                try:
                    result = fetch(target)
                    candidate_text = result[2] if isinstance(result, tuple) and len(result) == 3 else result[1] if isinstance(result, tuple) and len(result) == 2 else str(result)
                    legacy_text += "\n" + candidate_text
                except Exception as error:
                    diagnostics["errors"].append(str(error))
            if legacy_text.strip():
                if legacy_cache_path:
                    legacy_cache_path.write_text(legacy_text, encoding="utf-8")
                return apply_legacy_text(legacy_text, cache_hit=False)
    except Exception as error:
        diagnostics["errors"].append(str(error))
        analog.result_data_status = "NO_USABLE_RESULT"
        analog.result_confidence = "LOW"
    diagnostics["status"] = analog.result_data_status
    return analog, diagnostics


def build_analog_review(source: RadarCard, analogs: list[HistoricalAnalog], config: RadarConfig) -> list[dict[str, Any]]:
    rows = []
    for analog in analogs:
        relationship = "missing budget"
        if source.nmck and analog.nmck:
            relationship = f"{round(analog.nmck / source.nmck, 3)}x source NMCK"
        rows.append(
            {
                "source_procurement_number": source.procurement_number,
                "analog_procurement_number": analog.analog_procurement_number,
                "similarity_score": analog.similarity_score,
                "similarity_reasons": "; ".join(analog.similarity_reasons),
                "mismatch_reasons": "; ".join(analog.mismatch_reasons),
                "result_completeness": analog.result_data_status,
                "strong_analog": analog.similarity_score >= config.historical.similarity.strong_similarity_score,
                "commodity_like": (analog.reduction_percent or 0) >= config.historical.dumping.high_reduction_threshold or (analog.participant_count or 0) >= config.historical.dumping.high_participant_threshold,
                "same_customer": bool(source.customer and source.customer.lower() == analog.customer.lower()),
                "same_procedure_type": bool(source.procedure_type and source.procedure_type.lower() == analog.procedure_type.lower()),
                "budget_relationship": relationship,
            }
        )
    return rows


def select_live_validation_analogs(source: RadarCard, analogs: list[HistoricalAnalog], config: RadarConfig) -> list[HistoricalAnalog]:
    selected = select_analogs(source, analogs, config)
    for analog in selected:
        analog.evidence.append({"selection_mode": analog.selection_mode or "NORMAL"})
    if selected:
        return selected
    scored = [score_similarity(source, analog) for analog in analogs]
    scored.sort(key=lambda item: item.similarity_score, reverse=True)
    relaxed_threshold = max(30, config.historical.similarity.minimum_score - 10)
    fallback = [item for item in scored if item.similarity_score >= relaxed_threshold]
    mode = "RELAXED_THRESHOLD"
    if not fallback:
        source_customer = (source.customer or "").strip().lower()
        fallback = [
            item
            for item in scored
            if item.similarity_score >= 30
            and source_customer
            and item.customer.strip().lower() == source_customer
        ]
        mode = "SAME_CUSTOMER_FALLBACK"
    fallback = fallback[: min(config.historical.search.maximum_selected_analogs, MAX_RESULT_COLLECTIONS)]
    for analog in fallback:
        analog.mismatch_reasons.append(mode)
        analog.evidence.append({"selection_mode": mode})
    return fallback


def build_metric_evidence(analogs: list[HistoricalAnalog], config: RadarConfig) -> dict[str, Any]:
    def numbers(rows: list[HistoricalAnalog]) -> list[str]:
        return [item.analog_procurement_number for item in rows]

    participant_rows = [item for item in analogs if item.participant_count is not None]
    reduction_rows = [item for item in analogs if item.reduction_percent is not None]
    strong_rows = [item for item in analogs if item.similarity_score >= config.historical.similarity.strong_similarity_score]
    no_application_rows = [item for item in analogs if item.no_applications]
    complete_rows = [item for item in analogs if item.result_data_status == "COMPLETE"]
    return {
        "participant_aggregates": {
            "contributing_procurement_numbers": numbers(participant_rows),
            "excluded_procurement_numbers": numbers([item for item in analogs if item.participant_count is None]),
            "exclusion_reasons": {"missing_participant_count": numbers([item for item in analogs if item.participant_count is None])},
            "sample_size": len(participant_rows),
            "formula": "median/quartiles over analog.participant_count when present",
        },
        "reduction_aggregates": {
            "contributing_procurement_numbers": numbers(reduction_rows),
            "excluded_procurement_numbers": numbers([item for item in analogs if item.reduction_percent is None]),
            "exclusion_reasons": {"missing_reduction_percent": numbers([item for item in analogs if item.reduction_percent is None])},
            "sample_size": len(reduction_rows),
            "formula": "median/quartiles over analog.reduction_percent when present; NMCK is never substituted for final price",
        },
        "strong_analog_count": {"contributing_procurement_numbers": numbers(strong_rows), "sample_size": len(strong_rows), "formula": "similarity_score >= strong_similarity_score"},
        "no_application_rate": {"contributing_procurement_numbers": numbers(no_application_rows), "sample_size": len(analogs), "formula": "no_application_count / selected_analog_count"},
        "complete_result_count": {"contributing_procurement_numbers": numbers(complete_rows), "sample_size": len(complete_rows), "formula": "result_data_status == COMPLETE"},
    }


def validate_source_values(number: str, source_card: RadarCard, source_result: dict[str, Any]) -> dict[str, Any]:
    expected = EXPECTED_REFERENCES.get(number, {})
    extracted = {
        "nmck": source_card.nmck,
        "contract_price": source_result.get("contract_price"),
        "reduction_percent": source_result.get("reduction_percent"),
        "participant_count": source_result.get("participant_count"),
    }
    diffs: dict[str, Any] = {}
    warnings: list[str] = []
    checks: list[bool] = []
    if not expected:
        status = "PARTIAL_PASS" if any(value is not None for value in extracted.values()) else "RESULT_UNREADABLE"
    else:
        for key in ["nmck", "contract_price"]:
            if key in expected:
                value = extracted.get(key)
                diffs[key] = None if value is None else round(abs(float(value) - float(expected[key])), 2)
                checks.append(value is not None and diffs[key] <= 1)
                if value is None:
                    warnings.append(f"{key} unavailable")
        if "reduction_percent" in expected:
            value = extracted.get("reduction_percent")
            diffs["reduction_percent"] = None if value is None else round(abs(float(value) - float(expected["reduction_percent"])), 3)
            checks.append(value is not None and diffs["reduction_percent"] <= 0.1)
            if value is None:
                warnings.append("reduction_percent unavailable")
        if "participant_count" in expected:
            value = extracted.get("participant_count")
            diffs["participant_count"] = None if value is None else abs(int(value) - int(expected["participant_count"]))
            checks.append(value is not None and diffs["participant_count"] == 0)
        if "participant_count_min" in expected:
            value = extracted.get("participant_count")
            diffs["participant_count_min"] = None if value is None else int(value) - int(expected["participant_count_min"])
            checks.append(value is not None and int(value) >= int(expected["participant_count_min"]))
        if checks and all(checks):
            status = "PASS"
        elif any(checks):
            status = "PARTIAL_PASS"
        else:
            status = "FAIL" if any(value is not None for value in extracted.values()) else "RESULT_UNREADABLE"
    return {
        "procurement_number": number,
        "expected_reference_values": expected,
        "extracted_values": extracted,
        "absolute_differences": diffs,
        "validation_status": status,
        "evidence": source_result.get("evidence", []),
        "warnings": warnings,
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    if not headers:
        headers = ["empty"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def render_live_markdown(result: LiveHistoricalValidationResult) -> str:
    metrics = result.bundle.competition_metrics
    risk = result.bundle.dumping_risk_assessment
    adjusted = result.bundle.history_adjusted_assessment
    lines = [
        "# R3A Live Historical Validation",
        "",
        "## 1. Source procurement",
        f"- Procurement: `{result.source_card.procurement_number}`",
        f"- URL: {result.source_card.source_url}",
        f"- Validation status: {result.source_validation.get('validation_status')}",
        "",
        "## 2. Query strategy",
    ]
    for row in result.historical_query_plan:
        lines.append(f"- `{row['query_text']}` ({row['query_type']}, weight={row['query_weight']})")
    lines.extend(
        [
            "",
            "## 3. Completed-procedure search diagnostics",
            f"- Raw candidates: {result.diagnostics.get('raw_cards', 0)}",
            f"- Unique candidates: {result.diagnostics.get('unique_cards', 0)}",
            "",
            "## 4. Selected analogs",
        ]
    )
    for analog in result.bundle.historical_analogs:
        lines.append(f"- `{analog.analog_procurement_number}` score={analog.similarity_score}, status={analog.result_data_status}")
    lines.extend(
        [
            "",
            "## 5. Source result validation",
            json.dumps(result.source_validation, ensure_ascii=False, indent=2),
            "",
            "## 6. Competition metrics",
            json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2),
            "",
            "## 7. Dumping-risk assessment",
            json.dumps(risk.to_dict(), ensure_ascii=False, indent=2),
            "",
            "## 8. Retrospective history-adjusted decision",
            f"- decision_context: `{DECISION_CONTEXT}`",
            f"- retrospective_history_adjusted_decision: `{adjusted.history_adjusted_decision.value if adjusted else 'UNKNOWN'}`",
            "",
            "## 9. Data-quality limitations",
        ]
    )
    for warning in result.diagnostics.get("warnings", []) + result.source_validation.get("warnings", []):
        lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## 10. Resource usage",
            f"- Bytes downloaded: {result.diagnostics.get('bytes_downloaded', 0)}",
            f"- Cache hits: {result.diagnostics.get('cache_hits', 0)}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_live_validation_outputs(result: LiveHistoricalValidationResult, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "historical_query_plan": output_dir / "historical_query_plan.json",
        "source_validation": output_dir / "source_validation.json",
        "historical_candidates_raw": output_dir / "historical_candidates_raw.json",
        "historical_candidates_unique": output_dir / "historical_candidates_unique.json",
        "historical_candidates_scored": output_dir / "historical_candidates_scored.json",
        "selected_analogs": output_dir / "selected_analogs.json",
        "analog_review": output_dir / "analog_review.csv",
        "analog_result_resolution_json": output_dir / "analog_result_resolution.json",
        "analog_result_resolution_csv": output_dir / "analog_result_resolution.csv",
        "protocol_extraction_diagnostics_json": output_dir / "protocol_extraction_diagnostics.json",
        "assembled_historical_results_json": output_dir / "assembled_historical_results.json",
        "competition_metric_samples_json": output_dir / "competition_metric_samples.json",
        "competition_metric_evidence": output_dir / "competition_metric_evidence.json",
        "historical_live_diagnostics_json": output_dir / "historical_live_diagnostics.json",
        "historical_live_diagnostics_csv": output_dir / "historical_live_diagnostics.csv",
        "historical_live_validation_markdown": output_dir / "historical_live_validation.md",
    }
    write_json(paths["historical_query_plan"], result.historical_query_plan)
    write_json(paths["source_validation"], result.source_validation)
    write_json(paths["historical_candidates_raw"], result.raw_candidates)
    write_json(paths["historical_candidates_unique"], result.unique_candidates)
    write_json(paths["historical_candidates_scored"], result.scored_candidates)
    write_json(paths["selected_analogs"], [item.to_dict() for item in result.bundle.historical_analogs])
    write_csv(paths["analog_review"], result.analog_review)
    write_json(paths["analog_result_resolution_json"], result.analog_result_resolution)
    write_csv(paths["analog_result_resolution_csv"], result.analog_result_resolution)
    write_json(paths["protocol_extraction_diagnostics_json"], result.protocol_extraction_diagnostics)
    write_json(paths["assembled_historical_results_json"], result.assembled_historical_results)
    write_json(paths["competition_metric_samples_json"], result.competition_metric_samples)
    write_json(paths["competition_metric_evidence"], result.competition_metric_evidence)
    write_json(paths["historical_live_diagnostics_json"], result.diagnostics)
    write_csv(paths["historical_live_diagnostics_csv"], [result.diagnostics])
    paths["historical_live_validation_markdown"].write_text(render_live_markdown(result), encoding="utf-8")
    result.markdown_path = str(paths["historical_live_validation_markdown"])
    result.output_paths = {key: str(value) for key, value in paths.items()}
    return result.output_paths


def update_live_validation_audit_doc(path: Path, result: LiveHistoricalValidationResult) -> None:
    rows = search_filter_audit(result.historical_query_plan, RadarConfig())
    content = [
        "# RADAR R3A.1 Live Validation",
        "",
        "## Completed Filter Audit",
        "",
        f"- Source procurement: `{result.source_card.procurement_number}`",
        f"- Canonical URL: {result.source_card.source_url}",
        f"- Decision context: `{DECISION_CONTEXT}`",
        "",
        "## Request Parameters",
    ]
    for row in rows:
        content.append(f"- query=`{row['query_text']}`, params={json.dumps(row['request_params'], ensure_ascii=False)}, fingerprint=`{row['filter_fingerprint']}`")
    content.extend(
        [
            "",
            "## Pagination Behavior",
            "- Pagination changes only `pageNumber`; completed status filter `pc=on` is preserved.",
            "",
            "## Observed Status Distribution",
            json.dumps(result.diagnostics.get("observed_status_distribution", {}), ensure_ascii=False, indent=2),
            "",
            "## EIS-Specific Limitations",
            "- EIS pages may be unavailable, rate-limited, or rendered with changed layouts.",
            "- Cancelled, failed and completed procedures remain distinguishable through result status fields when extracted.",
        ]
    )
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def run_live_historical_validation(
    source_card: RadarCard,
    preliminary: RadarAssessment,
    config: RadarConfig,
    *,
    output_dir: str | Path,
    dry_run: bool = False,
    resume: bool = False,
    collector: Callable[[Any, RadarConfig, int | None, int | None], list[RadarCard]] | None = None,
    fetch: Callable[[str], str] | None = None,
    source_resolution: SourceResolutionResult | None = None,
) -> LiveHistoricalValidationResult:
    started = time.monotonic()
    original_preliminary_score = preliminary.total_score
    original_preliminary_decision = preliminary.radar_decision
    source_card = mark_validation_source(source_card)
    exclude_validation_source_from_active_assessment(preliminary)
    plan = build_query_plan(source_card, config)
    filter_rows = search_filter_audit(plan, config)
    raw_analogs, discovery_diag = discover_historical_candidates(source_card, plan, config, dry_run=dry_run, collector=collector)
    selected = select_live_validation_analogs(source_card, raw_analogs, config)
    cache_dir = Path(output_dir) / ".history_cache"
    byte_budget = {"total": 0}
    result_rows = []
    enriched: list[HistoricalAnalog] = []
    analog_result_resolution: list[dict[str, Any]] = []
    protocol_extraction_diagnostics: list[dict[str, Any]] = []
    assembled_historical_results: list[dict[str, Any]] = []
    for analog in selected[: min(config.historical.search.maximum_selected_analogs, MAX_RESULT_COLLECTIONS)]:
        enriched_analog, row = collect_result_for_analog(analog, fetch=fetch, cache_dir=cache_dir, resume=resume, byte_budget=byte_budget)
        enriched.append(enriched_analog)
        result_rows.append(row)
        if row.get("resolution_diagnostic"):
            analog_result_resolution.append(row["resolution_diagnostic"])
        if row.get("assembled_result"):
            assembled_historical_results.append(row["assembled_result"])
        protocol_extraction_diagnostics.extend(row.get("protocol_extraction_diagnostics", []))
    if dry_run:
        enriched = selected
    metrics = calculate_competition_metrics(enriched, config)
    risk = assess_dumping_risk(metrics, config)
    adjusted = history_adjustment(preliminary, risk)
    if metrics.confidence == "INSUFFICIENT":
        adjusted.historical_adjustment = 0
        adjusted.history_adjusted_score = original_preliminary_score
        adjusted.history_adjusted_decision = original_preliminary_decision
        adjusted.historical_adjustment_reasons = ["NOT_APPLIED_INSUFFICIENT_HISTORY"]
    customer = build_customer_history(source_card.customer, enriched, metrics, config)
    suppliers = build_supplier_history(enriched, config)
    repeated = detect_repeated_procurements(source_card, enriched)
    source_result = {"evidence": []}
    if not dry_run:
        try:
            if fetch is None:
                import requests

                def fetch(target: str) -> str:
                    response = requests.get(target, timeout=45)
                    response.raise_for_status()
                    return response.text

            source_html = fetch(source_card.source_url)
            source_result = extract_result_values(source_html, source_card.nmck)
            source_result["evidence"] = [{"type": "source_result_or_common_page", "source_url": source_card.source_url}]
        except Exception as error:
            source_result = {"evidence": [], "error": str(error)}
    source_validation = validate_source_values(source_card.procurement_number, source_card, source_result)
    analog_review = build_analog_review(source_card, enriched, config)
    metric_evidence = build_metric_evidence(enriched, config)
    bundle = HistoricalAssessmentBundle(
        procurement_number=source_card.procurement_number,
        historical_search=generate_historical_queries(source_card, config, profile="r3a-live-validation"),
        historical_analogs=enriched,
        competition_metrics=metrics,
        customer_history=customer,
        supplier_history=suppliers,
        dumping_risk_assessment=risk,
        history_adjusted_assessment=adjusted,
        repeated_procurements=repeated,
        diagnostics={
            "decision_context": DECISION_CONTEXT,
            "retrospective_history_adjusted_decision": None if metrics.confidence == "INSUFFICIENT" else adjusted.history_adjusted_decision.value,
            "history_adjustment_status": "NOT_APPLIED_INSUFFICIENT_HISTORY" if metrics.confidence == "INSUFFICIENT" else "APPLIED",
        },
    )
    source_status = source_resolution.status if source_resolution else "RESOLVED_LIVE"
    error_codes = discovery_diag["errors"] + [error for row in result_rows for error in row.get("errors", [])]
    if source_resolution:
        error_codes.extend([attempt.error_code for attempt in source_resolution.attempts if attempt.error_code])
    usable_statuses = {"COMPLETE", "PARTIAL_PRICE", "PARTIAL_PARTICIPANTS", "PARTIAL_OTHER"}
    usable_results = sum(1 for item in enriched if item.result_data_status in usable_statuses)
    run_quality_status = classify_run_quality(
        source_status=source_status,
        queries_attempted=discovery_diag["queries_attempted"],
        raw_candidates=discovery_diag["raw_cards"],
        selected_analogs=len(enriched),
        usable_results=usable_results,
        error_codes=error_codes,
    )
    diagnostics = {
        "decision_context": DECISION_CONTEXT,
        "source_resolution": source_card.to_dict(),
        "source_resolution_result": source_resolution.to_dict() if source_resolution else None,
        "source_resolution_attempts": [attempt.to_dict() for attempt in source_resolution.attempts] if source_resolution else [],
        "source_resolution_strategy_used": source_resolution.strategy_used if source_resolution else "",
        "source_cache_age": "; ".join(source_resolution.validation_warnings) if source_resolution else "",
        "source_http_status_distribution": {
            str(status): sum(1 for attempt in source_resolution.attempts if attempt.http_status == status)
            for status in sorted({attempt.http_status for attempt in source_resolution.attempts if attempt.http_status is not None})
        } if source_resolution else {},
        "queries_planned": len(plan),
        "queries_attempted": discovery_diag["queries_attempted"],
        "historical_query_success_count": sum(1 for row in discovery_diag.get("search_rows", []) if row.get("cards_found", 0) > 0),
        "historical_query_failure_count": len(discovery_diag.get("errors", [])),
        "pages_requested": discovery_diag["pages_requested"],
        "pages_succeeded": discovery_diag["pages_requested"] if not discovery_diag["errors"] else 0,
        "raw_cards": discovery_diag["raw_cards"],
        "unique_cards": discovery_diag["unique_cards"],
        "candidate_count_raw": discovery_diag["raw_cards"],
        "candidate_count_unique": discovery_diag["unique_cards"],
        "candidate_count_scored": len(raw_analogs),
        "selected_analog_count": len(enriched),
        "candidates_scored": len(raw_analogs),
        "candidates_excluded": max(0, len(raw_analogs) - len(selected)),
        "analogs_selected": len(enriched),
        "result_pages_attempted": sum(1 for row in result_rows if row.get("attempted")),
        "protocols_downloaded": len([item for item in protocol_extraction_diagnostics if item.get("document_url")]),
        "result_resolution_attempts": sum(1 for row in result_rows if row.get("attempted") or row.get("cache_hit")),
        "result_resolution_successes": sum(1 for item in enriched if item.result_data_status == "COMPLETE"),
        "result_resolution_partial": sum(1 for item in enriched if item.result_data_status in {"PARTIAL_PRICE", "PARTIAL_PARTICIPANTS", "PARTIAL_OTHER"}),
        "result_resolution_temporary_failures": sum(1 for row in result_rows if row.get("errors")),
        "complete_results": sum(1 for item in enriched if item.result_data_status == "COMPLETE"),
        "partial_results": sum(1 for item in enriched if item.result_data_status in {"PARTIAL_PRICE", "PARTIAL_PARTICIPANTS", "PARTIAL_OTHER"}),
        "failed_results": sum(1 for row in result_rows if row.get("errors")),
        "cache_hits": sum(1 for row in result_rows if row.get("cache_hit")),
        "bytes_downloaded": byte_budget["total"],
        "total_duration": round(time.monotonic() - started, 3),
        "error_codes": error_codes,
        "completed_search_filters": filter_rows,
        "competition_metric_sample_size": max(metrics.participant_sample_size, metrics.reduction_sample_size, metrics.winner_sample_size, metrics.complete_result_sample_size),
        "participant_sample_size": metrics.participant_sample_size,
        "reduction_sample_size": metrics.reduction_sample_size,
        "winner_sample_size": metrics.winner_sample_size,
        "complete_result_sample_size": metrics.complete_result_sample_size,
        "participant_metric_confidence": metrics.participant_metric_confidence,
        "reduction_metric_confidence": metrics.reduction_metric_confidence,
        "winner_metric_confidence": metrics.winner_metric_confidence,
        "analog_result_resolution": analog_result_resolution,
        "protocol_extraction_diagnostics": protocol_extraction_diagnostics,
        "assembled_historical_results": assembled_historical_results,
        "competition_metric_samples": {
            "participant_sample_size": metrics.participant_sample_size,
            "participant_contributors": metrics.participant_contributors,
            "reduction_sample_size": metrics.reduction_sample_size,
            "reduction_contributors": metrics.reduction_contributors,
            "winner_sample_size": metrics.winner_sample_size,
            "winner_contributors": metrics.winner_contributors,
            "complete_result_sample_size": metrics.complete_result_sample_size,
            "complete_result_contributors": metrics.complete_result_contributors,
        },
        "run_quality_status": run_quality_status,
        "latest_published": False,
        "latest_publish_reason": "not evaluated yet",
        "warnings": [],
        "download_limits": {"max_total_bytes": MAX_TOTAL_BYTES, "max_single_file_bytes": MAX_SINGLE_FILE_BYTES, "full_technical_documents": False},
    }
    result = LiveHistoricalValidationResult(
        source_card,
        bundle,
        plan,
        source_validation,
        analog_review,
        metric_evidence,
        diagnostics,
        raw_candidates=discovery_diag.get("raw_candidate_cards", []),
        unique_candidates=discovery_diag.get("unique_candidate_cards", []),
        scored_candidates=[item.to_dict() for item in raw_analogs],
        analog_result_resolution=analog_result_resolution,
        protocol_extraction_diagnostics=protocol_extraction_diagnostics,
        assembled_historical_results=assembled_historical_results,
        competition_metric_samples=diagnostics["competition_metric_samples"],
    )
    write_live_validation_outputs(result, Path(output_dir))
    update_live_validation_audit_doc(Path("RADAR_R3A1_LIVE_VALIDATION.md"), result)
    return result


def cache_fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
