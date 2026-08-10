from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from radar.analog_search import (
    extract_category,
    extract_functional_terms,
    extract_profile,
    generate_historical_queries,
    normalize_text,
    normalize_tokens,
    term_importance,
)
from radar.competition_metrics import avg, calculate_competition_metrics, med, percentile
from radar.config import RadarConfig
from radar.models import (
    CompetitionMetrics,
    CustomerHistoryProfile,
    DumpingRiskAssessment,
    HistoricalAnalog,
    HistoricalSearchQuery,
    HistoryAdjustedAssessment,
    RadarAssessment,
    RadarCard,
    RadarDecision,
    RepeatedProcurementLink,
    SupplierHistoryProfile,
)


@dataclass
class HistoricalAssessmentBundle:
    procurement_number: str
    historical_search: list[HistoricalSearchQuery] = field(default_factory=list)
    historical_analogs: list[HistoricalAnalog] = field(default_factory=list)
    competition_metrics: CompetitionMetrics = field(default_factory=CompetitionMetrics)
    customer_history: CustomerHistoryProfile | None = None
    supplier_history: list[SupplierHistoryProfile] = field(default_factory=list)
    dumping_risk_assessment: DumpingRiskAssessment = field(default_factory=DumpingRiskAssessment)
    history_adjusted_assessment: HistoryAdjustedAssessment | None = None
    repeated_procurements: list[RepeatedProcurementLink] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "procurement_number": self.procurement_number,
            "historical_search": [item.to_dict() for item in self.historical_search],
            "historical_analogs": [item.to_dict() for item in self.historical_analogs],
            "competition_metrics": self.competition_metrics.to_dict(),
            "customer_history": self.customer_history.to_dict() if self.customer_history else None,
            "supplier_history": [item.to_dict() for item in self.supplier_history],
            "dumping_risk_assessment": self.dumping_risk_assessment.to_dict(),
            "history_adjusted_assessment": self.history_adjusted_assessment.to_dict() if self.history_adjusted_assessment else None,
            "repeated_procurements": [item.to_dict() for item in self.repeated_procurements],
            "diagnostics": self.diagnostics,
        }


LOW_VALUE_TOKENS = {"разработка", "создание", "оказание", "услуг", "услуги"}


def budget_similarity(source: float | None, analog: float | None) -> tuple[int, str]:
    if source is None or analog is None or source <= 0 or analog <= 0:
        return 0, "missing budget"
    ratio = max(source, analog) / max(1.0, min(source, analog))
    if ratio <= 1.2:
        return 10, "nmck within 20%"
    if ratio <= 1.5:
        return 7, "nmck within 50%"
    if ratio <= 5:
        return 3, "same order of magnitude"
    return 0, "nmck differs by more than 5x"


def category_compatibility(source_category: str, candidate_category: str) -> str:
    if not source_category or not candidate_category:
        return "UNKNOWN"
    if source_category == candidate_category:
        return "STRONG_CATEGORY_MATCH"
    compatible_pairs = {
        ("BUSINESS_PORTAL", "PORTAL"),
        ("PORTAL", "WEBSITE"),
        ("PORTAL", "INFORMATION_SYSTEM"),
        ("INFORMATION_SYSTEM", "REGISTRY_SYSTEM"),
        ("WEBSITE", "PORTAL"),
        ("BUSINESS_PORTAL", "WEBSITE"),
        ("BUSINESS_PORTAL", "INFORMATION_SYSTEM"),
    }
    if (source_category, candidate_category) in compatible_pairs:
        return "CATEGORY_MATCH"
    if source_category in {"PORTAL", "BUSINESS_PORTAL"} and candidate_category in {"WEBSITE", "INFORMATION_SYSTEM"}:
        return "CROSS_CATEGORY_POSSIBLE"
    if candidate_category in {"LICENSE_ONLY", "HARDWARE"}:
        return "CATEGORY_MISMATCH"
    return "CATEGORY_MISMATCH"


def _title_token_overlap(source: RadarCard, analog: HistoricalAnalog) -> set[str]:
    source_tokens = set(normalize_tokens(source.title))
    analog_tokens = set(normalize_tokens(analog.title))
    return {token for token in (source_tokens & analog_tokens) if token not in LOW_VALUE_TOKENS}


