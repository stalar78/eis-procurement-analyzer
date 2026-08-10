from __future__ import annotations

import re
import html
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from radar.models import NormalizedStatus, RadarCard
from radar.prefilter import days_to_deadline, parse_datetime


@dataclass
class StatusInfo:
    normalized_status: NormalizedStatus
    reason: str
    confidence: str


@dataclass
class OpenVerification:
    procurement_number: str
    card_status_raw: str = ""
    detail_status_raw: str = ""
    card_deadline: str = ""
    detail_deadline: str = ""
    open_verification_status: str = "NOT_VERIFIED"
    open_verification_reasons: list[str] = field(default_factory=list)
    open_verification_timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_status_v2(status: str) -> StatusInfo:
    value = (status or "").lower()
    if any(term in value for term in ["закупка отменена", "отмен"]):
        return StatusInfo(NormalizedStatus.CANCELLED, "cancellation keyword", "high")
    if any(term in value for term in ["контракт заключ", "контракт подпис"]):
        return StatusInfo(NormalizedStatus.CONTRACT_SIGNED, "contract signed keyword", "high")
    if any(term in value for term in ["определение поставщика завершено", "закупка завершена", "заверш"]):
        return StatusInfo(NormalizedStatus.COMPLETED, "completion keyword", "high")
    if any(term in value for term in ["подача ценовых предлож", "ценов"]):
        return StatusInfo(NormalizedStatus.PRICE_SUBMISSION, "price submission keyword", "medium")
    if any(term in value for term in ["подача заяв", "прием заяв", "приём заяв", "ожидание подачи"]):
        return StatusInfo(NormalizedStatus.APPLICATION_SUBMISSION, "application submission keyword", "high")
    if any(term in value for term in ["работа комиссии", "рассмотр"]):
        return StatusInfo(NormalizedStatus.COMMISSION_REVIEW, "commission keyword", "medium")
    if any(term in value for term in ["приостанов"]):
        return StatusInfo(NormalizedStatus.SUSPENDED, "suspended keyword", "high")
    return StatusInfo(NormalizedStatus.UNKNOWN, "no mapping rule matched", "low")


def is_provisionally_open(card: RadarCard, as_of: datetime) -> tuple[bool, list[str], StatusInfo]:
    info = normalize_status_v2(card.status_raw or card.status_normalized)
    deadline = parse_datetime(card.application_deadline)
    remaining = days_to_deadline(deadline, as_of)
    reasons: list[str] = [info.reason]
    if info.normalized_status not in {NormalizedStatus.APPLICATION_SUBMISSION, NormalizedStatus.PRICE_SUBMISSION}:
        reasons.append(f"status is not active: {info.normalized_status.value}")
        return False, reasons, info
    if deadline is None:
        reasons.append("deadline is missing")
        return False, reasons, info
    if remaining is None or remaining <= 0:
        reasons.append("deadline is not in the future")
        return False, reasons, info
    reasons.append("active status and future deadline")
    return True, reasons, info


def extract_status_from_detail_text(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text)
    patterns = [
        r"Статус\s*:?\s*([^\n\r]{3,120})",
        r"Этап закупки\s*:?\s*([^\n\r]{3,120})",
        r"(Подача заявок|Прием заявок|Приём заявок|Определение поставщика завершено|Закупка отменена|Работа комиссии)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def extract_deadline_from_detail_text(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text)
    patterns = [
        r"Окончание подачи заявок\s*:?\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4}(?:\s+[0-9:]+)?)",
        r"Дата и время окончания срока подачи заявок\s*:?\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4}(?:\s+[0-9:]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def verify_open_from_detail_text(card: RadarCard, detail_text: str, as_of: datetime) -> OpenVerification:
    detail_status = extract_status_from_detail_text(detail_text)
    detail_deadline = extract_deadline_from_detail_text(detail_text)
    info = normalize_status_v2(detail_status or card.status_raw)
    card_deadline = parse_datetime(card.application_deadline)
    verified_deadline = parse_datetime(detail_deadline) or card_deadline
    remaining = days_to_deadline(verified_deadline, as_of)
    reasons: list[str] = [info.reason]
    status = "VERIFIED_OPEN"
    if info.normalized_status == NormalizedStatus.CANCELLED:
        status = "VERIFIED_CANCELLED"
    elif info.normalized_status in {NormalizedStatus.COMPLETED, NormalizedStatus.CONTRACT_SIGNED}:
        status = "VERIFIED_CLOSED"
    elif (
        detail_deadline
        and card.application_deadline
        and parse_datetime(detail_deadline)
        and card_deadline
        and parse_datetime(detail_deadline).date() != card_deadline.date()
    ):
        status = "DEADLINE_CONFLICT"
        reasons.append("detail deadline differs from card deadline")
    elif info.normalized_status not in {NormalizedStatus.APPLICATION_SUBMISSION, NormalizedStatus.PRICE_SUBMISSION}:
        status = "STATUS_CONFLICT"
    elif remaining is None or remaining <= 0:
        status = "DEADLINE_CONFLICT"
        reasons.append("detail deadline is not in the future")
    else:
        reasons.append("detail status and deadline confirm open procurement")
    return OpenVerification(
        procurement_number=card.procurement_number,
        card_status_raw=card.status_raw,
        detail_status_raw=detail_status,
        card_deadline=card.application_deadline,
        detail_deadline=detail_deadline,
        open_verification_status=status,
        open_verification_reasons=reasons,
        open_verification_timestamp=datetime.now(as_of.tzinfo).isoformat(timespec="seconds"),
    )


def unavailable_verification(card: RadarCard, reason: str, as_of: datetime) -> OpenVerification:
    return OpenVerification(
        procurement_number=card.procurement_number,
        card_status_raw=card.status_raw,
        card_deadline=card.application_deadline,
        open_verification_status="DETAIL_UNAVAILABLE",
        open_verification_reasons=[reason],
        open_verification_timestamp=datetime.now(as_of.tzinfo).isoformat(timespec="seconds"),
    )


def build_status_audit(cards: list[RadarCard], as_of: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for card in cards:
        raw = card.status_raw or ""
        info = normalize_status_v2(raw)
        deadline = parse_datetime(card.application_deadline)
        remaining = days_to_deadline(deadline, as_of)
        row = grouped.setdefault(
            raw,
            {
                "raw_status": raw,
                "normalized_status": info.normalized_status.value,
                "occurrence_count": 0,
                "future_deadline_count": 0,
                "past_deadline_count": 0,
                "example_procurement_numbers": [],
                "normalization_confidence": info.confidence,
                "mapping_rule": info.reason,
            },
        )
        row["occurrence_count"] += 1
        if remaining is not None and remaining > 0:
            row["future_deadline_count"] += 1
        elif remaining is not None:
            row["past_deadline_count"] += 1
        if len(row["example_procurement_numbers"]) < 5:
            row["example_procurement_numbers"].append(card.procurement_number)
    return list(grouped.values())
