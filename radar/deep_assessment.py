from __future__ import annotations

from typing import Any

from radar.config import RadarConfig
from radar.models import DeepAssessment, EnrichmentStatus, RadarAssessment, RadarDecision


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(card: dict[str, Any], *names: str) -> str:
    for name in names:
        value = card.get(name)
        if value:
            return str(value)
    return "missing"


def commodity_confirmation(card: dict[str, Any]) -> tuple[bool, list[str]]:
    haystack = " ".join(str(card.get(field, "")) for field in ["procurement_name", "short_scope", "functional_modules", "design_requirements"]).lower()
    reasons = []
    checks = {
        "simple informational website": ["информационный сайт", "новости", "контакты", "галерея"],
        "constructor or tilda allowed": ["tilda", "конструктор"],
        "no authentication": ["без авторизации", "без личного кабинета"],
        "no integrations": ["без интеграций"],
    }
    for reason, terms in checks.items():
        if any(term in haystack for term in terms):
            reasons.append(reason)
    return bool(reasons), reasons


def map_deep_assessment(
    analysis: dict[str, Any],
    preliminary: RadarAssessment,
    config: RadarConfig,
    status: EnrichmentStatus = EnrichmentStatus.COMPLETE,
) -> DeepAssessment:
    reliability = str(analysis.get("analysis_reliability") or analysis.get("document_reliability") or "INSUFFICIENT")
    technical_status = _status(analysis, "technical_specification_status")
    contract_status = _status(analysis, "contract_status")
    application_status = _status(analysis, "application_requirements_status")
    nmck_status = _status(analysis, "nmck_status")
    protocol_status = _status(analysis, "final_protocol_status", "protocol_status")
    evidence = analysis.get("evidence") or []
    commodity, commodity_reasons = commodity_confirmation(analysis)

    deep = DeepAssessment(
        procurement_number=preliminary.procurement_number,
        preliminary_score=preliminary.total_score,
        preliminary_decision=preliminary.radar_decision,
        document_analysis_version=str(analysis.get("analysis_version") or analysis.get("document_analysis_version") or ""),
        document_completeness_score=_to_int(analysis.get("data_completeness_score") or analysis.get("document_completeness_score")),
        document_reliability=reliability,
        technical_participation_verdict=str(analysis.get("technical_participation_verdict") or "INSUFFICIENT_TECHNICAL_DATA"),
        market_result_status=str(analysis.get("market_result_status") or ""),
        overall_recommendation=str(analysis.get("overall_recommendation") or "INSUFFICIENT_DATA"),
        technical_complexity_score=_to_int(analysis.get("technical_complexity_score")),
        organizational_complexity_score=_to_int(analysis.get("organizational_complexity_score")),
        legal_risk_score=_to_int(analysis.get("legal_risk_score")),
        financial_risk_score=_to_int(analysis.get("financial_risk_score")),
        ai_fit_score=_to_int(analysis.get("ai_fit_score")),
        solo_developer_fit_score=_to_int(analysis.get("solo_developer_fit_score")),
        estimated_development_hours_min=_to_int(analysis.get("estimated_hours_min")) or None,
        estimated_development_hours_max=_to_int(analysis.get("estimated_hours_max")) or None,
        estimated_support_hours=_to_int(analysis.get("estimated_support_hours")) or None,
        estimated_infrastructure_costs=_to_float(analysis.get("estimated_direct_costs_max")),
        recommended_min_price=_to_float(analysis.get("recommended_min_price")),
        recommended_comfort_price=_to_float(analysis.get("recommended_comfort_price")),
        nmck_viability=str(analysis.get("nmck_viability") or ""),
        price_margin_vs_min=_to_float(analysis.get("price_margin_vs_min")),
        price_margin_percent=_to_float(analysis.get("price_margin_percent")),
        specific_platform=str(analysis.get("specific_platform") or ""),
        specific_platform_required=bool(analysis.get("platform_expertise_required") or analysis.get("specific_platform_required")),
        required_integrations=_as_list(analysis.get("integrations") or analysis.get("external_systems")),
        required_licenses=_as_list(analysis.get("required_licenses") or ("license required" if analysis.get("licenses_required") else "")),
        staff_requirements=str(analysis.get("staff_requirements") or ""),
        technical_specification_status=technical_status,
        contract_status=contract_status,
        application_requirements_status=application_status,
        nmck_status=nmck_status,
        protocol_status=protocol_status,
        key_positive_factors=_as_list(analysis.get("key_positive_factors") or analysis.get("functional_modules")),
        key_risks=_as_list(analysis.get("key_risks")),
        blocking_factors=_as_list(analysis.get("blocking_factors")),
        participation_conditions=_as_list(analysis.get("participation_conditions")),
        evidence_count=len(evidence),
        high_confidence_evidence_count=sum(1 for item in evidence if str(item.get("confidence", "")).lower() == "high"),
        manual_review_required=bool(analysis.get("manual_review_required", True)),
        commodity_risk_confirmed=commodity,
        commodity_risk_reasons=commodity_reasons,
        enrichment_status=status,
    )
    deep.unanswered_questions = build_questions(deep)
    deep.deep_score = calculate_deep_score(deep)
    deep.final_radar_decision = decide_final(deep, config)
    deep.final_decision_reasons = final_reasons(deep)
    return deep