def score_similarity(source: RadarCard, analog: HistoricalAnalog, profile_terms: list[str] | None = None) -> HistoricalAnalog:
    del profile_terms
    source_terms = set(extract_functional_terms(f"{source.title} {normalize_text(source.raw_text)[:1500]}"))
    candidate_terms = set(extract_functional_terms(analog.title))
    token_overlap = _title_token_overlap(source, analog)
    functional_overlap = source_terms & candidate_terms

    analog.source_normalized_tokens = sorted(set(normalize_tokens(source.title)))
    analog.candidate_normalized_tokens = sorted(set(normalize_tokens(analog.title)))
    analog.source_functional_terms = sorted(source_terms)
    analog.candidate_functional_terms = sorted(candidate_terms)
    analog.shared_title_tokens = sorted(token_overlap)
    analog.shared_functional_terms = sorted(functional_overlap)
    analog.source_category = extract_category(source.title)
    analog.candidate_category = extract_category(analog.title)
    analog.source_profile = extract_profile(source.title)
    analog.candidate_profile = extract_profile(analog.title)
    analog.category_compatibility = category_compatibility(analog.source_category, analog.candidate_category)
    analog.missing_fields = [
        name
        for name, value in [("title", analog.title), ("customer", analog.customer), ("nmck", analog.nmck), ("procedure_type", analog.procedure_type)]
        if value in {"", None}
    ]

    analog.functional_similarity_score = min(30, sum(term_importance(term) for term in functional_overlap))
    analog.title_similarity_score = min(15, len(token_overlap) * 3)
    analog.profile_similarity_score = 4 if analog.source_profile == analog.candidate_profile and analog.source_profile != "other" else 0
    if analog.category_compatibility == "STRONG_CATEGORY_MATCH":
        analog.profile_similarity_score += 4
    elif analog.category_compatibility == "CATEGORY_MATCH":
        analog.profile_similarity_score += 3
    elif analog.category_compatibility == "CROSS_CATEGORY_POSSIBLE":
        analog.profile_similarity_score += 2
    analog.profile_similarity_score = min(12, analog.profile_similarity_score)
    analog.customer_similarity_score = 15 if source.customer and source.customer.lower() == analog.customer.lower() else 0
    analog.procedure_similarity_score = 10 if source.procedure_type and source.procedure_type.lower() == analog.procedure_type.lower() else 0
    analog.budget_similarity_score, budget_reason = budget_similarity(source.nmck, analog.nmck)
    analog.region_similarity_score = 5 if source.region and source.region.lower() == analog.region.lower() else 0
    analog.similarity_score = (
        analog.functional_similarity_score
        + analog.title_similarity_score
        + analog.profile_similarity_score
        + analog.customer_similarity_score
        + analog.procedure_similarity_score
        + analog.budget_similarity_score
        + analog.region_similarity_score
    )

    if functional_overlap:
        analog.similarity_reasons.append("functional overlap: " + ", ".join(sorted(functional_overlap)))
    if token_overlap:
        analog.similarity_reasons.append("title token overlap: " + ", ".join(sorted(token_overlap)[:6]))
    analog.similarity_reasons.append(budget_reason)
    if analog.category_compatibility == "CATEGORY_MISMATCH":
        analog.mismatch_reasons.append("category mismatch")
        analog.exclusion_reason = "CATEGORY_MISMATCH"
    elif not functional_overlap and not token_overlap:
        analog.mismatch_reasons.append("no meaningful functional/title overlap")
    return analog


