from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from radar.config import RadarConfig
from radar import http
from radar.models import RadarCard
from radar.open_verification import build_status_audit, is_provisionally_open, unavailable_verification, verify_open_from_detail_text
from radar.prefilter import days_to_deadline, normalize_status, parse_datetime
from radar.search_request import SearchRequest, build_eis_search_request, redact_url, request_from_url, serialize_eis_search_request
from radar.search_profiles import SearchProfile


def _redact_detail_source_url(url: str) -> str:
    redacted = redact_url(url)
    parsed = urlparse(redacted)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    if not params:
        return redacted
    safe_params = []
    for key, value in params:
        if key.lower() in {"regnumber", "registrynumber", "noticenumber", "purchasenoticenumber"}:
            safe_params.append((key, "<redacted>"))
        else:
            safe_params.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(safe_params, doseq=True)))


def normalize_law(value: str) -> str:
    lowered = (value or "").lower()
    if "44" in lowered:
        return "44-FZ"
    if "223" in lowered:
        return "223-FZ"
    return value or ""


def normalize_card(raw: dict[str, Any], profile: str = "", query: str = "") -> RadarCard:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    search_queries = raw.get("search_queries") or raw.get("queries") or []
    if isinstance(search_queries, str):
        search_queries = [search_queries]
    if query and query not in search_queries:
        search_queries.append(query)

    search_profiles = raw.get("search_profiles") or []
    if isinstance(search_profiles, str):
        search_profiles = [search_profiles]
    if profile and profile not in search_profiles:
        search_profiles.append(profile)

    card = RadarCard(
        procurement_number=str(raw.get("procurement_number") or raw.get("number") or "").strip(),
        title=raw.get("title") or raw.get("object_name") or "",
        customer=raw.get("customer") or "",
        law=normalize_law(raw.get("law") or ""),
        procedure_type=raw.get("procedure_type") or raw.get("procedure") or "",
        status_raw=raw.get("status_raw") or raw.get("status") or "",
        status_normalized=raw.get("status_normalized") or "",
        nmck=raw.get("nmck") if raw.get("nmck") is not None else raw.get("initial_price_value"),
        currency=raw.get("currency") or "RUB",
        published_at=raw.get("published_at") or raw.get("published_date") or "",
        updated_at=raw.get("updated_at") or raw.get("updated_date") or "",
        application_deadline=raw.get("application_deadline") or raw.get("deadline_date") or "",
        auction_date=raw.get("auction_date") or "",
        source_url=raw.get("source_url") or raw.get("card_url") or "",
        region=raw.get("region") or "",
        search_queries=search_queries,
        search_profiles=search_profiles,
        raw_text=raw.get("raw_text") or "",
        discovered_at=raw.get("discovered_at") or raw.get("collected_at") or now,
        last_seen_at=raw.get("last_seen_at") or now,
    )
    card.status_normalized = normalize_status(card.status_raw or card.status_normalized)
    card.source_fingerprint = raw.get("source_fingerprint") or card.compute_fingerprint()
    return card


def deduplicate_cards(cards: list[RadarCard]) -> list[RadarCard]:
    unique: dict[str, RadarCard] = {}
    for card in cards:
        key = card.procurement_number or card.compute_fingerprint()
        if key in unique:
            existing = unique[key]
            existing.search_queries = sorted(set(existing.search_queries + card.search_queries))
            existing.search_profiles = sorted(set(existing.search_profiles + card.search_profiles))
            existing.last_seen_at = max(existing.last_seen_at, card.last_seen_at)
            if not existing.raw_text and card.raw_text:
                existing.raw_text = card.raw_text
            existing.source_fingerprint = existing.compute_fingerprint()
        else:
            unique[key] = card
    return list(unique.values())


def load_offline_cards(path: str | Path) -> list[RadarCard]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("cards", data) if isinstance(data, dict) else data
    return deduplicate_cards([normalize_card(item) for item in items])


def _verify_detail_content(
    card: RadarCard,
    content: str,
    as_of: datetime,
    *,
    source_url: str,
    http_status: int | None,
    recovery_status: str,
    strategy: str,
) -> dict[str, Any]:
    from radar.source_resolution import content_has_number, fingerprint_content, page_type_for_url

    verification = verify_open_from_detail_text(card, content, as_of)
    row = verification.to_dict()
    row["detail_source_url"] = _redact_detail_source_url(source_url)
    row["detail_direct_http_status"] = http_status
    row["detail_source_recovery_status"] = recovery_status
    row["detail_source_strategy"] = strategy
    if row.get("open_verification_status") != "DETAIL_UNAVAILABLE" and content_has_number(content, card.procurement_number):
        row["_detail_last_known_good_url"] = source_url
        row["detail_last_known_good_url"] = _redact_detail_source_url(source_url)
        row["detail_last_known_good_page_type"] = page_type_for_url(source_url)
        row["detail_last_known_good_fingerprint"] = fingerprint_content(content)
    return row


