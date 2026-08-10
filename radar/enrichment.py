from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from radar.artifact_registry import ArtifactRegistry, fingerprint_records
from radar.config import RadarConfig
from radar.deep_assessment import map_deep_assessment
from radar.live_collection import ProcurementCollectionTarget, normalize_eis_url
from radar.models import (
    ArtifactRecord,
    DeepAssessment,
    EnrichmentCandidate,
    EnrichmentStatus,
    RadarAssessment,
    RadarCard,
    RadarDecision,
)
from radar.prefilter import parse_datetime


ERROR_CODES = {
    "DOWNLOAD_LIMIT_REACHED",
    "FILE_TOO_LARGE",
    "TOO_MANY_DOCUMENTS",
    "DOWNLOAD_TIMEOUT",
    "INVALID_CONTENT_TYPE",
    "HTML_INSTEAD_OF_DOCUMENT",
    "TLS_FAILURE",
    "ACCESS_DENIED",
    "DOCUMENT_LINK_EXPIRED",
    "COLLECTION_FAILED",
    "ANALYSIS_FAILED",
    "UNSUPPORTED_ARCHIVE",
    "EXTRACTION_INCOMPLETE",
    "UNKNOWN_ERROR",
}


@dataclass
class EnrichmentPlan:
    selected: list[EnrichmentCandidate] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    estimated_operation_count: int = 0
    configured_limits: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_procurements": [item.to_dict() for item in self.selected],
            "skipped_procurements": self.skipped,
            "estimated_operation_count": self.estimated_operation_count,
            "configured_limits": self.configured_limits,
        }


@dataclass
class EnrichmentResult:
    plan: EnrichmentPlan
    deep_assessments: list[DeepAssessment] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _card_by_number(cards: list[RadarCard]) -> dict[str, RadarCard]:
    return {card.procurement_number: card for card in cards if card.procurement_number}


def _assessment_by_number(assessments: list[RadarAssessment]) -> dict[str, RadarAssessment]:
    return {item.procurement_number: item for item in assessments}


def _skip(plan: EnrichmentPlan, card: RadarCard | None, number: str, reason: str) -> None:
    plan.skipped.append(
        {
            "procurement_number": number or (card.procurement_number if card else ""),
            "title": card.title if card else "",
            "reason_skipped": reason,
        }
    )


