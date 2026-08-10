from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from radar.discovery import normalize_card
from radar.live_collection import EIS_HOSTS, extract_procurement_number, normalize_eis_url, validate_eis_url
from radar.models import RadarCard
from radar.search_request import redact_url


SOURCE_RESOLUTION_STATUSES = {
    "RESOLVED_LIVE",
    "RESOLVED_SEARCH_RECOVERY",
    "RESOLVED_ALTERNATE_SECTION",
    "RESOLVED_CACHED",
    "TEMPORARILY_UNAVAILABLE",
    "NOT_FOUND_CONFIRMED",
    "NUMBER_MISMATCH",
    "INVALID_SOURCE",
    "PARTIAL_RESOLUTION",
}

TEMPORARY_HTTP_STATUSES = {404, 429, 500, 502, 503, 504}
SECTION_PATTERNS = [
    ("common-info", "common-info"),
    ("documents", "documents"),
    ("supplier-results", "results"),
    ("protocol", "protocol"),
    ("printForm", "print_form"),
]


@dataclass
class SourceResolutionAttempt:
    procurement_number: str
    strategy: str
    requested_url: str
    resolved_url: str = ""
    http_status: int | None = None
    browser_status: str = ""
    procurement_number_match: bool = False
    page_type: str = ""
    content_valid: bool = False
    content_fingerprint: str = ""
    attempted_at: str = ""
    duration_seconds: float = 0.0
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceResolutionResult:
    procurement_number: str
    status: str
    canonical_url: str = ""
    page_type: str = ""
    confidence: str = "LOW"
    strategy_used: str = ""
    attempts: list[SourceResolutionAttempt] = field(default_factory=list)
    first_successful_url: str = ""
    last_successful_url: str = ""
    cache_used: bool = False
    stale_cache_used: bool = False
    validation_warnings: list[str] = field(default_factory=list)
    resolved_at: str = ""
    source_card: RadarCard | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["attempts"] = [item.to_dict() for item in self.attempts]
        data["source_card"] = self.source_card.to_dict() if self.source_card else None
        return data


