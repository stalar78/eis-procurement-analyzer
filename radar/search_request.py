from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from radar.config import RadarConfig


DISCOVERY_MODES = {"ACTIVE_ONLY", "ACTIVE_AND_RECENT", "ALL_STATUSES", "COMPLETED_ONLY", "COMPLETED_AND_FAILED", "FAILED_ONLY", "FAILED_AND_COMPLETED", "CUSTOMER_HISTORY", "SUPPLIER_HISTORY", "OFFLINE"}
STATUS_PARAMS = {
    "application_submission": "af",
    "commission_review": "ca",
    "completed": "pc",
    "cancelled": "pa",
}
SORT_FIELDS = {"update_date": "UPDATE_DATE", "publish_date": "PUBLISH_DATE", "price": "PRICE"}
SORT_FIELDS_REVERSE = {value: key for key, value in SORT_FIELDS.items()}


@dataclass
class SearchRequest:
    query_text: str
    law: str = "all"
    discovery_mode: str = "ACTIVE_ONLY"
    included_statuses: list[str] = field(default_factory=lambda: ["application_submission"])
    excluded_statuses: list[str] = field(default_factory=list)
    published_from: str = ""
    published_to: str = ""
    updated_from: str = ""
    updated_to: str = ""
    application_deadline_from: str = ""
    application_deadline_to: str = ""
    sort_field: str = "update_date"
    sort_direction: str = "desc"
    page_number: int = 1
    page_size: int = 50
    source_profile: str = ""

    def fingerprint(self) -> str:
        payload = {
            "query_text": self.query_text,
            "law": self.law,
            "discovery_mode": self.discovery_mode,
            "included_statuses": self.included_statuses,
            "published_from": self.published_from,
            "published_to": self.published_to,
            "application_deadline_from": self.application_deadline_from,
            "application_deadline_to": self.application_deadline_to,
            "sort_field": self.sort_field,
            "sort_direction": self.sort_direction,
            "page_size": self.page_size,
            "source_profile": self.source_profile,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _date(value: datetime) -> str:
    return value.strftime("%d.%m.%Y")


def build_eis_search_request(
    query_text: str,
    config: RadarConfig,
    *,
    source_profile: str = "",
    page_number: int = 1,
    as_of: datetime | None = None,
    published_within_days: int | None = None,
    updated_within_days: int | None = None,
    discovery_mode: str | None = None,
) -> SearchRequest:
    mode = discovery_mode or config.discovery.mode
    if mode not in DISCOVERY_MODES:
        raise ValueError(f"Unsupported discovery mode: {mode}")
    now = as_of or datetime.now().astimezone()
    published_days = published_within_days if published_within_days is not None else config.discovery.published_within_days
    updated_days = updated_within_days if updated_within_days is not None else config.discovery.updated_within_days

    if mode == "ALL_STATUSES":
        included = ["application_submission", "commission_review", "completed", "cancelled"]
    elif mode == "COMPLETED_ONLY":
        included = ["completed"]
    elif mode == "COMPLETED_AND_FAILED":
        included = ["completed", "cancelled"]
    elif mode == "FAILED_ONLY":
        included = ["completed", "cancelled"]
    elif mode == "FAILED_AND_COMPLETED":
        included = ["completed", "cancelled"]
    elif mode in {"CUSTOMER_HISTORY", "SUPPLIER_HISTORY"}:
        included = ["completed", "cancelled"]
    elif mode == "ACTIVE_AND_RECENT":
        included = ["application_submission", "commission_review"]
    else:
        included = ["application_submission"]

    return SearchRequest(
        query_text=query_text,
        law="all",
        discovery_mode=mode,
        included_statuses=included,
        excluded_statuses=config.discovery.exclude_statuses,
        published_from=_date(now - timedelta(days=published_days)) if published_days else "",
        published_to=_date(now),
        updated_from=_date(now - timedelta(days=updated_days)) if updated_days else "",
        updated_to=_date(now),
        application_deadline_from=_date(now) if mode == "ACTIVE_ONLY" else "",
        application_deadline_to="",
        sort_field=config.discovery.sort.get("field", "update_date"),
        sort_direction=config.discovery.sort.get("direction", "desc"),
        page_number=page_number,
        page_size=50,
        source_profile=source_profile,
    )


def serialize_eis_search_request(request: SearchRequest, base_url: str) -> str:
    parsed = urlparse(base_url)
    params: dict[str, list[str]] = {}
    params["searchString"] = [request.query_text]
    params["morphology"] = ["on"]
    params["search-filter"] = ["Дате размещения"]
    params["pageNumber"] = [str(request.page_number)]
    params["sortDirection"] = ["true" if request.sort_direction == "asc" else "false"]
    params["recordsPerPage"] = [f"_{request.page_size}"]
    params["showLotsInfoHidden"] = ["false"]
    params["sortBy"] = [SORT_FIELDS.get(request.sort_field, request.sort_field)]
    if "44-FZ" in request.law or request.law == "all":
        params["fz44"] = ["on"]
    if "223-FZ" in request.law or request.law == "all":
        params["fz223"] = ["on"]
    params["selectedLaws"] = ["FZ44,FZ223"]
    params["currencyIdGeneral"] = ["-1"]
    for status in request.included_statuses:
        param = STATUS_PARAMS.get(status)
        if param:
            params[param] = ["on"]
    if request.discovery_mode in {"FAILED_ONLY", "FAILED_AND_COMPLETED"}:
        params["pc"] = ["on"]
        params["pa"] = ["on"]
    if request.published_from:
        params["publishDateFrom"] = [request.published_from]
    if request.published_to:
        params["publishDateTo"] = [request.published_to]
    if request.application_deadline_from:
        params["applSubmissionCloseDateFrom"] = [request.application_deadline_from]
    if request.application_deadline_to:
        params["applSubmissionCloseDateTo"] = [request.application_deadline_to]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(params, doseq=True), parsed.fragment))


