from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RadarRuntimeConfig:
    timezone: str = "Europe/Moscow"
    output_dir: str = "outputs/radar"
    database: str = "data/radar.db"
    request_delay_seconds: float = 1.5
    max_pages_per_query: int = 5
    max_results_per_query: int = 200
    default_minimum_days_to_deadline: int = 7
    preferred_days_to_deadline: int = 30
    update_existing_after_hours: int = 24
    save_raw_cards: bool = True
    deadline_too_close_watch_days: int = 2


@dataclass
class FilterConfig:
    laws: list[str] = field(default_factory=lambda: ["44-FZ", "223-FZ"])
    statuses: list[str] = field(default_factory=lambda: ["application_submission"])
    hard_exclusion_terms: list[str] = field(default_factory=list)
    preferred_nmck_min: float = 500_000
    preferred_nmck_max: float = 3_000_000
    hard_nmck_min: float = 150_000


@dataclass
class ScoringConfig:
    priority_threshold: int = 75
    review_threshold: int = 55
    watch_threshold: int = 35


@dataclass
class EnrichmentConfig:
    enabled: bool = False
    decisions: list[str] = field(default_factory=lambda: ["PRIORITY", "REVIEW"])
    priority_limit_per_run: int = 10
    review_limit_per_run: int = 5
    total_limit_per_run: int = 12
    minimum_preliminary_score: dict[str, int] = field(default_factory=lambda: {"PRIORITY": 75, "REVIEW": 60})
    minimum_days_to_deadline: int = 5
    include_new_only: bool = False
    include_changed: bool = True
    skip_already_enriched: bool = True
    refresh_after_hours: int = 72
    max_documents_per_procurement: int = 80
    max_total_download_mb_per_run: int = 500
    max_single_file_mb: int = 50
    download_timeout_seconds: int = 90
    analysis_timeout_seconds: int = 600
    retry_failed_after_hours: int = 12
    max_attempts: int = 3
    stop_on_error: bool = False
    solo_fit_threshold: int = 6
    ai_fit_threshold: int = 6
    use_history_adjusted_score: bool = True
    reject_extreme_competition_before_enrichment: bool = False
    downgrade_extreme_competition_to_watch: bool = True
    enrich_unknown_history: bool = True
    enrich_high_competition_when_technical_score_above: int = 85


@dataclass
class DiscoveryFallbackConfig:
    enabled: bool = True
    widen_published_window_days: list[int] = field(default_factory=lambda: [60, 120])
    use_active_and_recent: bool = False
    add_broader_queries: bool = True


@dataclass
class DiscoveryConfig:
    mode: str = "ACTIVE_ONLY"
    laws: list[str] = field(default_factory=lambda: ["44-FZ", "223-FZ"])
    include_statuses: list[str] = field(default_factory=lambda: ["application_submission"])
    exclude_statuses: list[str] = field(default_factory=lambda: ["completed", "cancelled", "contract_signed"])
    published_within_days: int = 30
    updated_within_days: int = 30
    sort: dict[str, str] = field(default_factory=lambda: {"field": "update_date", "direction": "desc"})
    verify_open_status_from_detail_page: bool = True
    verify_top_candidates_limit: int = 20
    query_retry_count: int = 2
    empty_query_retry_count: int = 1
    maximum_queries_per_run: int = 10
    maximum_total_pages: int = 10
    maximum_unique_cards: int = 200
    minimum_open_candidates_target: int = 3
    fallback: DiscoveryFallbackConfig = field(default_factory=DiscoveryFallbackConfig)


@dataclass
class HistoricalSearchConfig:
    lookback_days: int = 1095
    maximum_queries_per_procurement: int = 5
    maximum_pages_per_query: int = 3
    maximum_raw_candidates: int = 200
    maximum_selected_analogs: int = 20
    minimum_selected_analogs: int = 3


@dataclass
class HistoricalResultCollectionConfig:
    enabled: bool = True
    maximum_result_pages_per_analog: int = 3
    maximum_documents_per_analog: int = 10
    download_full_documents: bool = False
    prefer_structured_results: bool = True
    prefer_protocol_pages: bool = True


@dataclass
class HistoricalSimilarityConfig:
    minimum_score: int = 45
    strong_similarity_score: int = 70
    relaxed_threshold_delta: int = 10
    hard_floor_score: int = 30


@dataclass
class HistoricalBoundedConfig:
    enabled: bool = True
    maximum_procurements: int = 100
    maximum_suppliers_per_procurement: int = 10


@dataclass
class HistoricalCacheConfig:
    refresh_after_hours: int = 168


