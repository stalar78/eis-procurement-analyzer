from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from radar import opportunity_intelligence_version
from radar.analog_search import extract_functional_terms, normalize_text, normalize_tokens
from radar.config import RadarConfig
from radar.historical import budget_similarity
from radar.models import (
    EligibilityStatus,
    NoCompetitionOpportunity,
    OpportunityTransition,
    ProcurementFailureEvent,
    RadarAssessment,
    RadarCard,
    RadarDecision,
    RepeatedProcurementLink,
)
from radar.prefilter import parse_datetime


FAILURE_TYPES = {
    "NO_APPLICATIONS",
    "SINGLE_APPLICATION",
    "ALL_APPLICATIONS_REJECTED",
    "NO_ADMITTED_APPLICATIONS",
    "PROCUREMENT_CANCELLED",
    "PROCEDURE_DECLARED_UNSUCCESSFUL",
    "CONTRACT_NOT_CONCLUDED",
    "UNKNOWN_FAILURE",
}

EXPLICIT_REFERENCE_PATTERNS = [
    r"(?:regNumber|purchaseNoticeNumber)=([0-9]{8,25})",
    r"(?:извещени[ея]|закупк[аи])\s*(?:№|N|N\s*|номер)?\s*([0-9]{8,25})",
]


@dataclass
class OpportunityAssessmentResult:
    failure_events: list[ProcurementFailureEvent] = field(default_factory=list)
    republication_links: list[RepeatedProcurementLink] = field(default_factory=list)
    opportunities: list[NoCompetitionOpportunity] = field(default_factory=list)
    transitions: list[OpportunityTransition] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_events": [item.to_dict() for item in self.failure_events],
            "republication_links": [item.to_dict() for item in self.republication_links],
            "opportunities": [item.to_dict() for item in self.opportunities],
            "transitions": [item.to_dict() for item in self.transitions],
            "diagnostics": self.diagnostics,
        }


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _first_text(payload: dict[str, Any], keys: list[str]) -> str:
    values = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
        elif isinstance(value, dict):
            values.append(json.dumps(value, ensure_ascii=False))
    return normalize_text(" ".join(values))


def _explicit_number_references(text: str) -> list[str]:
    numbers: list[str] = []
    for pattern in EXPLICIT_REFERENCE_PATTERNS:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            if match not in numbers:
                numbers.append(match)
    return numbers