def _should_try_source_recovery(strategy: str, status_code: int | None = None) -> bool:
    if strategy != "DIRECT":
        return False
    return status_code is None or status_code in {404, 429, 500, 502, 503, 504}


def _recovery_status_for_strategy(strategy: str) -> str:
    if strategy == "LAST_KNOWN_GOOD":
        return "REUSED"
    if strategy == "PROVEN_CANONICAL_RETRY":
        return "RETRIED"
    return "NOT_ATTEMPTED"


def _fetch_detail_url(card: RadarCard, as_of: datetime, url: str, strategy: str) -> tuple[dict[str, Any], bool]:
    import requests

    try:
        response = http.get(url, timeout=30)
    except requests.RequestException:
        unavailable = unavailable_verification(card, "detail request failed", as_of, "REQUEST_ERROR").to_dict()
        unavailable["detail_source_strategy"] = strategy
        unavailable["detail_source_recovery_status"] = "FAILED" if strategy == "LAST_KNOWN_GOOD" else "NOT_ATTEMPTED"
        unavailable["detail_source_url"] = _redact_detail_source_url(url)
        return unavailable, _should_try_source_recovery(strategy)
    if response.status_code >= 400:
        code = "SOURCE_URL_NOT_FOUND" if response.status_code == 404 and strategy == "LAST_KNOWN_GOOD" else "HTTP_ERROR"
        unavailable = unavailable_verification(card, f"HTTP {response.status_code}", as_of, code).to_dict()
        unavailable["detail_source_url"] = _redact_detail_source_url(getattr(response, "url", "") or url)
        unavailable["detail_direct_http_status"] = response.status_code
        unavailable["detail_source_recovery_status"] = "FAILED" if strategy == "LAST_KNOWN_GOOD" else "NOT_ATTEMPTED"
        unavailable["detail_source_strategy"] = strategy
        return unavailable, _should_try_source_recovery(strategy, response.status_code)
    row = _verify_detail_content(
        card,
        response.text,
        as_of,
        source_url=getattr(response, "url", "") or url,
        http_status=response.status_code,
        recovery_status=_recovery_status_for_strategy(strategy),
        strategy=strategy,
    )
    return row, False


def _persist_last_known_good(state, row: dict[str, Any], as_of: datetime) -> None:
    if state is None or not row.get("_detail_last_known_good_url"):
        return
    state.save_successful_source_url(
        procurement_number=str(row.get("procurement_number") or ""),
        source_url=str(row.get("_detail_last_known_good_url") or ""),
        page_type=str(row.get("detail_last_known_good_page_type") or ""),
        fetched_at=datetime.now(as_of.tzinfo).isoformat(timespec="seconds"),
        content_fingerprint=str(row.get("detail_last_known_good_fingerprint") or ""),
        latest_known_validation_status=str(row.get("open_verification_status") or ""),
    )


def _public_verification_row(row: dict[str, Any]) -> dict[str, Any]:
    public_row = dict(row)
    public_row.pop("_detail_last_known_good_url", None)
    return public_row