def select_enrichment_candidates(
    cards: list[RadarCard],
    assessments: list[RadarAssessment],
    config: RadarConfig,
    *,
    decisions: list[str] | None = None,
    total_limit: int | None = None,
    priority_limit: int | None = None,
    review_limit: int | None = None,
    procurement_numbers: list[str] | None = None,
    force_enrich: bool = False,
    state: Any = None,
    refresh_enrichment: bool = False,
    as_of: datetime | None = None,
) -> EnrichmentPlan:
    allowed_decisions = set(decisions or config.enrichment.decisions)
    total_limit = total_limit if total_limit is not None else config.enrichment.total_limit_per_run
    priority_limit = priority_limit if priority_limit is not None else config.enrichment.priority_limit_per_run
    review_limit = review_limit if review_limit is not None else config.enrichment.review_limit_per_run
    explicit = set(procurement_numbers or [])
    card_map = _card_by_number(cards)
    assessment_map = _assessment_by_number(assessments)
    plan = EnrichmentPlan(
        configured_limits={
            "total_limit_per_run": total_limit,
            "priority_limit_per_run": priority_limit,
            "review_limit_per_run": review_limit,
            "minimum_days_to_deadline": config.enrichment.minimum_days_to_deadline,
            "max_documents_per_procurement": config.enrichment.max_documents_per_procurement,
            "max_total_download_mb_per_run": config.enrichment.max_total_download_mb_per_run,
        }
    )

    candidates: list[tuple[RadarCard, RadarAssessment, str, bool]] = []
    for card in cards:
        assessment = assessment_map.get(card.procurement_number)
        if not assessment:
            _skip(plan, card, card.procurement_number, "missing preliminary assessment")
            continue
        is_explicit = card.procurement_number in explicit
        if assessment.eligibility_status.value == "CLOSED":
            _skip(plan, card, card.procurement_number, "closed procurement")
            continue
        if not card.procurement_number:
            _skip(plan, card, card.procurement_number, "missing procurement number")
            continue
        if not card.source_url:
            _skip(plan, card, card.procurement_number, "missing source URL")
            continue
        if assessment.hard_reject_reasons and not (is_explicit and force_enrich):
            _skip(plan, card, card.procurement_number, "hard reject")
            continue
        if assessment.days_to_deadline is not None and assessment.days_to_deadline < config.enrichment.minimum_days_to_deadline and not (is_explicit and force_enrich):
            _skip(plan, card, card.procurement_number, "deadline too close for enrichment")
            continue
        if assessment.radar_decision.value not in allowed_decisions and not (is_explicit and force_enrich):
            _skip(plan, card, card.procurement_number, "decision is not selected for enrichment")
            continue
        min_score = config.enrichment.minimum_preliminary_score.get(assessment.radar_decision.value, 0)
        if assessment.total_score < min_score and not (is_explicit and force_enrich):
            _skip(plan, card, card.procurement_number, "preliminary score below enrichment threshold")
            continue
        if config.enrichment.include_new_only and not assessment.is_new and not (is_explicit and force_enrich):
            _skip(plan, card, card.procurement_number, "policy includes only new procurements")
            continue
        if state and not refresh_enrichment and config.enrichment.skip_already_enriched:
            cache_reason = state.enrichment_cache_skip_reason(
                card.procurement_number,
                card.source_fingerprint,
                config.enrichment.refresh_after_hours,
                as_of=as_of,
            )
            if cache_reason:
                _skip(plan, card, card.procurement_number, cache_reason)
                continue
        candidates.append((card, assessment, "explicit override" if is_explicit else f"{assessment.radar_decision.value} candidate", is_explicit))

    def sort_key(item: tuple[RadarCard, RadarAssessment, str, bool]) -> tuple[int, int, int, int, int, float, float]:
        card, assessment, _reason, is_explicit = item
        deadline = parse_datetime(card.application_deadline) if card.application_deadline else None
        deadline_ts = deadline.timestamp() if deadline else float("inf")
        priority = 0 if assessment.radar_decision == RadarDecision.PRIORITY else 1
        return (
            0 if is_explicit else 1,
            priority,
            0 if assessment.is_new else 1,
            0 if assessment.is_changed else 1,
            -assessment.total_score,
            deadline_ts,
            -(card.nmck or 0),
        )

    selected_counts = {RadarDecision.PRIORITY.value: 0, RadarDecision.REVIEW.value: 0}
    for card, assessment, reason, is_explicit in sorted(candidates, key=sort_key):
        if len(plan.selected) >= total_limit:
            _skip(plan, card, card.procurement_number, "total enrichment limit reached")
            continue
        if not is_explicit and assessment.radar_decision == RadarDecision.PRIORITY and selected_counts[RadarDecision.PRIORITY.value] >= priority_limit:
            _skip(plan, card, card.procurement_number, "priority enrichment limit reached")
            continue
        if not is_explicit and assessment.radar_decision == RadarDecision.REVIEW and selected_counts[RadarDecision.REVIEW.value] >= review_limit:
            _skip(plan, card, card.procurement_number, "review enrichment limit reached")
            continue
        selected_counts[assessment.radar_decision.value] = selected_counts.get(assessment.radar_decision.value, 0) + 1
        plan.selected.append(
            EnrichmentCandidate(
                procurement_number=card.procurement_number,
                reason_selected=reason,
                ordering=len(plan.selected) + 1,
                preliminary_score=assessment.total_score,
                preliminary_decision=assessment.radar_decision,
                source_url=card.source_url,
                deadline=card.application_deadline,
                planned_max_documents=config.enrichment.max_documents_per_procurement,
                planned_max_bytes=config.enrichment.max_total_download_mb_per_run * 1024 * 1024,
                cache_state="will_check_state" if state else "not_checked",
                expected_action="COLLECT_AND_ANALYZE",
            )
        )
    plan.estimated_operation_count = len(plan.selected) * 2
    return plan


def load_offline_analysis(offline_root: str | Path, procurement_number: str) -> tuple[dict[str, Any], list[ArtifactRecord]]:
    root = Path(offline_root)
    proc_dir = root / procurement_number
    analysis_path = proc_dir / "analysis.json"
    if not analysis_path.exists():
        raise FileNotFoundError(f"Offline enrichment analysis not found: {analysis_path}")
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    artifacts_path = proc_dir / "artifacts.json"
    artifacts = []
    if artifacts_path.exists():
        registry = ArtifactRegistry(root)
        artifacts = registry.load_manifest_records(procurement_number, artifacts_path)
    return analysis, artifacts


def analyze_procurement_directory(
    procurement_dir: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
    run_regression_checks: bool = False,
) -> dict[str, Any]:
    import analyze_candidate_documents

    if run_regression_checks and analyze_candidate_documents.run_regression_tests() != 0:
        raise RuntimeError("document analyzer regression checks failed")
    output_dir.mkdir(parents=True, exist_ok=True)
    utilities = analyze_candidate_documents.detect_utilities()
    return analyze_candidate_documents.process_procurement(
        procurement_dir,
        output_dir,
        utilities,
        overwrite,
        True,
        False,
    )