def request_from_url(url: str, source_profile: str = "") -> SearchRequest:
    params = parse_qs(urlparse(url).query)
    included = [name for name, param in STATUS_PARAMS.items() if param in params]
    if params.get("pa") and params.get("pc"):
        mode = "FAILED_ONLY" if "af" not in params and "ca" not in params else "FAILED_AND_COMPLETED"
    elif params.get("pa"):
        mode = "FAILED_ONLY"
    elif "pc" in params and "af" not in params and "ca" not in params:
        mode = "COMPLETED_ONLY"
    elif {"pc", "pa"} & set(params):
        mode = "ALL_STATUSES"
    else:
        mode = "ACTIVE_ONLY"
    return SearchRequest(
        query_text=params.get("searchString", [""])[0],
        discovery_mode=mode,
        included_statuses=included,
        published_from=params.get("publishDateFrom", [""])[0],
        published_to=params.get("publishDateTo", [""])[0],
        application_deadline_from=params.get("applSubmissionCloseDateFrom", [""])[0],
        application_deadline_to=params.get("applSubmissionCloseDateTo", [""])[0],
        sort_field=SORT_FIELDS_REVERSE.get(params.get("sortBy", ["UPDATE_DATE"])[0], params.get("sortBy", ["UPDATE_DATE"])[0]),
        sort_direction="asc" if params.get("sortDirection", ["false"])[0] == "true" else "desc",
        page_number=int(params.get("pageNumber", ["1"])[0]),
        page_size=int(params.get("recordsPerPage", ["_50"])[0].replace("_", "")),
        source_profile=source_profile,
    )


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    for key in list(params):
        if any(token in key.lower() for token in ["session", "token", "cookie", "auth"]):
            params[key] = ["<redacted>"]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(params, doseq=True), parsed.fragment))