def verify_cards_from_detail(cards: list[RadarCard], as_of: datetime, limit: int, state=None, remembered_source_max_age_hours: int = 336) -> list[dict[str, Any]]:
    from radar.source_resolution import (
        SourceResolutionPolicy,
        content_has_number,
        resolve_procurement_source_content,
    )

    results: list[dict[str, Any]] = []
    recovery_policy = SourceResolutionPolicy(
        max_attempts_per_strategy=1,
        enable_cached_source_fallback=False,
        confirmation_attempts_for_not_found=1,
    )
    for card in cards[:limit]:
        if not card.source_url:
            results.append(unavailable_verification(card, "missing source URL", as_of, "MISSING_SOURCE_URL").to_dict())
            continue
        row, should_recover = _fetch_detail_url(card, as_of, card.source_url, "DIRECT")
        if row.get("_detail_last_known_good_url"):
            row["detail_last_known_good_url"] = _redact_detail_source_url(str(row["_detail_last_known_good_url"]))
        remembered_url = state.get_last_successful_source_url(card.procurement_number, remembered_source_max_age_hours) if state else ""
        if not should_recover:
            _persist_last_known_good(state, row, as_of)
            results.append(_public_verification_row(row))
            continue
        direct_failure_code = str(row.get("detail_failure_code") or "")
        direct_http_status = row.get("detail_direct_http_status")
        direct_transient_failure = direct_failure_code == "REQUEST_ERROR" or (
            direct_failure_code == "HTTP_ERROR" and direct_http_status in {429, 500, 502, 503, 504}
        )
        if remembered_url == card.source_url:
            retry_row, _retry_should_recover = _fetch_detail_url(card, as_of, card.source_url, "PROVEN_CANONICAL_RETRY")
            retry_row["detail_proven_canonical_retry_count"] = 1
            if retry_row.get("_detail_last_known_good_url"):
                retry_row["detail_last_known_good_url"] = _redact_detail_source_url(str(retry_row["_detail_last_known_good_url"]))
            if retry_row.get("open_verification_status") != "DETAIL_UNAVAILABLE":
                _persist_last_known_good(state, retry_row, as_of)
                results.append(_public_verification_row(retry_row))
                continue
        elif remembered_url:
            remembered_row, remembered_should_recover = _fetch_detail_url(card, as_of, remembered_url, "LAST_KNOWN_GOOD")
            if remembered_row.get("_detail_last_known_good_url"):
                remembered_row["detail_last_known_good_url"] = _redact_detail_source_url(str(remembered_row["_detail_last_known_good_url"]))
            if remembered_row.get("open_verification_status") != "DETAIL_UNAVAILABLE":
                _persist_last_known_good(state, remembered_row, as_of)
                results.append(_public_verification_row(remembered_row))
                continue
            if remembered_should_recover:
                row = remembered_row
        recovery = resolve_procurement_source_content(
            card.procurement_number,
            source_url=card.source_url,
            policy=recovery_policy,
        )
        if (
            recovery.result.status in {"RESOLVED_LIVE", "RESOLVED_SEARCH_RECOVERY", "RESOLVED_ALTERNATE_SECTION"}
            and recovery.content
            and content_has_number(recovery.content, card.procurement_number)
        ):
            recovered_url = recovery.result.canonical_url
            recovered_row = _verify_detail_content(
                card,
                recovery.content,
                as_of,
                source_url=recovered_url,
                http_status=None,
                recovery_status="RECOVERED",
                strategy=recovery.result.strategy_used or "SEARCH_RECOVERY",
            )
            recovered_row["detail_recovered_url"] = _redact_detail_source_url(recovered_url)
            recovered_row["detail_source_resolution_status"] = recovery.result.status
            recovered_row["detail_source_resolution_attempts"] = len(recovery.result.attempts)
            if recovered_row.get("_detail_last_known_good_url"):
                recovered_row["detail_last_known_good_url"] = _redact_detail_source_url(str(recovered_row["_detail_last_known_good_url"]))
            _persist_last_known_good(state, recovered_row, as_of)
            results.append(_public_verification_row(recovered_row))
            continue
        if recovery.result.status == "NOT_FOUND_CONFIRMED":
            failure_code = "SOURCE_URL_NOT_FOUND"
            failure_reason = "source recovery failed"
        elif direct_transient_failure:
            failure_code = direct_failure_code
            direct_reasons = row.get("open_verification_reasons") or []
            failure_reason = str(direct_reasons[0]) if direct_reasons else "source recovery failed"
        else:
            failure_code = "SOURCE_RECOVERY_FAILED"
            failure_reason = "source recovery failed"
        unavailable = unavailable_verification(card, failure_reason, as_of, failure_code).to_dict()
        unavailable["detail_source_url"] = _redact_detail_source_url(card.source_url)
        unavailable["detail_direct_http_status"] = row.get("detail_direct_http_status")
        unavailable["detail_source_recovery_status"] = "FAILED"
        unavailable["detail_source_strategy"] = "FAILED"
        unavailable["detail_source_resolution_status"] = recovery.result.status
        unavailable["detail_source_resolution_attempts"] = len(recovery.result.attempts)
        results.append(unavailable)
    return results


def _detail_unavailable_diagnostics(verifications: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, list[str]]]:
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for row in verifications:
        if row.get("open_verification_status") != "DETAIL_UNAVAILABLE":
            continue
        code = str(row.get("detail_failure_code") or "UNKNOWN")
        counts[code] += 1
        procurement_number = str(row.get("procurement_number") or "")
        if procurement_number and len(examples.setdefault(code, [])) < 3:
            examples[code].append(procurement_number)
    return dict(sorted(counts.items())), {key: examples[key] for key in sorted(examples)}