def classify_failure_event(row: dict[str, Any], *, detected_at: str | None = None) -> ProcurementFailureEvent:
    text = _first_text(
        row,
        [
            "failure_status_raw",
            "failure_reason",
            "status_raw",
            "status_normalized",
            "result_text",
            "protocol_text",
            "evidence_excerpt",
            "raw_text",
        ],
    ).lower()
    application_count = row.get("application_count")
    admitted_count = row.get("admitted_application_count")
    try:
        application_count = int(application_count) if application_count is not None else None
    except (TypeError, ValueError):
        application_count = None
    try:
        admitted_count = int(admitted_count) if admitted_count is not None else None
    except (TypeError, ValueError):
        admitted_count = None

    explicit_no_apps = any(token in text for token in ["не подано ни одной заявки", "заявки не поданы", "отсутствие заявок", "0 заявок", "ноль заявок"])
    explicit_all_rejected = any(token in text for token in ["все заявки отклонены", "всем участникам отказано", "все участники не допущены", "все заявки признаны несоответствующими", "all applications were rejected"])
    explicit_no_admitted = any(token in text for token in ["нет допущенных заявок", "допущено 0", "ни один участник не допущен"])
    cancelled = any(token in text for token in ["закупка отменена", "процедура отменена", "отменено", "procedure was cancelled", "procurement was cancelled"])
    unsuccessful = any(token in text for token in ["признана несостоявшейся", "закупка не состоялась", "процедура не состоялась", "несостоявшаяся"])
    contract_not_concluded = any(token in text for token in ["контракт не заключен", "договор не заключен", "контракт не заключён", "договор не заключён", "contract was not concluded", "contract not concluded"])

    failure_type = "UNKNOWN_FAILURE"
    if explicit_no_apps or application_count == 0:
        failure_type = "NO_APPLICATIONS"
    elif application_count == 1:
        failure_type = "SINGLE_APPLICATION"
    elif explicit_all_rejected:
        failure_type = "ALL_APPLICATIONS_REJECTED"
    elif explicit_no_admitted or (admitted_count == 0 and application_count and application_count > 0):
        failure_type = "NO_ADMITTED_APPLICATIONS"
    elif cancelled:
        failure_type = "PROCUREMENT_CANCELLED"
    elif contract_not_concluded:
        failure_type = "CONTRACT_NOT_CONCLUDED"
    elif unsuccessful:
        failure_type = "PROCEDURE_DECLARED_UNSUCCESSFUL"

    evidence_confidence = "HIGH" if failure_type in {"NO_APPLICATIONS", "ALL_APPLICATIONS_REJECTED", "NO_ADMITTED_APPLICATIONS", "SINGLE_APPLICATION"} else "MEDIUM" if failure_type != "UNKNOWN_FAILURE" else "LOW"
    return ProcurementFailureEvent(
        procurement_number=str(row.get("procurement_number", "")),
        law=str(row.get("law", "")),
        customer=str(row.get("customer", "")),
        title=str(row.get("title", "")),
        nmck=row.get("nmck"),
        procedure_type=str(row.get("procedure_type", "")),
        region=str(row.get("region", "")),
        failure_type=failure_type,
        failure_status_raw=str(row.get("failure_status_raw") or row.get("status_raw") or ""),
        failure_status_normalized=str(row.get("failure_status_normalized") or row.get("status_normalized") or ""),
        failure_reason=str(row.get("failure_reason", "")),
        application_count=application_count,
        admitted_application_count=admitted_count,
        single_application=application_count == 1,
        single_application_admitted=application_count == 1 and (admitted_count or 0) == 1,
        single_application_winner=bool(row.get("winner_name") and application_count == 1),
        contract_concluded=bool(row.get("contract_concluded")),
        contract_not_concluded=contract_not_concluded or bool(row.get("contract_not_concluded")),
        protocol_url=str(row.get("protocol_url", "")),
        result_url=str(row.get("result_url", "")),
        evidence_source=str(row.get("evidence_source") or row.get("protocol_url") or row.get("result_url") or ""),
        evidence_excerpt=str(row.get("evidence_excerpt") or row.get("failure_reason") or text[:300]),
        evidence_confidence=evidence_confidence,
        completed_at=str(row.get("completed_at") or row.get("updated_at") or ""),
        detected_at=detected_at or _now(),
    )


def temporal_score(previous_completed_at: str, current_published_at: str, config: RadarConfig) -> tuple[int, int | None, list[str]]:
    warnings: list[str] = []
    previous = parse_datetime(previous_completed_at)
    current = parse_datetime(current_published_at)
    if previous is None or current is None:
        return 0, None, ["missing temporal evidence"]
    days = (current - previous).days
    if days < 0:
        return 0, days, ["current publication is before previous failure"]
    if days <= config.opportunities.republication.strong_window_days:
        return 10, days, warnings
    if days <= config.opportunities.republication.maximum_days_between:
        return 6, days, warnings
    return 0, days, ["outside default republication window"]


