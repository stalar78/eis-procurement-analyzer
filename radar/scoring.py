from __future__ import annotations

from radar.config import RadarConfig
from radar.models import EligibilityStatus, RadarAssessment, RadarCard, RadarDecision
from radar.prefilter import hard_reject_reasons, text_blob
from radar.search_profiles import SearchProfile


POSITIVE_TERMS = [
    "личный кабинет",
    "административная панель",
    "роли",
    "права",
    "реестр",
    "обработка заявок",
    "workflow",
    "api",
    "интеграция",
    "миграция",
    "генерация документов",
    "нестандартная бизнес-логика",
]

COMMODITY_TERMS = [
    "лендинг",
    "сайт-визитка",
    "tilda",
    "конструктор сайтов",
    "типовой сайт",
    "информационный сайт",
    "создание сайта учреждения",
    "версия для слабовидящих",
    "фотогалерея",
    "простой муниципальный портал",
]

COMPLEXITY_TERMS = [
    "сложные роли",
    "модуль",
    "интеграция",
    "api",
    "миграция",
    "реестр",
    "маршрут согласования",
    "бизнес-процесс",
]

HIGH_RISK_TERMS = [
    "есиа",
    "смэв",
    "гост",
    "криптография",
    "защищенная сеть",
    "24/7",
    "sla",
    "медицинская ис",
    "банковская система",
    "gis",
    "обязательные сертификаты",
    "несколько регионов",
]


def _matches(blob: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term.lower() in blob]


def assess_card(
    card: RadarCard,
    eligibility: EligibilityStatus,
    days_to_deadline: float | None,
    config: RadarConfig,
    profiles: list[SearchProfile],
    is_new: bool = False,
    is_changed: bool = False,
    eligibility_reasons: list[str] | None = None,
) -> RadarAssessment:
    blob = text_blob(card)
    positive_terms = POSITIVE_TERMS[:]
    negative_terms: list[str] = []
    complexity_terms = COMPLEXITY_TERMS[:]
    for profile in profiles:
        positive_terms.extend(profile.positive_terms)
        negative_terms.extend(profile.negative_terms)
        complexity_terms.extend(profile.complexity_bonus_terms)

    positive = sorted(set(_matches(blob, positive_terms)))
    commodity_hits = sorted(set(_matches(blob, COMMODITY_TERMS)))
    complexity_hits = sorted(set(_matches(blob, complexity_terms)))
    high_risk_hits = sorted(set(_matches(blob, HIGH_RISK_TERMS) + _matches(blob, negative_terms)))
    hard_rejects = hard_reject_reasons(card, config, profiles)

    technical_score = min(30, len(positive) * 7)
    complexity_score = min(20, len(complexity_hits) * 5)
    commodity_score = min(30, len(commodity_hits) * 8)
    low_commodity_score = max(0, 10 - commodity_score)

    if card.nmck is None:
        budget_score = 4
    elif config.filters.preferred_nmck_min <= card.nmck <= config.filters.preferred_nmck_max:
        budget_score = 20
    elif card.nmck < config.filters.hard_nmck_min:
        budget_score = 0
    else:
        budget_score = 12

    if days_to_deadline is None:
        deadline_score = 3
    elif days_to_deadline >= config.radar.preferred_days_to_deadline:
        deadline_score = 15
    elif days_to_deadline >= config.radar.default_minimum_days_to_deadline:
        deadline_score = 12
    elif days_to_deadline >= config.radar.deadline_too_close_watch_days:
        deadline_score = 6
    else:
        deadline_score = 0

    data_quality_flags: list[str] = []
    if not card.procurement_number:
        data_quality_flags.append("missing procurement number")
    if not card.title:
        data_quality_flags.append("missing title")
    if not card.application_deadline:
        data_quality_flags.append("missing application deadline")
    if card.nmck is None:
        data_quality_flags.append("missing nmck")
    data_quality_score = 5 if not data_quality_flags else max(0, 5 - len(data_quality_flags))

    exclusion_penalty = min(50, len(hard_rejects) * 25 + len(high_risk_hits) * 5 + commodity_score)
    total = technical_score + budget_score + deadline_score + complexity_score + data_quality_score + low_commodity_score - exclusion_penalty
    total = max(0, min(100, total))

    manual_questions = [f"Check high-risk signal: {term}" for term in high_risk_hits]
    negative = list(eligibility_reasons or [])
    negative.extend([f"commodity signal: {term}" for term in commodity_hits])
    negative.extend([f"high-risk signal: {term}" for term in high_risk_hits])

    if hard_rejects or eligibility == EligibilityStatus.CLOSED:
        decision = RadarDecision.REJECT
    elif data_quality_flags and eligibility in {EligibilityStatus.DEADLINE_UNKNOWN, EligibilityStatus.STATUS_UNCLEAR}:
        decision = RadarDecision.INSUFFICIENT_DATA
    elif (
        total >= config.scoring.priority_threshold
        and eligibility == EligibilityStatus.OPEN
        and len(positive) >= 2
        and not any("specific-platform" in item for item in hard_rejects)
    ):
        decision = RadarDecision.PRIORITY
    elif (
        total >= config.scoring.review_threshold
        and eligibility in {EligibilityStatus.OPEN, EligibilityStatus.DEADLINE_TOO_CLOSE}
    ):
        decision = RadarDecision.REVIEW
    elif total >= config.scoring.watch_threshold or eligibility == EligibilityStatus.DEADLINE_UNKNOWN:
        decision = RadarDecision.WATCH
    else:
        decision = RadarDecision.REJECT

    if eligibility == EligibilityStatus.DEADLINE_TOO_CLOSE and (days_to_deadline or 0) < config.radar.deadline_too_close_watch_days:
        decision = RadarDecision.REJECT

    return RadarAssessment(
        procurement_number=card.procurement_number,
        eligibility_status=eligibility,
        days_to_deadline=days_to_deadline,
        is_new=is_new,
        is_changed=is_changed,
        preliminary_category="card-prefilter",
        commodity_score=commodity_score,
        technical_interest_score=technical_score,
        deadline_score=deadline_score,
        budget_score=budget_score,
        complexity_signal_score=complexity_score,
        exclusion_penalty=exclusion_penalty,
        total_score=total,
        radar_decision=decision,
        positive_reasons=[f"positive signal: {term}" for term in positive]
        + [f"complexity signal: {term}" for term in complexity_hits],
        negative_reasons=sorted(set(negative)),
        hard_reject_reasons=hard_rejects,
        manual_review_questions=manual_questions,
        data_quality_flags=data_quality_flags,
    )