async def _collect_with_existing_collector(
    request: SearchRequest,
    config: RadarConfig,
    limit: int | None,
    max_pages: int | None,
) -> list[RadarCard]:
    import collect_results

    url = serialize_eis_search_request(request, collect_results.DEFAULT_URL)
    output_name = f"radar_{request.source_profile}_{abs(hash(request.fingerprint()))}_{request.page_number}"
    args = argparse.Namespace(
        url=url,
        output=output_name,
        start_page=1,
        max_pages=max_pages or config.radar.max_pages_per_query,
        records_per_page=50,
        delay_min=config.radar.request_delay_seconds,
        delay_max=config.radar.request_delay_seconds + 0.5,
        timeout=60,
        retries=2,
        headless=True,
        force=True,
    )
    await collect_results.collect(args)
    checkpoint = collect_results.RAW_DIR / f"{output_name}.json"
    raw_items = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else []
    if limit:
        raw_items = raw_items[:limit]
    return [normalize_card(item, profile=request.source_profile, query=request.query_text) for item in raw_items]


def discover_cards(
    config: RadarConfig,
    profiles: list[SearchProfile],
    offline_input: str | Path | None = None,
    limit: int | None = None,
    max_pages: int | None = None,
    as_of: datetime | None = None,
    discovery_mode: str | None = None,
    explicit_queries: list[str] | None = None,
    state=None,
) -> tuple[list[RadarCard], dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "queries_attempted": 0,
        "queries_successful": 0,
        "errors": [],
        "mode": "offline" if offline_input else "online",
        "discovery_mode": "OFFLINE" if offline_input else (discovery_mode or config.discovery.mode),
        "search_diagnostics": [],
        "status_audit": [],
        "open_verifications": [],
        "detail_unavailable_by_code": {},
        "detail_unavailable_examples_by_code": {},
    }
    if offline_input:
        cards = load_offline_cards(offline_input)
        if limit:
            cards = cards[:limit]
        diagnostics.update(
            {
                "queries_attempted": 0,
                "queries_successful": 0,
                "raw_cards": len(cards),
                "unique_cards": len(cards),
            }
        )
        return cards, diagnostics

    collected: list[RadarCard] = []
    total_pages = 0
    queries_attempted = 0
    now = as_of or datetime.now().astimezone()
    for profile in profiles:
        queries = explicit_queries or profile.queries
        for query in queries:
            if queries_attempted >= config.discovery.maximum_queries_per_run:
                diagnostics["errors"].append("QUERY_BUDGET_REACHED")
                break
            queries_attempted += 1
            diagnostics["queries_attempted"] += 1
            try:
                remaining = None if limit is None else max(0, limit - len(collected))
                if remaining == 0:
                    break
                pages_for_query = min(max_pages or config.radar.max_pages_per_query, config.discovery.maximum_total_pages - total_pages)
                if pages_for_query <= 0:
                    diagnostics["errors"].append("PAGE_BUDGET_REACHED")
                    break
                request = build_eis_search_request(
                    query,
                    config,
                    source_profile=profile.name,
                    page_number=1,
                    as_of=now,
                    discovery_mode=discovery_mode,
                )
                requested_url = serialize_eis_search_request(request, __import__("collect_results").DEFAULT_URL)
                cards = asyncio.run(_collect_with_existing_collector(request, config, remaining, pages_for_query))
                returned_request = request_from_url(requested_url, source_profile=profile.name)
                filter_lost = returned_request.fingerprint() != request.fingerprint()
                provisional = [card for card in cards if is_provisionally_open(card, now)[0]]
                status_distribution: dict[str, int] = {}
                for card in cards:
                    status_distribution[card.status_normalized] = status_distribution.get(card.status_normalized, 0) + 1
                future_deadline_count = 0
                for card in cards:
                    deadline = parse_datetime(card.application_deadline, config.radar.timezone)
                    remaining = days_to_deadline(deadline, now)
                    if remaining is not None and remaining > 0:
                        future_deadline_count += 1
                diagnostics["search_diagnostics"].append(
                    {
                        "query": query,
                        "profile": profile.name,
                        "law": request.law,
                        "discovery_mode": request.discovery_mode,
                        "requested_statuses": request.included_statuses,
                        "requested_date_range": {
                            "published_from": request.published_from,
                            "published_to": request.published_to,
                            "application_deadline_from": request.application_deadline_from,
                        },
                        "page": 1,
                        "requested_url_redacted": redact_url(requested_url),
                        "resolved_url_redacted": redact_url(requested_url),
                        "filter_fingerprint": request.fingerprint(),
                        "response_status": "ok",
                        "cards_found": len(cards),
                        "status_distribution": status_distribution,
                        "future_deadline_count": future_deadline_count,
                        "provisional_open_count": len(provisional),
                        "parse_warnings": ["FILTER_LOST_DURING_PAGINATION"] if filter_lost else [],
                        "failure_code": "FILTER_LOST_DURING_PAGINATION" if filter_lost else "",
                        "duration_seconds": 0,
                    }
                )
                if filter_lost:
                    break
                collected.extend(cards)
                total_pages += pages_for_query
                diagnostics["queries_successful"] += 1
            except Exception as error:
                diagnostics["errors"].append(f"{profile.name}/{query}: {error}")
        if (limit and len(collected) >= limit) or len(deduplicate_cards(collected)) >= config.discovery.maximum_unique_cards:
            break
    unique = deduplicate_cards(collected)
    if (discovery_mode or config.discovery.mode) == "ACTIVE_ONLY":
        unique = [card for card in unique if is_provisionally_open(card, now)[0]]
    provisional_count = len(unique)
    verifications: list[dict[str, Any]] = []
    rejected_by_detail_verification = 0
    verification_skipped_due_to_limit = 0
    if config.discovery.verify_open_status_from_detail_page and unique:
        attempted_cards = unique[: config.discovery.verify_top_candidates_limit]
        verification_skipped_due_to_limit = max(0, len(unique) - len(attempted_cards))
        verifications = verify_cards_from_detail(unique, now, config.discovery.verify_top_candidates_limit, state=state)
        verification_by_number = {
            row["procurement_number"]: row
            for row in verifications
            if row.get("procurement_number")
        }
        kept_cards: list[RadarCard] = []
        for card in unique:
            verification = verification_by_number.get(card.procurement_number)
            if verification is None:
                kept_cards.append(card)
                continue
            status = verification.get("open_verification_status")
            if status in {"VERIFIED_CLOSED", "VERIFIED_CANCELLED", "STATUS_CONFLICT", "DEADLINE_CONFLICT"}:
                rejected_by_detail_verification += 1
                continue
            kept_cards.append(card)
        unique = kept_cards
    diagnostics["open_verifications"] = verifications
    diagnostics["detail_verifications_attempted"] = len(verifications)
    diagnostics["detail_verification_skipped_due_to_limit"] = verification_skipped_due_to_limit
    diagnostics["verified_open"] = sum(1 for row in verifications if row.get("open_verification_status") == "VERIFIED_OPEN")
    diagnostics["verified_closed"] = sum(1 for row in verifications if row.get("open_verification_status") == "VERIFIED_CLOSED")
    diagnostics["verified_cancelled"] = sum(1 for row in verifications if row.get("open_verification_status") == "VERIFIED_CANCELLED")
    diagnostics["status_conflicts"] = sum(1 for row in verifications if row.get("open_verification_status") == "STATUS_CONFLICT")
    diagnostics["deadline_conflicts"] = sum(1 for row in verifications if row.get("open_verification_status") == "DEADLINE_CONFLICT")
    diagnostics["detail_unavailable"] = sum(1 for row in verifications if row.get("open_verification_status") == "DETAIL_UNAVAILABLE")
    detail_unavailable_by_code, detail_unavailable_examples_by_code = _detail_unavailable_diagnostics(verifications)
    diagnostics["detail_unavailable_by_code"] = detail_unavailable_by_code
    diagnostics["detail_unavailable_examples_by_code"] = detail_unavailable_examples_by_code
    diagnostics["detail_verification_rejected"] = rejected_by_detail_verification
    diagnostics["status_audit"] = build_status_audit(deduplicate_cards(collected), now)
    diagnostics["raw_cards"] = len(collected)
    diagnostics["unique_cards"] = len(unique)
    diagnostics["provisionally_open"] = provisional_count
    diagnostics["cards_with_active_raw_status"] = sum(
        1 for card in deduplicate_cards(collected) if is_provisionally_open(card, now)[2].normalized_status.value in {"APPLICATION_SUBMISSION", "PRICE_SUBMISSION"}
    )
    diagnostics["cards_with_future_deadline"] = sum(
        1
        for card in deduplicate_cards(collected)
        if (lambda remaining: remaining is not None and remaining > 0)(
            days_to_deadline(parse_datetime(card.application_deadline, config.radar.timezone), now)
        )
    )
    if not unique:
        if provisional_count and rejected_by_detail_verification:
            diagnostics["no_open_candidate_reason"] = "ALL_PROVISIONAL_CANDIDATES_REJECTED_BY_DETAIL_VERIFICATION"
        else:
            diagnostics["no_open_candidate_reason"] = "NO_OPEN_CANDIDATES_FOUND"
    return unique[:limit] if limit else unique, diagnostics