@dataclass
class DumpingConfig:
    high_reduction_threshold: int = 50
    extreme_reduction_threshold: int = 75
    severe_reduction_threshold: int = 90
    high_participant_threshold: int = 10
    extreme_participant_threshold: int = 25
    minimum_sample_for_medium_confidence: int = 5
    minimum_sample_for_high_confidence: int = 10
    commodity_risk_reduction_threshold: int = 60
    commodity_risk_participant_threshold: int = 15


@dataclass
class HistoricalConfig:
    enabled: bool = False
    search: HistoricalSearchConfig = field(default_factory=HistoricalSearchConfig)
    result_collection: HistoricalResultCollectionConfig = field(default_factory=HistoricalResultCollectionConfig)
    similarity: HistoricalSimilarityConfig = field(default_factory=HistoricalSimilarityConfig)
    customer_history: HistoricalBoundedConfig = field(default_factory=HistoricalBoundedConfig)
    supplier_history: HistoricalBoundedConfig = field(default_factory=HistoricalBoundedConfig)
    cache: HistoricalCacheConfig = field(default_factory=HistoricalCacheConfig)
    dumping: DumpingConfig = field(default_factory=DumpingConfig)


@dataclass
class OpportunityFailureHistoryConfig:
    lookback_days: int = 1095
    maximum_queries_per_procurement: int = 3
    maximum_pages_per_query: int = 2
    maximum_candidates: int = 50
    maximum_result_resolutions: int = 5
    refresh_after_hours: int = 168


@dataclass
class OpportunityRepublicationConfig:
    maximum_days_between: int = 365
    strong_window_days: int = 90
    minimum_relation_score: int = 50
    strong_relation_score: int = 75


@dataclass
class OpportunityScoringConfig:
    high_threshold: int = 75
    medium_threshold: int = 55
    low_threshold: int = 35
    minimum_opportunity_score: int = 35


@dataclass
class OpportunitiesConfig:
    enabled: bool = False
    failure_history: OpportunityFailureHistoryConfig = field(default_factory=OpportunityFailureHistoryConfig)
    republication: OpportunityRepublicationConfig = field(default_factory=OpportunityRepublicationConfig)
    scoring: OpportunityScoringConfig = field(default_factory=OpportunityScoringConfig)


@dataclass
class RadarConfig:
    radar: RadarRuntimeConfig = field(default_factory=RadarRuntimeConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    historical: HistoricalConfig = field(default_factory=HistoricalConfig)
    opportunities: OpportunitiesConfig = field(default_factory=OpportunitiesConfig)


def _merge_dataclass(instance: Any, data: dict[str, Any]) -> Any:
    for key, value in data.items():
        if hasattr(instance, key):
            setattr(instance, key, value)
    return instance


def load_config(path: str | Path | None = None) -> RadarConfig:
    config = RadarConfig()
    if not path:
        default_path = Path("config/radar.example.yaml")
        path = default_path if default_path.exists() else None
    if not path:
        return config

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    _merge_dataclass(config.radar, data.get("radar", {}))
    _merge_dataclass(config.filters, data.get("filters", {}))
    _merge_dataclass(config.scoring, data.get("scoring", {}))
    _merge_dataclass(config.enrichment, data.get("enrichment", {}))
    discovery_data = data.get("discovery", {})
    fallback_data = discovery_data.pop("fallback", None) if isinstance(discovery_data, dict) else None
    _merge_dataclass(config.discovery, discovery_data)
    if fallback_data:
        _merge_dataclass(config.discovery.fallback, fallback_data)
    historical_data = data.get("historical", {})
    if isinstance(historical_data, dict):
        nested = {
            "search": config.historical.search,
            "result_collection": config.historical.result_collection,
            "similarity": config.historical.similarity,
            "customer_history": config.historical.customer_history,
            "supplier_history": config.historical.supplier_history,
            "cache": config.historical.cache,
            "dumping": config.historical.dumping,
        }
        top_level = {k: v for k, v in historical_data.items() if k not in nested}
        _merge_dataclass(config.historical, top_level)
        for key, instance in nested.items():
            if key in historical_data:
                _merge_dataclass(instance, historical_data[key])
    opportunities_data = data.get("opportunities", {})
    if isinstance(opportunities_data, dict):
        nested_opportunities = {
            "failure_history": config.opportunities.failure_history,
            "republication": config.opportunities.republication,
            "scoring": config.opportunities.scoring,
        }
        top_level = {k: v for k, v in opportunities_data.items() if k not in nested_opportunities}
        _merge_dataclass(config.opportunities, top_level)
        for key, instance in nested_opportunities.items():
            if key in opportunities_data:
                _merge_dataclass(instance, opportunities_data[key])
    return config
