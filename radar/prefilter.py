from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from radar.config import RadarConfig
from radar.models import EligibilityStatus, RadarCard
from radar.search_profiles import SearchProfile


OPEN_STATUS = "application_submission"
CLOSED_STATUS = "closed"
CANCELLED_STATUS = "cancelled"
COMMISSION_STATUS = "commission"
UNKNOWN_STATUS = "unknown"


def text_blob(card: RadarCard) -> str:
    return " ".join(
        [
            card.title,
            card.customer,
            card.procedure_type,
            card.status_raw,
            card.region,
            card.raw_text,
        ]
    ).lower()


def normalize_status(status: str) -> str:
    value = (status or "").lower()
    if any(term in value for term in ["отмен", "cancel"]):
        return CANCELLED_STATUS
    if any(term in value for term in ["контракт заключ", "заверш", "итог", "поставщик"]):
        return CLOSED_STATUS
    if any(term in value for term in ["работа комиссии", "рассмотр"]):
        return COMMISSION_STATUS
    if any(term in value for term in ["подача заяв", "прием заяв", "приём заяв", "размещ"]):
        return OPEN_STATUS
    return UNKNOWN_STATUS


def parse_datetime(value: str, timezone: str = "Europe/Moscow") -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    patterns = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ]
    tz = ZoneInfo(timezone)
    for pattern in patterns:
        try:
            parsed = datetime.strptime(raw, pattern)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
            return parsed.astimezone(tz)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def parse_as_of(value: str | None, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if not value:
        return datetime.now(tz)
    parsed = parse_datetime(value, timezone)
    if parsed is None:
        raise ValueError(f"Invalid --as-of value: {value}")
    if len(value.strip()) == 10:
        parsed = datetime.combine(parsed.date(), time.min, tzinfo=tz)
    return parsed


def days_to_deadline(deadline: datetime | None, as_of: datetime) -> float | None:
    if deadline is None:
        return None
    delta = deadline - as_of
    return delta.total_seconds() / 86_400


def evaluate_eligibility(
    card: RadarCard,
    as_of: datetime,
    config: RadarConfig,
    profiles: list[SearchProfile],
) -> tuple[EligibilityStatus, float | None, list[str]]:
    reasons: list[str] = []
    status = normalize_status(card.status_raw or card.status_normalized)
    card.status_normalized = status

    deadline = parse_datetime(card.application_deadline, config.radar.timezone)
    remaining = days_to_deadline(deadline, as_of)
    blob = text_blob(card)

    if any(term in blob for term in ["закупка отменена", "отменена"]):
        reasons.append("status indicates cancellation")
        return EligibilityStatus.CLOSED, remaining, reasons
    if status in {CANCELLED_STATUS, CLOSED_STATUS}:
        reasons.append(f"status is {status}")
        return EligibilityStatus.CLOSED, remaining, reasons
    if deadline is None:
        reasons.append("application deadline is unknown")
        return EligibilityStatus.DEADLINE_UNKNOWN, None, reasons
    if remaining is not None and remaining < 0:
        reasons.append("application deadline has passed")
        return EligibilityStatus.CLOSED, remaining, reasons
    if status not in {OPEN_STATUS, UNKNOWN_STATUS}:
        reasons.append(f"status does not clearly allow submission: {status}")
        return EligibilityStatus.STATUS_UNCLEAR, remaining, reasons

    minimum_days = min(
        [
            profile.minimum_days_to_deadline
            for profile in profiles
            if profile.minimum_days_to_deadline is not None
        ]
        or [config.radar.default_minimum_days_to_deadline]
    )
    if remaining is not None and remaining < minimum_days:
        reasons.append(f"deadline is closer than configured minimum ({minimum_days} days)")
        return EligibilityStatus.DEADLINE_TOO_CLOSE, remaining, reasons
    return EligibilityStatus.OPEN, remaining, reasons


PROTECTED_DEVELOPMENT_TERMS = [
    "доработ",
    "модернизац",
    "разработ",
    "новый модуль",
    "развитие систем",
    "изменение функциональ",
]

DEFAULT_HARD_EXCLUSIONS = [
    "поставка компьютеров",
    "серверное оборудование",
    "расходные материалы",
    "принтер",
    "продление лиценз",
    "лицензии без разработ",
    "техническая поддержка без доработ",
    "обучение",
    "рекламные услуги",
    "seo",
    "размещение информации",
    "подписка на сервис",
    "услуги связи",
    "видеонаблюдение",
    "монтаж оборудования",
]


def hard_reject_reasons(card: RadarCard, config: RadarConfig, profiles: list[SearchProfile]) -> list[str]:
    blob = text_blob(card)
    reasons: list[str] = []
    exclusions = list(DEFAULT_HARD_EXCLUSIONS) + list(config.filters.hard_exclusion_terms)
    for profile in profiles:
        exclusions.extend(profile.exclusion_terms)

    if card.nmck is not None and card.nmck < config.filters.hard_nmck_min:
        reasons.append("nmck below hard minimum")

    protected = any(term in blob for term in PROTECTED_DEVELOPMENT_TERMS)
    for term in exclusions:
        term_lower = term.lower()
        if term_lower in blob:
            if "сопровожд" in term_lower and protected:
                continue
            if term_lower in {"seo", "лицензии"} and protected:
                continue
            reasons.append(f"hard exclusion term: {term}")

    if re.search(r"\b1с\b|1с:|битрикс24|directum|diasoft|sap\b", blob):
        reasons.append("specific-platform blocker or penalty")
    return sorted(set(reasons))


def clamp_score(value: float, minimum: int = 0, maximum: int = 100) -> int:
    if math.isnan(value):
        return minimum
    return max(minimum, min(maximum, int(round(value))))

