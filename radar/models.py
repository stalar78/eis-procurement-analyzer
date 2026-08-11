from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RadarDecision(StrEnum):
    PRIORITY = "PRIORITY"
    REVIEW = "REVIEW"
    WATCH = "WATCH"
    REJECT = "REJECT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class EnrichmentStatus(StrEnum):
    NOT_SELECTED = "NOT_SELECTED"
    QUEUED = "QUEUED"
    COLLECTING = "COLLECTING"
    COLLECTED = "COLLECTED"
    ANALYZING = "ANALYZING"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    SKIPPED_CACHED = "SKIPPED_CACHED"
    STALE = "STALE"


class EligibilityStatus(StrEnum):
    OPEN = "OPEN"
    DEADLINE_TOO_CLOSE = "DEADLINE_TOO_CLOSE"
    CLOSED = "CLOSED"
    STATUS_UNCLEAR = "STATUS_UNCLEAR"
    DEADLINE_UNKNOWN = "DEADLINE_UNKNOWN"


class NormalizedStatus(StrEnum):
    APPLICATION_SUBMISSION = "APPLICATION_SUBMISSION"
    PRICE_SUBMISSION = "PRICE_SUBMISSION"
    COMMISSION_REVIEW = "COMMISSION_REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    CONTRACT_SIGNED = "CONTRACT_SIGNED"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