@dataclass
class SourceResolutionPolicy:
    max_attempts_per_strategy: int = 2
    retry_delay_seconds: float = 2.0
    retry_backoff_multiplier: float = 2.0
    retry_statuses: list[int] = field(default_factory=lambda: [404, 429, 500, 502, 503, 504])
    enable_search_recovery: bool = True
    enable_alternate_section_recovery: bool = True
    enable_cached_source_fallback: bool = True
    cached_source_max_age_hours: int = 336
    confirmation_attempts_for_not_found: int = 3


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fingerprint_content(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8", errors="ignore")).hexdigest()


def page_type_for_url(url: str) -> str:
    lowered = url.lower()
    for needle, page_type in SECTION_PATTERNS:
        if needle.lower() in lowered:
            return page_type
    return "unknown"


def content_has_number(content: str, number: str) -> bool:
    return bool(number and number in (content or ""))


def content_is_valid_source(content: str, number: str) -> bool:
    if not content or "404 Not Found" in content[:1000]:
        return False
    if "<html" not in content.lower() and number not in content:
        return False
    return content_has_number(content, number)


def extract_text(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_money(value: str) -> float | None:
    matches = re.findall(r"\d[\d\s]*(?:[,.]\d{1,2})?", value.replace("\xa0", " "))
    if not matches:
        return None
    try:
        return float(matches[-1].replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def extract_card_from_source(number: str, url: str, html: str) -> RadarCard:
    text = extract_text(html)
    title = ""
    title_match = re.search(
        r"(?:Объект закупки|Наименование объекта закупки|Наименование закупки)\s*:?\s*(.{20,260}?)(?:Организация|Заказчик|Начальная|НМЦК|$)",
        text,
        re.IGNORECASE,
    )
    if title_match:
        title = title_match.group(1).strip(" :-")
    if not title:
        portal_match = re.search(r"([^.]{0,80}(?:портал|сайт|информационн\w+ систем\w+)[^.]{10,180})", text, re.IGNORECASE)
        if portal_match:
            title = portal_match.group(1).strip(" :-")
    customer = ""
    customer_match = re.search(r"(?:Заказчик|Организация, осуществляющая размещение)\s*:?\s*([A-ZА-ЯЁ][^:]{10,180}?)(?:ИНН|КПП|Место|Начальная|$)", text, re.IGNORECASE)
    if customer_match:
        customer = customer_match.group(1).strip(" :-")
    nmck = None
    nmck_match = re.search(r"(?:НМЦК|Начальная\s+\(максимальная\)\s+цена|Начальная цена).{0,120}?(\d[\d\s]*(?:[,.]\d{1,2})?)", text, re.IGNORECASE)
    if nmck_match:
        nmck = parse_money(nmck_match.group(1))
    card = normalize_card(
        {
            "procurement_number": number,
            "title": title,
            "customer": customer,
            "law": "44-FZ" if "44-ФЗ" in text or "44-Ф3" in text else "",
            "procedure_type": "Электронный аукцион" if "аукцион" in text.lower() else "",
            "status": "Определение поставщика завершено" if "заверш" in text.lower() else "",
            "status_normalized": "COMPLETED",
            "nmck": nmck,
            "source_url": url,
            "raw_text": text[:5000],
        }
    )
    return card


def default_fetch(url: str) -> tuple[int | None, str, str]:
    import requests
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        response = requests.get(url, timeout=45, verify=False, headers={"User-Agent": "Mozilla/5.0"})
    return response.status_code, response.url, response.text


def make_attempt(number: str, strategy: str, url: str, fetch: Callable[[str], tuple[int | None, str, str]]) -> tuple[SourceResolutionAttempt, str]:
    started = time.monotonic()
    attempt = SourceResolutionAttempt(procurement_number=number, strategy=strategy, requested_url=redact_url(url), attempted_at=now_iso())
    content = ""
    try:
        status, resolved_url, content = fetch(url)
        attempt.http_status = status
        attempt.resolved_url = redact_url(resolved_url or url)
        attempt.page_type = page_type_for_url(resolved_url or url)
        attempt.procurement_number_match = content_has_number(content, number) or extract_procurement_number(resolved_url or "") == number
        attempt.content_valid = content_is_valid_source(content, number)
        attempt.content_fingerprint = fingerprint_content(content) if content else ""
        if status in {429}:
            attempt.error_code = "EIS_RATE_LIMITED"
        elif status and status >= 500:
            attempt.error_code = "EIS_SERVER_ERROR"
        elif status == 404 and not attempt.content_valid:
            attempt.error_code = "SOURCE_404_TRANSIENT"
        elif not attempt.content_valid:
            attempt.error_code = "SOURCE_CONTENT_INVALID"
    except ValueError as error:
        attempt.error_code = "SOURCE_NUMBER_MISMATCH"
        attempt.error_message = str(error)
    except Exception as error:
        attempt.error_code = "SOURCE_TEMPORARILY_UNAVAILABLE"
        attempt.error_message = str(error)
    attempt.duration_seconds = round(time.monotonic() - started, 3)
    return attempt, content


def exact_search_url(number: str) -> str:
    return "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?" + urlencode(
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


def extract_matching_links(number: str, html: str, base: str = "https://zakupki.gov.ru") -> list[str]:
    links = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or "", flags=re.IGNORECASE):
        if number not in href:
            continue
        target = urljoin(base, href)
        parsed = urlparse(target)
        if parsed.hostname not in EIS_HOSTS:
            continue
        params = parse_qs(parsed.query)
        values = [item for values in params.values() for item in values]
        if number not in values and extract_procurement_number(target) != number:
            continue
        links.append(urlunparse(parsed._replace(fragment="")))
    ordered = sorted(set(links), key=lambda url: ("common-info" not in url, "documents" not in url, "supplier-results" not in url, "printForm" not in url, url))
    return ordered


def sibling_section_urls(url: str, number: str) -> list[str]:
    base_paths = [
        "common-info",
        "documents",
        "supplier-results",
        "protocol",
    ]
    parsed = urlparse(url)
    urls = []
    for section in base_paths:
        path = re.sub(r"/view/[^/]+\.html$", f"/view/{section}.html", parsed.path)
        if path == parsed.path and "/view/" not in parsed.path:
            continue
        urls.append(urlunparse(parsed._replace(path=path, query=f"regNumber={number}", fragment="")))
    urls.append(f"https://zakupki.gov.ru/epz/order/notice/printForm/view.html?regNumber={number}")
    return sorted(set(urls))


def load_cached_source_snapshot(output_dir: str | Path, number: str, max_age_hours: int) -> tuple[RadarCard | None, dict[str, Any]]:
    candidates = [
        Path(output_dir) / "source_snapshot.json",
        Path(output_dir) / "latest.json",
        Path(output_dir) / "latest_attempt.json",
    ]
    newest: tuple[RadarCard, dict[str, Any]] | None = None
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cards: list[dict[str, Any]] = []
            if data.get("procurement_number") == number:
                cards.append(data)
            for item in data.get("items", []):
                if item.get("card", {}).get("procurement_number") == number:
                    cards.append(item["card"])
            if data.get("source_card", {}).get("procurement_number") == number:
                cards.append(data["source_card"])
            for raw in cards:
                if not raw.get("title") and raw.get("nmck") is None:
                    continue
                mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
                age_hours = (datetime.now(mtime.tzinfo) - mtime).total_seconds() / 3600
                card = RadarCard(**raw)
                meta = {"path": str(path), "age_hours": round(age_hours, 2), "stale": age_hours > max_age_hours}
                if newest is None or meta["age_hours"] < newest[1]["age_hours"]:
                    newest = (card, meta)
        except Exception:
            continue
    return newest if newest else (None, {})


def save_source_snapshot(output_dir: str | Path, card: RadarCard, result: SourceResolutionResult) -> str:
    path = Path(output_dir) / "source_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = card.to_dict()
    payload["source_resolution"] = result.to_dict()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def resolve_procurement_source(
    procurement_number: str,
    *,
    source_url: str | None = None,
    output_dir: str | Path | None = None,
    policy: SourceResolutionPolicy | None = None,
    fetch: Callable[[str], tuple[int | None, str, str]] | None = None,
) -> SourceResolutionResult:
    policy = policy or SourceResolutionPolicy()
    fetch = fetch or default_fetch
    attempts: list[SourceResolutionAttempt] = []
    resolved_at = now_iso()

    def success(status: str, strategy: str, attempt: SourceResolutionAttempt, content: str, confidence: str = "HIGH") -> SourceResolutionResult:
        card = extract_card_from_source(procurement_number, attempt.resolved_url or attempt.requested_url, content)
        result = SourceResolutionResult(
            procurement_number=procurement_number,
            status=status,
            canonical_url=attempt.resolved_url or attempt.requested_url,
            page_type=attempt.page_type,
            confidence=confidence,
            strategy_used=strategy,
            attempts=attempts,
            first_successful_url=attempt.resolved_url or attempt.requested_url,
            last_successful_url=attempt.resolved_url or attempt.requested_url,
            resolved_at=resolved_at,
            source_card=card,
        )
        if output_dir:
            save_source_snapshot(output_dir, card, result)
        return result

    if source_url:
        try:
            validate_eis_url(source_url)
            normalize_eis_url(source_url, procurement_number)
        except Exception as error:
            attempt = SourceResolutionAttempt(procurement_number, "SUPPLIED_URL", redact_url(source_url), attempted_at=now_iso(), error_code="SOURCE_NUMBER_MISMATCH", error_message=str(error))
            attempts.append(attempt)
            return SourceResolutionResult(procurement_number, "NUMBER_MISMATCH", attempts=attempts, validation_warnings=[str(error)], resolved_at=resolved_at)
        for index in range(policy.max_attempts_per_strategy):
            attempt, content = make_attempt(procurement_number, "SUPPLIED_URL", source_url, fetch)
            attempts.append(attempt)
            if attempt.content_valid:
                return success("RESOLVED_LIVE", "SUPPLIED_URL", attempt, content)
            if attempt.http_status not in policy.retry_statuses:
                break

    if output_dir and policy.enable_cached_source_fallback:
        cached_card, cache_meta = load_cached_source_snapshot(output_dir, procurement_number, policy.cached_source_max_age_hours)
        if cached_card and not cache_meta.get("stale"):
            return SourceResolutionResult(
                procurement_number=procurement_number,
                status="RESOLVED_CACHED",
                canonical_url=cached_card.source_url,
                page_type=page_type_for_url(cached_card.source_url),
                confidence="MEDIUM",
                strategy_used="CACHED_SOURCE",
                attempts=attempts,
                first_successful_url=cached_card.source_url,
                last_successful_url=cached_card.source_url,
                cache_used=True,
                stale_cache_used=False,
                validation_warnings=[f"cached source used; age_hours={cache_meta.get('age_hours')}"],
                resolved_at=resolved_at,
                source_card=cached_card,
            )

    recovered_links: list[str] = []
    if policy.enable_search_recovery:
        search = exact_search_url(procurement_number)
        attempt, content = make_attempt(procurement_number, "EXACT_NUMBER_SEARCH", search, fetch)
        attempts.append(attempt)
        if attempt.content_valid:
            recovered_links = extract_matching_links(procurement_number, content)
            if not recovered_links:
                return success("PARTIAL_RESOLUTION", "EXACT_NUMBER_SEARCH", attempt, content, confidence="LOW")
            for link in recovered_links[:5]:
                linked_attempt, linked_content = make_attempt(procurement_number, "SEARCH_RECOVERED_LINK", link, fetch)
                attempts.append(linked_attempt)
                if linked_attempt.content_valid:
                    return success("RESOLVED_SEARCH_RECOVERY", "SEARCH_RECOVERED_LINK", linked_attempt, linked_content)
        elif attempt.http_status == 200 and procurement_number not in content:
            return SourceResolutionResult(procurement_number, "NOT_FOUND_CONFIRMED", attempts=attempts, strategy_used="EXACT_NUMBER_SEARCH", confidence="HIGH", resolved_at=resolved_at)

    if policy.enable_alternate_section_recovery:
        seeds = recovered_links or ([source_url] if source_url else [])
        for seed in seeds[:3]:
            for link in sibling_section_urls(seed, procurement_number)[:5]:
                attempt, content = make_attempt(procurement_number, "ALTERNATE_SECTION", link, fetch)
                attempts.append(attempt)
                if attempt.content_valid:
                    return success("RESOLVED_ALTERNATE_SECTION", "ALTERNATE_SECTION", attempt, content, confidence="MEDIUM")

    if output_dir and policy.enable_cached_source_fallback:
        cached_card, cache_meta = load_cached_source_snapshot(output_dir, procurement_number, policy.cached_source_max_age_hours)
        if cached_card:
            return SourceResolutionResult(
                procurement_number=procurement_number,
                status="RESOLVED_CACHED",
                canonical_url=cached_card.source_url,
                page_type=page_type_for_url(cached_card.source_url),
                confidence="LOW",
                strategy_used="STALE_CACHED_SOURCE",
                attempts=attempts,
                first_successful_url=cached_card.source_url,
                last_successful_url=cached_card.source_url,
                cache_used=True,
                stale_cache_used=True,
                validation_warnings=[f"stale cached source used; age_hours={cache_meta.get('age_hours')}"],
                resolved_at=resolved_at,
                source_card=cached_card,
            )

    temporary_count = sum(1 for item in attempts if item.error_code in {"SOURCE_404_TRANSIENT", "SOURCE_TEMPORARILY_UNAVAILABLE", "EIS_RATE_LIMITED", "EIS_SERVER_ERROR", "SOURCE_CONTENT_INVALID"})
    status = "TEMPORARILY_UNAVAILABLE" if temporary_count else "NOT_FOUND_CONFIRMED"
    return SourceResolutionResult(
        procurement_number=procurement_number,
        status=status,
        confidence="LOW",
        strategy_used=attempts[-1].strategy if attempts else "",
        attempts=attempts,
        validation_warnings=["single 404 is treated as transient until exact search absence is confirmed"] if temporary_count else [],
        resolved_at=resolved_at,
    )
