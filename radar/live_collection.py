from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

EIS_HOSTS = {
    "zakupki.gov.ru",
    "www.zakupki.gov.ru",
}

SECTION_PATH_HINTS = {
    "common": "common-info",
    "documents": "documents",
    "results": "supplier-results",
    "events": "event-journal",
    "protocols": "protocol",
    "contracts": "contract",
}


@dataclass
class ProcurementCollectionTarget:
    procurement_number: str
    source_url: str = ""


@dataclass
class LiveCollectionRequest:
    procurement_number: str
    source_url: str
    output_directory: Path
    overwrite: bool = False
    refresh: bool = False
    max_documents: int | None = None
    max_total_bytes: int | None = None
    max_single_file_bytes: int | None = None
    page_timeout_seconds: int = 90
    download_timeout_seconds: int = 90
    allowed_sections: list[str] = field(default_factory=lambda: ["common", "documents", "results", "events", "protocols", "contracts"])
    verbose: bool = False


@dataclass
class LiveCollectionResult:
    procurement_number: str
    source_url: str
    procurement_directory: str
    status: str
    pages_visited: int = 0
    sections_visited: list[str] = field(default_factory=list)
    document_links_found: int = 0
    documents_attempted: int = 0
    documents_downloaded: int = 0
    documents_skipped_cached: int = 0
    documents_failed: int = 0
    total_downloaded_bytes: int = 0
    manifest_path: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    resolved_common_url: str = ""
    document_set_fingerprint: str = ""
    analyzer_status: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_procurement_number(value: str) -> str:
    match = re.search(r"\b\d{10,25}\b", value or "")
    return match.group(0) if match else ""


def validate_eis_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("unsupported URL scheme")
    if parsed.hostname not in EIS_HOSTS:
        raise ValueError("non-EIS URL is not allowed")
    if parsed.scheme in {"javascript", "data", "file"}:
        raise ValueError("unsafe URL scheme")
    if not parsed.path:
        raise ValueError("malformed EIS URL")
    return urlunparse(parsed)


def normalize_eis_url(url: str, procurement_number: str | None = None) -> tuple[str, str]:
    normalized = validate_eis_url(url)
    parsed = urlparse(normalized)
    query = parse_qs(parsed.query)
    number = procurement_number or ""
    for key in ("regNumber", "registryNumber", "noticeNumber"):
        if query.get(key):
            number = extract_procurement_number(query[key][0])
            break
    if not number:
        number = extract_procurement_number(normalized)
    if not number:
        raise ValueError("procurement number is not resolvable from URL")
    if procurement_number and procurement_number != number:
        raise ValueError("procurement number does not match source URL")
    return normalized, number


def canonical_url_for_number(procurement_number: str) -> str:
    number = extract_procurement_number(procurement_number)
    if not number:
        raise ValueError("malformed procurement number")
    return f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={number}"


def section_url(source_url: str, section: str) -> str:
    validate_eis_url(source_url)
    if section == "common":
        return source_url
    parsed = urlparse(source_url)
    path = parsed.path
    for hint in SECTION_PATH_HINTS.values():
        path = path.replace(f"/{hint}.html", f"/{SECTION_PATH_HINTS[section]}.html")
    if path == parsed.path and path.endswith(".html"):
        path = re.sub(r"[^/]+\.html$", f"{SECTION_PATH_HINTS[section]}.html", path)
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


def deduplicate_document_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for link in links:
        url = str(link.get("url") or link.get("source_url") or "")
        normalized = urlunparse(urlparse(url)._replace(fragment=""))
        if normalized in seen:
            continue
        seen.add(normalized)
        new_link = dict(link)
        new_link["url"] = normalized
        result.append(new_link)
    return result