def score_republication_relation(current: RadarCard, previous: ProcurementFailureEvent, config: RadarConfig) -> RepeatedProcurementLink:
    same_customer = bool(current.customer and previous.customer and current.customer.lower() == previous.customer.lower())
    current_terms = set(extract_functional_terms(f"{current.title} {current.raw_text}"))
    previous_terms = set(extract_functional_terms(previous.title))
    functional_overlap = current_terms & previous_terms
    current_tokens = {token for token in normalize_tokens(current.title) if len(token) > 2}
    previous_tokens = {token for token in normalize_tokens(previous.title) if len(token) > 2}
    title_overlap = current_tokens & previous_tokens
    explicit_refs = _explicit_number_references(f"{current.raw_text} {current.title}")

    same_customer_score = 30 if same_customer else 0
    fallback_functional_overlap = {token for token in (current_tokens & previous_tokens) if token in {"portal", "workflow", "api", "account", "development", "личный", "кабинет", "портал"}}
    functional_score = min(25, sum(5 for _ in functional_overlap) + len(fallback_functional_overlap) * 5)
    title_score = min(15, len(title_overlap) * 3)
    budget_score, budget_reason = budget_similarity(current.nmck, previous.nmck)
    procedure_score = 5 if current.procedure_type and current.procedure_type.lower() == previous.procedure_type.lower() else 0
    region_score = 5 if current.region and current.region.lower() == previous.region.lower() else 0
    time_score, days_between, warnings = temporal_score(previous.completed_at, current.published_at, config)
    explicit_score = 30 if previous.procurement_number in explicit_refs else 0
    relation_score = min(100, explicit_score + same_customer_score + functional_score + title_score + budget_score + procedure_score + region_score + time_score)

    evidence: list[str] = []
    if explicit_score:
        evidence.append("EXPLICIT_REFERENCE")
    if same_customer:
        evidence.append("SAME_CUSTOMER_TITLE")
    if functional_overlap or fallback_functional_overlap:
        evidence.append("SAME_CUSTOMER_FUNCTIONAL" if same_customer else "FUNCTIONAL")
    if budget_score:
        evidence.append(f"SAME_CUSTOMER_BUDGET: {budget_reason}" if same_customer else f"BUDGET: {budget_reason}")
    if time_score:
        evidence.append("TEMPORAL_SEQUENCE")

    if days_between is not None and days_between < 0:
        relation_type = "NOT_RELATED"
        confidence = "LOW"
        relation_score = min(relation_score, 49)
    elif explicit_score:
        relation_type = "EXPLICIT_REPUBLICATION"
        confidence = "HIGH"
        relation_score = max(relation_score, 85)
    elif relation_score >= config.opportunities.republication.strong_relation_score and same_customer and (functional_score or title_score):
        relation_type = "LIKELY_REPUBLICATION"
        confidence = "HIGH"
    elif relation_score >= config.opportunities.republication.minimum_relation_score and same_customer:
        relation_type = "SAME_CUSTOMER_SIMILAR_SUBJECT"
        confidence = "MEDIUM"
    elif relation_score >= 35:
        relation_type = "POSSIBLE_REPUBLICATION"
        confidence = "LOW"
    else:
        relation_type = "NOT_RELATED"
        confidence = "LOW"

    return RepeatedProcurementLink(
        current_procurement_number=current.procurement_number,
        previous_procurement_number=previous.procurement_number,
        relation_type=relation_type,
        relation_score=relation_score,
        similarity_score=relation_score,
        confidence=confidence,
        same_customer=same_customer,
        title_similarity=title_score,
        functional_similarity=functional_score,
        budget_similarity=budget_score,
        procedure_similarity=procedure_score,
        region_similarity=region_score,
        previous_failure_type=previous.failure_type,
        previous_completed_at=previous.completed_at,
        current_published_at=current.published_at,
        days_between=days_between,
        evidence=evidence,
        warnings=warnings,
    )


def failure_competition_signal(failure: ProcurementFailureEvent) -> tuple[int, list[str], list[str]]:
    positives: list[str] = []
    risks: list[str] = []
    if failure.failure_type == "NO_APPLICATIONS":
        positives.append("previous procurement had explicit no-application evidence")
        return 20, positives, risks
    if failure.failure_type == "SINGLE_APPLICATION":
        positives.append("previous procurement had only one application")
        return 12, positives, risks
    if failure.failure_type in {"ALL_APPLICATIONS_REJECTED", "NO_ADMITTED_APPLICATIONS"}:
        positives.append("previous procurement had no admitted applications")
        risks.append("all applications rejected may indicate difficult requirements")
        return 8, positives, risks
    if failure.failure_type == "PROCUREMENT_CANCELLED":
        risks.append("previous procurement was cancelled; no weak-competition benefit")
        return 0, positives, risks
    if failure.failure_type == "CONTRACT_NOT_CONCLUDED":
        risks.append("contract not concluded is not low-competition evidence by itself")
        return 0, positives, risks
    return 0, positives, ["failure evidence is insufficient for competition benefit"]