def build_questions(deep: DeepAssessment) -> list[str]:
    questions: list[str] = []
    if deep.application_requirements_status not in {"read", "partial"}:
        questions.append("Are participant experience, licenses, and application requirements confirmed?")
    if not deep.required_integrations and deep.technical_specification_status in {"read", "partial"}:
        questions.append("Are integrations documented or explicitly absent?")
    if not deep.staff_requirements:
        questions.append("Is mandatory staffing or certification required?")
    if deep.contract_status not in {"read", "partial"}:
        questions.append("Are payment, acceptance, rights transfer, and support terms acceptable?")
    if deep.protocol_status == "missing":
        questions.append("Protocol is unavailable; market result fields remain unconfirmed.")
    if deep.specific_platform_required:
        questions.append("Is the specific platform mandatory and available to the developer?")
    return questions[:8]


def calculate_deep_score(deep: DeepAssessment) -> int:
    technical_fit = 0
    if deep.technical_participation_verdict in {"TAKE_NOW", "TAKE_WITH_CONDITIONS"}:
        technical_fit = 25
    elif deep.technical_participation_verdict in {"PREPARE", "REVIEW"}:
        technical_fit = 15

    economic = {"STRONG": 25, "ACCEPTABLE": 20, "BORDERLINE": 10, "WEAK": 4}.get(deep.nmck_viability, 8)
    solo_ai = min(15, round((deep.solo_developer_fit_score + deep.ai_fit_score) / 20 * 15))
    deadline = 10
    reliability = {"HIGH": 10, "MEDIUM": 7, "LOW": 3, "INSUFFICIENT": 0}.get(deep.document_reliability, 0)
    risk = max(0, 15 - deep.legal_risk_score - deep.financial_risk_score // 2)
    blockers = len(deep.blocking_factors) * 35
    if deep.specific_platform_required and deep.specific_platform:
        blockers += 25
    if deep.technical_specification_status == "missing" or deep.contract_status == "missing":
        blockers += 40
    if deep.commodity_risk_confirmed:
        blockers += 15
    return max(0, min(100, technical_fit + economic + solo_ai + deadline + reliability + risk - blockers))


def decide_final(deep: DeepAssessment, config: RadarConfig) -> RadarDecision:
    if deep.technical_specification_status == "missing" or deep.contract_status == "missing":
        return RadarDecision.INSUFFICIENT_DATA
    if deep.technical_participation_verdict == "DO_NOT_TAKE" or deep.blocking_factors:
        return RadarDecision.REJECT
    if deep.nmck_viability in {"WEAK", "UNACCEPTABLE"}:
        return RadarDecision.REJECT if deep.deep_score < 55 else RadarDecision.REVIEW
    if deep.specific_platform_required and deep.specific_platform:
        return RadarDecision.REJECT if deep.deep_score < 60 else RadarDecision.REVIEW
    if (
        deep.deep_score >= 75
        and deep.technical_participation_verdict in {"TAKE_NOW", "TAKE_WITH_CONDITIONS"}
        and deep.document_reliability in {"HIGH", "MEDIUM"}
        and deep.nmck_viability in {"STRONG", "ACCEPTABLE"}
        and deep.solo_developer_fit_score >= config.enrichment.solo_fit_threshold
        and deep.ai_fit_score >= config.enrichment.ai_fit_threshold
    ):
        return RadarDecision.PRIORITY
    if deep.deep_score >= 55:
        return RadarDecision.REVIEW
    if deep.deep_score >= 35:
        return RadarDecision.WATCH
    return RadarDecision.REJECT


def final_reasons(deep: DeepAssessment) -> list[str]:
    reasons = [
        f"technical verdict: {deep.technical_participation_verdict}",
        f"document reliability: {deep.document_reliability}",
        f"nmck viability: {deep.nmck_viability}",
    ]
    if deep.blocking_factors:
        reasons.append("blocking factors: " + "; ".join(deep.blocking_factors))
    if deep.commodity_risk_confirmed:
        reasons.append("commodity risk confirmed: " + "; ".join(deep.commodity_risk_reasons))
    if deep.unanswered_questions:
        reasons.append("manual review questions remain")
    return reasons