def select_analogs(source: RadarCard, analogs: list[HistoricalAnalog], config: RadarConfig, profile_terms: list[str] | None = None) -> list[HistoricalAnalog]:
    scored = [score_similarity(source, analog, profile_terms) for analog in analogs]
    normal_threshold = config.historical.similarity.minimum_score
    hard_floor = config.historical.similarity.hard_floor_score
    relaxed_threshold = max(hard_floor, normal_threshold - config.historical.similarity.relaxed_threshold_delta)
    selected: list[HistoricalAnalog] = []
    for analog in scored:
        analog.threshold_required = normal_threshold
        analog.hard_floor_passed = analog.similarity_score >= hard_floor
        if analog.evidence:
            query_value = analog.evidence[0].get("query", [""])
            if isinstance(query_value, list):
                analog.source_query = query_value[0] if query_value else ""
            else:
                analog.source_query = str(query_value or "")
        else:
            analog.source_query = ""

        if analog.analog_procurement_number == source.procurement_number:
            analog.exclusion_reason = "SELF_REFERENCE_FORBIDDEN"
            analog.threshold_gap = normal_threshold - analog.similarity_score
            continue
        if analog.category_compatibility == "CATEGORY_MISMATCH":
            analog.threshold_gap = normal_threshold - analog.similarity_score
            continue
        if analog.similarity_score >= normal_threshold:
            analog.selection_mode = "NORMAL"
            analog.selection_reason = "score meets normal threshold"
            analog.threshold_gap = 0
            selected.append(analog)
            continue
        if analog.similarity_score >= relaxed_threshold and analog.category_compatibility in {"STRONG_CATEGORY_MATCH", "CATEGORY_MATCH", "CROSS_CATEGORY_POSSIBLE"}:
            analog.selection_mode = "RELAXED_THRESHOLD"
            analog.selection_reason = "compatible category with relaxed threshold"
            analog.threshold_required = relaxed_threshold
            analog.threshold_gap = 0
            analog.mismatch_reasons.append("RELAXED_THRESHOLD")
            selected.append(analog)
            continue
        if source.customer and analog.customer.lower() == source.customer.lower() and analog.similarity_score >= hard_floor:
            analog.selection_mode = "SAME_CUSTOMER_FALLBACK"
            analog.selection_reason = "same customer fallback"
            analog.threshold_required = hard_floor
            analog.threshold_gap = 0
            analog.mismatch_reasons.append("SAME_CUSTOMER_FALLBACK")
            selected.append(analog)
            continue
        analog.threshold_gap = analog.threshold_required - analog.similarity_score
        if not analog.exclusion_reason:
            analog.exclusion_reason = "BELOW_THRESHOLD"

    selected.sort(key=lambda item: item.similarity_score, reverse=True)
    return selected[: config.historical.search.maximum_selected_analogs]