def build_opportunity(
    current: RadarCard,
    assessment: RadarAssessment,
    failure: ProcurementFailureEvent,
    link: RepeatedProcurementLink,
    config: RadarConfig,
) -> NoCompetitionOpportunity:
    positives: list[str] = []
    risks: list[str] = []
    warnings = list(link.warnings)
    technical_fit = min(30, max(0, int(round((assessment.total_score or 0) * 0.3))))
    if assessment.hard_reject_reasons:
        technical_fit = 0
        risks.append("technical hard reject blocks opportunity promotion")
    open_score = 15 if assessment.eligibility_status == EligibilityStatus.OPEN else 0
    if assessment.eligibility_status != EligibilityStatus.OPEN:
        warnings.append("current procurement is not verified open")
    relation_score = 20 if link.confidence == "HIGH" else 14 if link.confidence == "MEDIUM" else 6 if link.relation_type != "NOT_RELATED" else 0
    competition_score, competition_positives, competition_risks = failure_competition_signal(failure)
    positives.extend(competition_positives)
    risks.extend(competition_risks)
    budget_score = 10 if current.nmck and config.filters.preferred_nmck_min <= current.nmck <= config.filters.preferred_nmck_max else 5 if current.nmck else 0
    deadline_score = 5 if (assessment.days_to_deadline or 0) >= config.filters.statuses.count("never") + 5 else 0
    score = technical_fit + open_score + relation_score + competition_score + budget_score + deadline_score
    if assessment.days_to_deadline is not None and assessment.days_to_deadline < config.enrichment.minimum_days_to_deadline:
        score -= 15
        risks.append("deadline is extremely short")
    if link.relation_type == "NOT_RELATED":
        score -= 20
        warnings.append("unclear republication relation")
    if assessment.hard_reject_reasons:
        score = min(score, config.opportunities.scoring.medium_threshold - 1)
    if assessment.eligibility_status != EligibilityStatus.OPEN:
        score = min(score, config.opportunities.scoring.medium_threshold - 1)
    score = max(0, min(100, score))
    if score >= config.opportunities.scoring.high_threshold and not assessment.hard_reject_reasons and assessment.eligibility_status == EligibilityStatus.OPEN:
        level = "HIGH"
    elif score >= config.opportunities.scoring.medium_threshold:
        level = "MEDIUM"
    elif score >= config.opportunities.scoring.low_threshold:
        level = "LOW"
    elif score > 0:
        level = "REVIEW"
    else:
        level = "INSUFFICIENT_DATA"
    positives.append(f"republication relation {link.confidence} ({link.relation_score})")
    positives.append(f"technical fit component {technical_fit}/30")
    return NoCompetitionOpportunity(
        current_procurement_number=current.procurement_number,
        previous_procurement_number=failure.procurement_number,
        current_title=current.title,
        current_customer=current.customer,
        current_nmck=current.nmck,
        current_status=current.status_normalized,
        current_deadline=current.application_deadline,
        current_source_url=current.source_url,
        previous_failure_type=failure.failure_type,
        previous_application_count=failure.application_count,
        previous_nmck=failure.nmck,
        republication_confidence=link.confidence,
        republication_score=link.relation_score,
        preliminary_score=assessment.total_score,
        history_adjusted_score=assessment.history_adjusted_score or assessment.total_score,
        technical_fit_signal=technical_fit,
        competition_opportunity_signal=competition_score,
        opportunity_score=score,
        opportunity_level=level,
        positive_signals=positives,
        risks=risks,
        warnings=warnings,
    )