def run_enrichment(
    cards: list[RadarCard],
    assessments: list[RadarAssessment],
    config: RadarConfig,
    *,
    state: Any = None,
    offline_enrichment_input: str | Path | None = None,
    download_dir: str | Path | None = None,
    analysis_dir: str | Path | None = None,
    dry_run: bool = False,
    skip_download: bool = False,
    skip_analysis: bool = False,
    refresh_enrichment: bool = False,
    decisions: list[str] | None = None,
    total_limit: int | None = None,
    priority_limit: int | None = None,
    review_limit: int | None = None,
    procurement_numbers: list[str] | None = None,
    source_url: str | None = None,
    force_enrich: bool = False,
) -> EnrichmentResult:
    plan = select_enrichment_candidates(
        cards,
        assessments,
        config,
        decisions=decisions,
        total_limit=total_limit,
        priority_limit=priority_limit,
        review_limit=review_limit,
        procurement_numbers=procurement_numbers,
        force_enrich=force_enrich,
        state=state,
        refresh_enrichment=refresh_enrichment,
    )
    diagnostics = {
        "candidates_selected_for_enrichment": len(plan.selected),
        "enrichments_complete": 0,
        "enrichments_partial": 0,
        "enrichments_failed_retryable": 0,
        "enrichments_failed_final": 0,
        "cached_enrichments_reused": 0,
        "documents_downloaded": 0,
        "total_downloaded_bytes": 0,
        "errors": [],
    }
    if dry_run:
        return EnrichmentResult(plan=plan, diagnostics=diagnostics)

    assessment_map = _assessment_by_number(assessments)
    deep_assessments: list[DeepAssessment] = []
    artifacts: list[ArtifactRecord] = []
    registry = ArtifactRegistry(download_dir or "data/radar_enrichment")
    for candidate in plan.selected:
        preliminary = assessment_map[candidate.procurement_number]
        try:
            if offline_enrichment_input:
                analysis, proc_artifacts = load_offline_analysis(offline_enrichment_input, candidate.procurement_number)
            elif skip_analysis:
                analysis, proc_artifacts = {}, []
            else:
                proc_dir = registry.procurement_dir(candidate.procurement_number)
                collection_results = []
                proc_artifacts = []
                if not skip_download:
                    import collect_candidate_details

                    card = _card_by_number(cards)[candidate.procurement_number]
                    target_url = source_url or card.source_url
                    if source_url:
                        normalize_eis_url(source_url, candidate.procurement_number)
                    collection_results = collect_candidate_details.collect_candidate_details_for_procurements(
                        [ProcurementCollectionTarget(candidate.procurement_number, target_url)],
                        Path(download_dir or "data/radar_enrichment"),
                        overwrite=False,
                        refresh=refresh_enrichment,
                        max_documents_per_procurement=config.enrichment.max_documents_per_procurement,
                        max_total_download_bytes=config.enrichment.max_total_download_mb_per_run * 1024 * 1024,
                        max_single_file_bytes=config.enrichment.max_single_file_mb * 1024 * 1024,
                        timeout_seconds=config.enrichment.download_timeout_seconds,
                    )
                    diagnostics["live_collection_results"] = [
                        item.to_dict() if hasattr(item, "to_dict") else item.__dict__
                        for item in collection_results
                    ]
                    first = collection_results[0]
                    if first.status in {"FAILED_FINAL", "FAILED_RETRYABLE"}:
                        raise RuntimeError("; ".join(first.errors) or first.status)
                    proc_dir = Path(first.procurement_directory)
                    if first.manifest_path:
                        try:
                            manifest = json.loads(Path(first.manifest_path).read_text(encoding="utf-8"))
                            for row in manifest.get("artifacts", []):
                                proc_artifacts.append(ArtifactRecord(**row))
                        except Exception:
                            pass
                if skip_download and not proc_dir.exists():
                    raise FileNotFoundError(f"No downloaded procurement directory: {proc_dir}")
                if not any((proc_dir / "downloads").rglob("*")):
                    raise RuntimeError("collection produced no usable documents")
                analysis = analyze_procurement_directory(
                    proc_dir,
                    Path(analysis_dir or proc_dir / "analysis"),
                    overwrite=refresh_enrichment,
                )

            if proc_artifacts:
                doc_fingerprint = fingerprint_records(proc_artifacts)
                analysis["document_set_fingerprint"] = doc_fingerprint
            status = EnrichmentStatus.PARTIAL if analysis.get("partial_failure") else EnrichmentStatus.COMPLETE
            deep = map_deep_assessment(analysis, preliminary, config, status=status)
            deep_assessments.append(deep)
            artifacts.extend(proc_artifacts)
            diagnostics["documents_downloaded"] += len([item for item in proc_artifacts if item.artifact_type == "document"])
            diagnostics["total_downloaded_bytes"] += sum(item.size_bytes for item in proc_artifacts)
            if status == EnrichmentStatus.COMPLETE:
                diagnostics["enrichments_complete"] += 1
            else:
                diagnostics["enrichments_partial"] += 1
        except Exception as error:
            diagnostics["enrichments_failed_retryable"] += 1
            diagnostics["errors"].append(f"{candidate.procurement_number}: {error}")
            failed = DeepAssessment(
                procurement_number=candidate.procurement_number,
                preliminary_score=preliminary.total_score,
                preliminary_decision=preliminary.radar_decision,
                enrichment_status=EnrichmentStatus.FAILED_RETRYABLE,
                error_code="ANALYSIS_FAILED",
                error_message=str(error),
            )
            deep_assessments.append(failed)
            if config.enrichment.stop_on_error:
                break
    return EnrichmentResult(plan=plan, deep_assessments=deep_assessments, artifacts=artifacts, diagnostics=diagnostics)