def _load_history_rows(data: Any, procurement_number: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    if procurement_number in data and isinstance(data[procurement_number], list):
        return [item for item in data[procurement_number] if isinstance(item, dict)]
    if "analogs" in data and isinstance(data["analogs"], list):
        return [item for item in data["analogs"] if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []
    for value in data.values():
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def load_offline_history(path: str | Path, procurement_number: str) -> list[HistoricalAnalog]:
    root = Path(path)
    candidate_paths = [root / f"{procurement_number}.json", root / "history.json"]
    for candidate in candidate_paths:
        if candidate.exists():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            rows = _load_history_rows(data, procurement_number)
            return [HistoricalAnalog(**row) for row in rows]
    return []


def assess_dumping_risk(metrics: CompetitionMetrics, config: RadarConfig) -> DumpingRiskAssessment:
    score = 0
    positives: list[str] = []
    negatives: list[str] = []
    median_participants = metrics.median_participants or 0
    p75_participants = metrics.participants_p75 or 0
    median_reduction = metrics.median_reduction_percent or 0
    p75_reduction = metrics.reduction_p75 or 0

    if median_participants >= config.historical.dumping.high_participant_threshold:
        score += 20
        negatives.append("historically high participant count")
    if p75_participants >= config.historical.dumping.extreme_participant_threshold:
        score += 20
        negatives.append("upper quartile participant count is extreme")
    if median_reduction >= config.historical.dumping.high_reduction_threshold:
        score += 25
        negatives.append("median reduction is high")
    if p75_reduction >= config.historical.dumping.extreme_reduction_threshold:
        score += 25
        negatives.append("upper quartile reduction is extreme")
    if metrics.extreme_reduction_rate >= 0.3:
        score += 20
        negatives.append("frequent extreme reductions")
    if metrics.repeated_winner_share >= 0.5:
        score += 10
        negatives.append("repeated winner concentration")
    if metrics.no_application_rate >= 0.3:
        positives.append("historical no-application opportunity signal")
    score = min(100, score)
    if metrics.confidence == "INSUFFICIENT":
        level = "UNKNOWN"
    elif score >= 75:
        level = "EXTREME"
    elif score >= 55:
        level = "HIGH"
    elif score >= 30:
        level = "MODERATE"
    else:
        level = "LOW"
    return DumpingRiskAssessment(
        risk_level=level,
        risk_score=score,
        confidence=metrics.confidence,
        sample_size=max(metrics.participant_sample_size, metrics.reduction_sample_size, metrics.winner_sample_size, metrics.complete_result_sample_size),
        strong_analog_sample_size=metrics.strong_analog_count,
        competition_level="HIGH" if median_participants >= 10 else "MODERATE" if median_participants >= 4 else "LOW",
        expected_competition_band=f"median participants {median_participants}",
        historical_reduction_band=f"median reduction {median_reduction}%",
        high_participant_risk=median_participants >= config.historical.dumping.high_participant_threshold,
        extreme_reduction_risk=p75_reduction >= config.historical.dumping.extreme_reduction_threshold,
        commodity_market_risk=median_reduction >= config.historical.dumping.commodity_risk_reduction_threshold and median_participants >= config.historical.dumping.commodity_risk_participant_threshold,
        no_application_opportunity=metrics.no_application_rate >= 0.3,
        customer_specific_risk=False,
        supplier_concentration_signal=metrics.repeated_winner_share >= 0.5,
        participant_metric_confidence=metrics.participant_metric_confidence,
        reduction_metric_confidence=metrics.reduction_metric_confidence,
        winner_metric_confidence=metrics.winner_metric_confidence,
        positive_signals=positives,
        negative_signals=negatives,
        warnings=list(metrics.warnings),
        evidence=[],
    )


def history_adjustment(preliminary: RadarAssessment, risk: DumpingRiskAssessment) -> HistoryAdjustedAssessment:
    adjustment = 0
    reasons: list[str] = []
    if risk.risk_level == "LOW":
        adjustment = 5
        reasons.append("low historical competition risk")
    elif risk.risk_level == "MODERATE":
        adjustment = -5
        reasons.append("moderate historical competition risk")
    elif risk.risk_level == "HIGH":
        adjustment = -20
        reasons.append("high historical competition risk")
    elif risk.risk_level == "EXTREME":
        adjustment = -35
        reasons.append("extreme commodity/dumping pattern")
    elif risk.risk_level == "UNKNOWN":
        reasons.append("historical sample is insufficient")
    if risk.no_application_opportunity:
        adjustment += 10
        reasons.append("no-application opportunity signal")
    adjusted_score = max(0, min(100, preliminary.total_score + adjustment))
    if preliminary.hard_reject_reasons:
        decision = RadarDecision.REJECT
        reasons.append("history cannot override preliminary hard reject")
    elif adjusted_score >= 75:
        decision = RadarDecision.PRIORITY
    elif adjusted_score >= 55:
        decision = RadarDecision.REVIEW
    elif adjusted_score >= 35:
        decision = RadarDecision.WATCH
    else:
        decision = RadarDecision.REJECT
    return HistoryAdjustedAssessment(
        procurement_number=preliminary.procurement_number,
        preliminary_score=preliminary.total_score,
        historical_adjustment=adjustment,
        history_adjusted_score=adjusted_score,
        history_adjusted_decision=decision,
        historical_adjustment_reasons=reasons,
    )


def build_customer_history(customer: str, analogs: list[HistoricalAnalog], metrics: CompetitionMetrics, config: RadarConfig) -> CustomerHistoryProfile:
    customer_name = (customer or "").strip().lower()
    customer_analogs = [analog for analog in analogs if not customer_name or analog.customer.lower() == customer_name]
    nmck_values = [analog.nmck for analog in customer_analogs if analog.nmck is not None]
    contract_values = [analog.contract_price for analog in customer_analogs if analog.contract_price is not None]
    participant_values = [analog.participant_count for analog in customer_analogs if analog.participant_count is not None]
    reduction_values = [analog.reduction_percent for analog in customer_analogs if analog.reduction_percent is not None]
    winners = [analog.winner_name for analog in customer_analogs if analog.winner_name]
    winner_counts = {name: winners.count(name) for name in sorted(set(winners))}
    return CustomerHistoryProfile(
        normalized_customer_name=customer_name,
        customer_identifiers=[],
        total_completed_procurements=sum(1 for analog in customer_analogs if analog.result_data_status == "COMPLETE"),
        total_failed_procurements=sum(1 for analog in customer_analogs if analog.failed_procurement),
        total_cancelled_procurements=sum(1 for analog in customer_analogs if analog.result_data_status == "CANCELLED"),
        procurements_with_result_data=sum(1 for analog in customer_analogs if analog.result_data_status in {"COMPLETE", "PARTIAL"}),
        median_nmck=med(nmck_values),
        median_contract_price=med(contract_values),
        median_reduction_percent=med(reduction_values),
        average_reduction_percent=avg(reduction_values),
        reduction_percent_p25=percentile(reduction_values, 0.25),
        reduction_percent_p75=percentile(reduction_values, 0.75),
        median_participants=med(participant_values),
        average_participants=avg(participant_values),
        maximum_participants=max(participant_values) if participant_values else None,
        no_application_rate=metrics.no_application_rate,
        all_rejected_rate=metrics.all_rejected_rate,
        cancellation_rate=metrics.cancellation_rate,
        repeated_winner_share=metrics.repeated_winner_share,
        top_winners=[{"winner": name, "wins": count} for name, count in sorted(winner_counts.items(), key=lambda item: item[1], reverse=True)[:5]],
        commodity_procurement_share=round(sum(1 for analog in customer_analogs if extract_category(analog.title) in {"PORTAL", "WEBSITE", "BUSINESS_PORTAL"}) / len(customer_analogs), 3) if customer_analogs else 0,
        high_dumping_procurement_share=round(sum(1 for analog in customer_analogs if (analog.reduction_percent or 0) >= config.historical.dumping.high_reduction_threshold) / len(customer_analogs), 3) if customer_analogs else 0,
        history_confidence=metrics.confidence,
        evidence_count=len(customer_analogs),
        last_updated_at="",
    )


def build_supplier_history(analogs: list[HistoricalAnalog], config: RadarConfig) -> list[SupplierHistoryProfile]:
    grouped: dict[str, list[HistoricalAnalog]] = {}
    for analog in analogs:
        if analog.winner_name:
            grouped.setdefault(analog.winner_name, []).append(analog)
    profiles: list[SupplierHistoryProfile] = []
    for supplier, rows in list(grouped.items())[: config.historical.supplier_history.maximum_suppliers_per_procurement]:
        reductions = [item.reduction_percent for item in rows if item.reduction_percent is not None]
        profiles.append(
            SupplierHistoryProfile(
                supplier_name=supplier,
                supplier_identifier=rows[0].winner_identifier if rows else "",
                known_wins=len(rows),
                customers=sorted({item.customer for item in rows if item.customer}),
                categories=sorted({item.procedure_type for item in rows if item.procedure_type}),
                median_reduction_percent=statistics.median(reductions) if reductions else None,
                average_reduction_percent=round(sum(reductions) / len(reductions), 2) if reductions else None,
                extreme_reduction_count=sum(1 for value in reductions if value >= config.historical.dumping.extreme_reduction_threshold),
                repeat_customer_count=max(0, len(rows) - len({item.customer for item in rows if item.customer})),
                confidence="MEDIUM" if len(rows) >= 3 else "LOW",
                evidence=[{"procurement_number": item.analog_procurement_number, "customer": item.customer} for item in rows[:5]],
            )
        )
    return profiles


def detect_repeated_procurements(source: RadarCard, analogs: list[HistoricalAnalog]) -> list[RepeatedProcurementLink]:
    links: list[RepeatedProcurementLink] = []
    source_customer = (source.customer or "").lower()
    source_title = set(normalize_tokens(source.title))
    for analog in analogs:
        customer_match = source_customer and analog.customer.lower() == source_customer
        title_overlap = len(source_title & set(normalize_tokens(analog.title)))
        if customer_match and analog.similarity_score >= 70:
            relation = "SAME_CUSTOMER_SIMILAR_SUBJECT"
        elif analog.repeated_procurement_candidate:
            relation = "LIKELY_REPUBLICATION"
        elif title_overlap >= 3:
            relation = "POSSIBLE_DUPLICATE"
        else:
            continue
        links.append(
            RepeatedProcurementLink(
                current_procurement_number=source.procurement_number,
                previous_procurement_number=analog.analog_procurement_number,
                similarity_score=analog.similarity_score,
                relation_type=relation,
                evidence=analog.similarity_reasons[:3],
                confidence="HIGH" if analog.similarity_score >= 85 else "MEDIUM",
            )
        )
    return links


def apply_history_to_assessment(
    assessment: RadarAssessment,
    bundle: HistoricalAssessmentBundle,
    config: RadarConfig,
) -> RadarAssessment:
    risk = bundle.dumping_risk_assessment
    adjusted = bundle.history_adjusted_assessment or history_adjustment(assessment, risk)
    assessment.historical_adjustment = adjusted.historical_adjustment
    assessment.history_adjusted_score = adjusted.history_adjusted_score
    assessment.history_adjusted_decision = adjusted.history_adjusted_decision
    assessment.historical_adjustment_reasons = adjusted.historical_adjustment_reasons
    assessment.analog_count = bundle.competition_metrics.analog_count_total
    assessment.strong_analog_count = bundle.competition_metrics.strong_analog_count
    assessment.historical_confidence = bundle.competition_metrics.confidence
    assessment.competition_risk_level = risk.risk_level
    assessment.competition_risk_score = risk.risk_score
    assessment.median_participants = bundle.competition_metrics.median_participants
    assessment.median_reduction_percent = bundle.competition_metrics.median_reduction_percent
    assessment.extreme_reduction_rate = bundle.competition_metrics.extreme_reduction_rate
    assessment.no_application_rate = bundle.competition_metrics.no_application_rate
    assessment.repeated_winner_share = bundle.competition_metrics.repeated_winner_share
    if config.enrichment.use_history_adjusted_score:
        assessment.total_score = adjusted.history_adjusted_score
        assessment.radar_decision = adjusted.history_adjusted_decision
    return assessment


def run_historical_for_cards(
    cards: list[RadarCard],
    assessments: list[RadarAssessment],
    config: RadarConfig,
    *,
    offline_history_input: str | Path | None = None,
    history_limit: int | None = None,
) -> tuple[list[HistoricalAssessmentBundle], dict[str, Any]]:
    assessment_map = {item.procurement_number: item for item in assessments}
    bundles: list[HistoricalAssessmentBundle] = []
    diagnostics = {
        "historical_queries_planned": 0,
        "historical_queries_attempted": 0,
        "historical_pages": 0,
        "historical_raw_candidates": 0,
        "historical_unique_candidates": 0,
        "analogs_scored": 0,
        "analogs_selected": 0,
        "analogs_with_complete_results": 0,
        "result_extraction_failures": 0,
        "customer_history_records": 0,
        "supplier_history_records": 0,
        "cache_hits": 0,
    }
    for card in cards[: history_limit or len(cards)]:
        preliminary = assessment_map.get(card.procurement_number)
        if not preliminary:
            continue
        queries = generate_historical_queries(card, config, profile="radar")
        diagnostics["historical_queries_planned"] += len(queries)
        raw_analogs = load_offline_history(offline_history_input, card.procurement_number) if offline_history_input else []
        selected = select_analogs(card, raw_analogs, config)
        metrics = calculate_competition_metrics(selected, config)
        risk = assess_dumping_risk(metrics, config)
        adjusted = history_adjustment(preliminary, risk)
        customer = build_customer_history(card.customer, selected, metrics, config)
        suppliers = build_supplier_history(selected, config)
        repeated = detect_repeated_procurements(card, selected)
        bundle = HistoricalAssessmentBundle(
            procurement_number=card.procurement_number,
            historical_search=queries,
            historical_analogs=selected,
            competition_metrics=metrics,
            customer_history=customer,
            supplier_history=suppliers,
            dumping_risk_assessment=risk,
            history_adjusted_assessment=adjusted,
            repeated_procurements=repeated,
            diagnostics={
                "queries_planned": len(queries),
                "raw_candidates": len(raw_analogs),
                "selected_analogs": len(selected),
            },
        )
        apply_history_to_assessment(preliminary, bundle, config)
        diagnostics["historical_raw_candidates"] += len(raw_analogs)
        diagnostics["historical_unique_candidates"] += len(raw_analogs)
        diagnostics["analogs_scored"] += len(raw_analogs)
        diagnostics["analogs_selected"] += len(selected)
        diagnostics["analogs_with_complete_results"] += metrics.analog_count_with_complete_results
        diagnostics["customer_history_records"] += int(customer is not None)
        diagnostics["supplier_history_records"] += len(suppliers)
        bundles.append(bundle)
    return bundles, diagnostics