def detect_opportunity_transitions(previous: NoCompetitionOpportunity | None, current: NoCompetitionOpportunity, detected_at: str | None = None) -> list[OpportunityTransition]:
    detected_at = detected_at or _now()
    if previous is None:
        return [OpportunityTransition(current.current_procurement_number, "NEW_OPPORTUNITY", "", current.opportunity_level, detected_at)]
    transitions: list[OpportunityTransition] = []
    checks = [
        ("DEADLINE_CHANGED", previous.current_deadline, current.current_deadline),
        ("NMCK_CHANGED", str(previous.current_nmck), str(current.current_nmck)),
        ("RELATION_CONFIDENCE_CHANGED", previous.republication_confidence, current.republication_confidence),
        ("OPPORTUNITY_SCORE_CHANGED", str(previous.opportunity_score), str(current.opportunity_score)),
    ]
    if previous.current_status != current.current_status and current.current_status != "APPLICATION_SUBMISSION":
        transitions.append(OpportunityTransition(current.current_procurement_number, "OPEN_TO_CLOSED", previous.current_status, current.current_status, detected_at))
    for transition_type, old, new in checks:
        if old != new:
            transitions.append(OpportunityTransition(current.current_procurement_number, transition_type, old, new, detected_at))
    if transitions:
        transitions.insert(0, OpportunityTransition(current.current_procurement_number, "OPPORTUNITY_UPDATED", previous.opportunity_level, current.opportunity_level, detected_at))
    return transitions


def load_failure_events(path: str | Path | None) -> list[ProcurementFailureEvent]:
    if not path:
        return []
    root = Path(path)
    candidates = [root / "failure_events.json"] if root.is_dir() else [root]
    for candidate in candidates:
        if candidate.exists():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            rows = data.get("failure_events", data) if isinstance(data, dict) else data
            return [classify_failure_event(row) for row in rows if isinstance(row, dict)]
    return []


def assess_failed_opportunities(
    cards: list[RadarCard],
    assessments: list[RadarAssessment],
    config: RadarConfig,
    *,
    failure_events: list[ProcurementFailureEvent] | None = None,
    offline_failure_input: str | Path | None = None,
    previous_opportunities: dict[str, NoCompetitionOpportunity] | None = None,
) -> OpportunityAssessmentResult:
    failure_events = failure_events if failure_events is not None else load_failure_events(offline_failure_input)
    assessment_map = {item.procurement_number: item for item in assessments}
    links: list[RepeatedProcurementLink] = []
    opportunities: list[NoCompetitionOpportunity] = []
    transitions: list[OpportunityTransition] = []
    for card in cards:
        assessment = assessment_map.get(card.procurement_number)
        if assessment is None:
            continue
        for failure in failure_events[: config.opportunities.failure_history.maximum_candidates]:
            link = score_republication_relation(card, failure, config)
            links.append(link)
            if link.relation_type == "NOT_RELATED":
                continue
            if not link.same_customer and "EXPLICIT_REFERENCE" not in link.evidence:
                continue
            competition_score, _positives, _risks = failure_competition_signal(failure)
            if competition_score <= 0:
                continue
            opportunity = build_opportunity(card, assessment, failure, link, config)
            if opportunity.opportunity_score < config.opportunities.scoring.minimum_opportunity_score:
                continue
            opportunities.append(opportunity)
            previous = (previous_opportunities or {}).get(opportunity.current_procurement_number)
            transitions.extend(detect_opportunity_transitions(previous, opportunity))
    opportunities.sort(key=lambda item: item.opportunity_score, reverse=True)
    return OpportunityAssessmentResult(
        failure_events=failure_events,
        republication_links=links,
        opportunities=opportunities,
        transitions=transitions,
        diagnostics={
            "opportunity_intelligence_version": opportunity_intelligence_version,
            "failure_events_loaded": len(failure_events),
            "republication_links_scored": len(links),
            "opportunities_produced": len(opportunities),
        },
    )