@dataclass
class RadarCard:
    procurement_number: str
    title: str = ""
    customer: str = ""
    law: str = ""
    procedure_type: str = ""
    status_raw: str = ""
    status_normalized: str = ""
    nmck: float | None = None
    currency: str = "RUB"
    published_at: str = ""
    updated_at: str = ""
    application_deadline: str = ""
    auction_date: str = ""
    source_url: str = ""
    region: str = ""
    search_queries: list[str] = field(default_factory=list)
    search_profiles: list[str] = field(default_factory=list)
    raw_text: str = ""
    discovered_at: str = ""
    last_seen_at: str = ""
    source_fingerprint: str = ""

    def normalized_payload(self) -> dict[str, Any]:
        return {
            "procurement_number": self.procurement_number,
            "title": self.title,
            "customer": self.customer,
            "law": self.law,
            "procedure_type": self.procedure_type,
            "status_raw": self.status_raw,
            "status_normalized": self.status_normalized,
            "nmck": self.nmck,
            "currency": self.currency,
            "published_at": self.published_at,
            "updated_at": self.updated_at,
            "application_deadline": self.application_deadline,
            "source_url": self.source_url,
        }

    def compute_fingerprint(self) -> str:
        payload = json.dumps(self.normalized_payload(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RadarAssessment:
    procurement_number: str
    eligibility_status: EligibilityStatus
    days_to_deadline: float | None
    is_new: bool = False
    is_changed: bool = False
    preliminary_category: str = ""
    commodity_score: int = 0
    technical_interest_score: int = 0
    deadline_score: int = 0
    budget_score: int = 0
    complexity_signal_score: int = 0
    exclusion_penalty: int = 0
    total_score: int = 0
    radar_decision: RadarDecision = RadarDecision.INSUFFICIENT_DATA
    positive_reasons: list[str] = field(default_factory=list)
    negative_reasons: list[str] = field(default_factory=list)
    hard_reject_reasons: list[str] = field(default_factory=list)
    manual_review_questions: list[str] = field(default_factory=list)
    data_quality_flags: list[str] = field(default_factory=list)
    historical_adjustment: int = 0
    history_adjusted_score: int = 0
    history_adjusted_decision: RadarDecision = RadarDecision.INSUFFICIENT_DATA
    historical_adjustment_reasons: list[str] = field(default_factory=list)
    analog_count: int = 0
    strong_analog_count: int = 0
    historical_confidence: str = "INSUFFICIENT"
    competition_risk_level: str = "UNKNOWN"
    competition_risk_score: int = 0
    median_participants: float | None = None
    median_reduction_percent: float | None = None
    extreme_reduction_rate: float = 0
    no_application_rate: float = 0
    repeated_winner_share: float = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["eligibility_status"] = self.eligibility_status.value
        data["radar_decision"] = self.radar_decision.value
        data["history_adjusted_decision"] = self.history_adjusted_decision.value
        return data


@dataclass
class EnrichmentCandidate:
    procurement_number: str
    reason_selected: str
    ordering: int
    preliminary_score: int
    preliminary_decision: RadarDecision
    source_url: str = ""
    deadline: str = ""
    planned_max_documents: int | None = None
    planned_max_bytes: int | None = None
    cache_state: str = "not_checked"
    expected_action: str = "COLLECT_AND_ANALYZE"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["preliminary_decision"] = self.preliminary_decision.value
        return data


@dataclass
class ArtifactRecord:
    procurement_number: str
    artifact_type: str
    source_url: str = ""
    local_path: str = ""
    original_filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    downloaded_at: str = ""
    extraction_status: str = ""
    document_type: str = ""
    document_confidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeepAssessment:
    procurement_number: str
    preliminary_score: int
    preliminary_decision: RadarDecision
    document_analysis_version: str = ""
    document_completeness_score: int = 0
    document_reliability: str = "INSUFFICIENT"
    technical_participation_verdict: str = "INSUFFICIENT_TECHNICAL_DATA"
    market_result_status: str = ""
    overall_recommendation: str = "INSUFFICIENT_DATA"
    technical_complexity_score: int = 0
    organizational_complexity_score: int = 0
    legal_risk_score: int = 0
    financial_risk_score: int = 0
    ai_fit_score: int = 0
    solo_developer_fit_score: int = 0
    estimated_development_hours_min: int | None = None
    estimated_development_hours_max: int | None = None
    estimated_support_hours: int | None = None
    estimated_infrastructure_costs: float | None = None
    recommended_min_price: float | None = None
    recommended_comfort_price: float | None = None
    nmck_viability: str = ""
    price_margin_vs_min: float | None = None
    price_margin_percent: float | None = None
    specific_platform: str = ""
    specific_platform_required: bool = False
    required_integrations: list[str] = field(default_factory=list)
    required_licenses: list[str] = field(default_factory=list)
    staff_requirements: str = ""
    technical_specification_status: str = "missing"
    contract_status: str = "missing"
    application_requirements_status: str = "missing"
    nmck_status: str = "missing"
    protocol_status: str = "missing"
    key_positive_factors: list[str] = field(default_factory=list)
    key_risks: list[str] = field(default_factory=list)
    blocking_factors: list[str] = field(default_factory=list)
    participation_conditions: list[str] = field(default_factory=list)
    unanswered_questions: list[str] = field(default_factory=list)
    evidence_count: int = 0
    high_confidence_evidence_count: int = 0
    manual_review_required: bool = True
    commodity_risk_confirmed: bool = False
    commodity_risk_reasons: list[str] = field(default_factory=list)
    deep_score: int = 0
    final_radar_decision: RadarDecision = RadarDecision.INSUFFICIENT_DATA
    final_decision_reasons: list[str] = field(default_factory=list)
    enrichment_status: EnrichmentStatus = EnrichmentStatus.NOT_SELECTED
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["preliminary_decision"] = self.preliminary_decision.value
        data["final_radar_decision"] = self.final_radar_decision.value
        data["enrichment_status"] = self.enrichment_status.value
        return data


@dataclass
class HistoricalSearchQuery:
    source_procurement_number: str
    query_text: str
    query_type: str
    generation_reason: str = ""
    law: str = ""
    customer: str = ""
    region: str = ""
    date_from: str = ""
    date_to: str = ""
    completed_only: bool = True
    profile: str = ""
    weight: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HistoricalAnalog:
    source_procurement_number: str
    analog_procurement_number: str
    title: str = ""
    customer: str = ""
    law: str = ""
    procedure_type: str = ""
    region: str = ""
    nmck: float | None = None
    contract_price: float | None = None
    participant_count: int | None = None
    admitted_participant_count: int | None = None
    reduction_percent: float | None = None
    winner_name: str = ""
    winner_identifier: str = ""
    published_at: str = ""
    completed_at: str = ""
    source_url: str = ""
    similarity_score: int = 0
    title_similarity_score: int = 0
    functional_similarity_score: int = 0
    customer_similarity_score: int = 0
    procedure_similarity_score: int = 0
    budget_similarity_score: int = 0
    region_similarity_score: int = 0
    profile_similarity_score: int = 0
    similarity_reasons: list[str] = field(default_factory=list)
    mismatch_reasons: list[str] = field(default_factory=list)
    result_data_status: str = "UNKNOWN"
    result_confidence: str = "LOW"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    no_applications: bool = False
    all_applications_rejected: bool = False
    failed_procurement: bool = False
    failure_reason: str = ""
    repeated_procurement_candidate: bool = False
    category_compatibility: str = "UNKNOWN"
    selection_mode: str = ""
    selection_reason: str = ""
    threshold_required: int = 0
    threshold_gap: int = 0
    hard_floor_passed: bool = False
    exclusion_reason: str = ""
    missing_fields: list[str] = field(default_factory=list)
    source_normalized_tokens: list[str] = field(default_factory=list)
    candidate_normalized_tokens: list[str] = field(default_factory=list)
    source_functional_terms: list[str] = field(default_factory=list)
    candidate_functional_terms: list[str] = field(default_factory=list)
    shared_title_tokens: list[str] = field(default_factory=list)
    shared_functional_terms: list[str] = field(default_factory=list)
    source_profile: str = ""
    candidate_profile: str = ""
    source_category: str = ""
    candidate_category: str = ""
    source_query: str = ""
    result_url: str = ""
    protocol_url: str = ""
    contract_url: str = ""
    result_source_type: str = ""
    result_resolution_status: str = ""
    result_cache_used: bool = False
    result_cache_age_hours: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalogResultResolutionDiagnostic:
    procurement_number: str
    law: str
    source_url: str
    common_url: str = ""
    result_url: str = ""
    protocol_url: str = ""
    contract_url: str = ""
    resolution_strategy: str = "NONE"
    resolution_status: str = "NOT_FOUND"
    urls_attempted: list[str] = field(default_factory=list)
    http_statuses: dict[str, int | None] = field(default_factory=dict)
    browser_statuses: dict[str, str] = field(default_factory=dict)
    page_types_detected: list[str] = field(default_factory=list)
    document_links_found: list[str] = field(default_factory=list)
    protocol_documents_found: list[str] = field(default_factory=list)
    cache_used: bool = False
    cache_age_hours: float | None = None
    final_resolved_url: str = ""
    result_source_type: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssembledHistoricalResult:
    procurement_number: str
    nmck: float | None = None
    final_price: float | None = None
    participant_count: int | None = None
    admitted_participant_count: int | None = None
    winner_name: str = ""
    winner_identifier: str = ""
    reduction_percent: float | None = None
    nmck_evidence: list[dict[str, Any]] = field(default_factory=list)
    final_price_evidence: list[dict[str, Any]] = field(default_factory=list)
    participant_count_evidence: list[dict[str, Any]] = field(default_factory=list)
    admitted_count_evidence: list[dict[str, Any]] = field(default_factory=list)
    winner_evidence: list[dict[str, Any]] = field(default_factory=list)
    reduction_inputs: dict[str, Any] = field(default_factory=dict)
    completeness: str = "NO_USABLE_RESULT"
    confidence: str = "LOW"
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompetitionMetrics:
    analog_count_total: int = 0
    analog_count_with_complete_results: int = 0
    analog_count_partial: int = 0
    participant_sample_size: int = 0
    reduction_sample_size: int = 0
    winner_sample_size: int = 0
    complete_result_sample_size: int = 0
    no_application_sample_size: int = 0
    strong_analog_count: int = 0
    median_participants: float | None = None
    average_participants: float | None = None
    participants_p25: float | None = None
    participants_p75: float | None = None
    maximum_participants: int | None = None
    median_reduction_percent: float | None = None
    average_reduction_percent: float | None = None
    reduction_p25: float | None = None
    reduction_p75: float | None = None
    maximum_reduction_percent: float | None = None
    high_reduction_rate: float = 0
    extreme_reduction_count: int = 0
    extreme_reduction_rate: float = 0
    severe_reduction_rate: float = 0
    no_application_count: int = 0
    no_application_rate: float = 0
    all_rejected_count: int = 0
    all_rejected_rate: float = 0
    cancelled_count: int = 0
    cancellation_rate: float = 0
    repeated_winner_count: int = 0
    repeated_winner_share: float = 0
    sample_quality: str = "INSUFFICIENT"
    confidence: str = "INSUFFICIENT"
    participant_metric_confidence: str = "INSUFFICIENT"
    reduction_metric_confidence: str = "INSUFFICIENT"
    winner_metric_confidence: str = "INSUFFICIENT"
    participant_contributors: list[str] = field(default_factory=list)
    reduction_contributors: list[str] = field(default_factory=list)
    winner_contributors: list[str] = field(default_factory=list)
    no_application_contributors: list[str] = field(default_factory=list)
    complete_result_contributors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DumpingRiskAssessment:
    risk_level: str = "UNKNOWN"
    risk_score: int = 0
    confidence: str = "INSUFFICIENT"
    sample_size: int = 0
    strong_analog_sample_size: int = 0
    competition_level: str = "UNKNOWN"
    expected_competition_band: str = ""
    historical_reduction_band: str = ""
    high_participant_risk: bool = False
    extreme_reduction_risk: bool = False
    commodity_market_risk: bool = False
    no_application_opportunity: bool = False
    customer_specific_risk: bool = False
    supplier_concentration_signal: bool = False
    participant_metric_confidence: str = "INSUFFICIENT"
    reduction_metric_confidence: str = "INSUFFICIENT"
    winner_metric_confidence: str = "INSUFFICIENT"
    positive_signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CustomerHistoryProfile:
    normalized_customer_name: str
    customer_identifiers: list[str] = field(default_factory=list)
    total_completed_procurements: int = 0
    total_failed_procurements: int = 0
    total_cancelled_procurements: int = 0
    procurements_with_result_data: int = 0
    median_nmck: float | None = None
    median_contract_price: float | None = None
    median_reduction_percent: float | None = None
    average_reduction_percent: float | None = None
    reduction_percent_p25: float | None = None
    reduction_percent_p75: float | None = None
    median_participants: float | None = None
    average_participants: float | None = None
    maximum_participants: int | None = None
    no_application_rate: float = 0
    all_rejected_rate: float = 0
    cancellation_rate: float = 0
    repeated_winner_share: float = 0
    top_winners: list[dict[str, Any]] = field(default_factory=list)
    commodity_procurement_share: float = 0
    high_dumping_procurement_share: float = 0
    history_confidence: str = "INSUFFICIENT"
    evidence_count: int = 0
    last_updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SupplierHistoryProfile:
    supplier_name: str
    supplier_identifier: str = ""
    known_wins: int = 0
    customers: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    median_reduction_percent: float | None = None
    average_reduction_percent: float | None = None
    extreme_reduction_count: int = 0
    repeat_customer_count: int = 0
    known_termination_count: int | None = None
    known_penalty_count: int | None = None
    confidence: str = "LOW"
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepeatedProcurementLink:
    current_procurement_number: str
    previous_procurement_number: str
    relation_type: str
    relation_score: int = 0
    similarity_score: int = 0
    confidence: str = "LOW"
    same_customer: bool = False
    title_similarity: int = 0
    functional_similarity: int = 0
    budget_similarity: int = 0
    procedure_similarity: int = 0
    region_similarity: int = 0
    previous_failure_type: str = ""
    previous_completed_at: str = ""
    current_published_at: str = ""
    days_between: int | None = None
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["similarity_score"]:
            data["similarity_score"] = self.relation_score
        if not data["relation_score"]:
            data["relation_score"] = self.similarity_score
        return data


@dataclass
class ProcurementFailureEvent:
    procurement_number: str
    law: str = ""
    customer: str = ""
    title: str = ""
    nmck: float | None = None
    procedure_type: str = ""
    region: str = ""
    failure_type: str = "UNKNOWN_FAILURE"
    failure_status_raw: str = ""
    failure_status_normalized: str = ""
    failure_reason: str = ""
    application_count: int | None = None
    admitted_application_count: int | None = None
    single_application: bool = False
    single_application_admitted: bool = False
    single_application_winner: bool = False
    contract_concluded: bool = False
    contract_not_concluded: bool = False
    protocol_url: str = ""
    result_url: str = ""
    evidence_source: str = ""
    evidence_excerpt: str = ""
    evidence_confidence: str = "LOW"
    completed_at: str = ""
    detected_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FailureDiscoveryDiagnostic:
    mode: str
    query: str
    law: str
    url: str
    request_params: dict[str, Any] = field(default_factory=dict)
    page_number: int = 1
    http_status: int | None = None
    raw_cards: int = 0
    parsed_cards: int = 0
    unique_cards: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpportunityTransition:
    procurement_number: str
    transition_type: str
    previous_value: str = ""
    current_value: str = ""
    detected_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeFeedEvent:
    procurement_number: str
    event_type: str
    detected_at: str
    field_name: str = ""
    previous_value: str = ""
    current_value: str = ""
    severity: str = "INFO"
    source: str = "procurement_state"
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NoCompetitionOpportunity:
    current_procurement_number: str
    previous_procurement_number: str = ""
    current_title: str = ""
    current_customer: str = ""
    current_nmck: float | None = None
    current_status: str = ""
    current_deadline: str = ""
    current_source_url: str = ""
    previous_failure_type: str = ""
    previous_application_count: int | None = None
    previous_nmck: float | None = None
    republication_confidence: str = "LOW"
    republication_score: int = 0
    preliminary_score: int = 0
    history_adjusted_score: int = 0
    technical_fit_signal: int = 0
    competition_opportunity_signal: int = 0
    opportunity_score: int = 0
    opportunity_level: str = "INSUFFICIENT_DATA"
    positive_signals: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HistoryAdjustedAssessment:
    procurement_number: str
    preliminary_score: int
    historical_adjustment: int
    history_adjusted_score: int
    history_adjusted_decision: RadarDecision
    historical_adjustment_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["history_adjusted_decision"] = self.history_adjusted_decision.value
        return data


@dataclass
class RadarRunResult:
    run_id: str
    started_at: datetime
    finished_at: datetime
    as_of: datetime
    cards: list[RadarCard]
    assessments: list[RadarAssessment]
    diagnostics: dict[str, Any]
