from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.config import RadarConfig
from radar.models import RadarCard
from radar.open_verification import build_status_audit, is_provisionally_open, unavailable_verification, verify_open_from_detail_text
from radar.prefilter import days_to_deadline, normalize_status, parse_datetime
from radar.search_request import SearchRequest, build_eis_search_request, redact_url, request_from_url, serialize_eis_search_request
from radar.search_profiles import SearchProfile


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


def verify_cards_from_detail(cards: list[RadarCard], as_of: datetime, limit: int) -> list[dict[str, Any]]:
    import requests
    import warnings

    results: list[dict[str, Any]] = []
    for card in cards[:limit]:
        if not card.source_url:
            results.append(unavailable_verification(card, "missing source URL", as_of).to_dict())
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                response = requests.get(card.source_url, timeout=30, verify=False)
            if response.status_code >= 400:
                results.append(unavailable_verification(card, f"HTTP {response.status_code}", as_of).to_dict())
                continue
            results.append(verify_open_from_detail_text(card, response.text, as_of).to_dict())
        except Exception as error:
            results.append(unavailable_verification(card, str(error), as_of).to_dict())
    return results


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
    if config.discovery.verify_open_status_from_detail_page and unique:
        verifications = verify_cards_from_detail(unique, now, config.discovery.verify_top_candidates_limit)
        verified_open_numbers = {
            row["procurement_number"]
            for row in verifications
            if row.get("open_verification_status") == "VERIFIED_OPEN"
        }
        unique = [card for card in unique if card.procurement_number in verified_open_numbers]
    diagnostics["open_verifications"] = verifications
    diagnostics["detail_verifications_attempted"] = len(verifications)
    diagnostics["verified_open"] = sum(1 for row in verifications if row.get("open_verification_status") == "VERIFIED_OPEN")
    diagnostics["verified_closed"] = sum(1 for row in verifications if row.get("open_verification_status") == "VERIFIED_CLOSED")
    diagnostics["verified_cancelled"] = sum(1 for row in verifications if row.get("open_verification_status") == "VERIFIED_CANCELLED")
    diagnostics["status_conflicts"] = sum(1 for row in verifications if row.get("open_verification_status") == "STATUS_CONFLICT")
    diagnostics["deadline_conflicts"] = sum(1 for row in verifications if row.get("open_verification_status") == "DEADLINE_CONFLICT")
    diagnostics["detail_unavailable"] = sum(1 for row in verifications if row.get("open_verification_status") == "DETAIL_UNAVAILABLE")
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
        diagnostics["no_open_candidate_reason"] = "NO_OPEN_CANDIDATES_FOUND"
    return unique[:limit] if limit else unique, diagnostics
