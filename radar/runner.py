from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from radar import radar_version
from radar.config import load_config
from radar.discovery import discover_cards
from radar.enrichment import run_enrichment
from radar.historical import run_historical_for_cards
from radar.historical_live_validation import (
    exclude_validation_source_from_active_assessment,
    run_live_historical_validation,
    validate_live_history_args,
)
from radar.live_collection import normalize_eis_url
from radar.models import RadarCard
from radar.prefilter import evaluate_eligibility, parse_as_of
from radar.reporting import write_reports
from radar.scoring import assess_card
from radar.search_profiles import load_search_profiles, select_profiles
from radar.source_resolution import resolve_procurement_source
from radar.state import RadarState


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EIS Procurement Radar Stage R1.")
    parser.add_argument("--config", default="config/radar.example.yaml")
    parser.add_argument("--profile")
    parser.add_argument("--all-profiles", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--db")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline-input")
    parser.add_argument("--as-of")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--enrich", action="store_true")
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument("--enrich-decisions")
    parser.add_argument("--enrich-limit", type=int)
    parser.add_argument("--priority-enrich-limit", type=int)
    parser.add_argument("--review-enrich-limit", type=int)
    parser.add_argument("--procurement-number", action="append", default=[])
    parser.add_argument("--source-url")
    parser.add_argument("--force-enrich", action="store_true")
    parser.add_argument("--refresh-enrichment", action="store_true")
    parser.add_argument("--download-dir")
    parser.add_argument("--analysis-dir")
    parser.add_argument("--max-documents-per-procurement", type=int)
    parser.add_argument("--max-total-download-mb", type=int)
    parser.add_argument("--max-single-file-mb", type=int)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--resume-enrichment", action="store_true")
    parser.add_argument("--enrichment-only", action="store_true")
    parser.add_argument("--offline-enrichment-input")
    parser.add_argument("--discovery-mode", choices=["ACTIVE_ONLY", "ACTIVE_AND_RECENT", "ALL_STATUSES", "COMPLETED_ONLY", "COMPLETED_AND_FAILED", "CUSTOMER_HISTORY", "SUPPLIER_HISTORY"])
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--history-only", action="store_true")
    parser.add_argument("--allow-completed-source", action="store_true")
    parser.add_argument("--resume-history", action="store_true")
    parser.add_argument("--publish-blocked", action="store_true")
    parser.add_argument("--no-publish-blocked", action="store_true")
    parser.add_argument("--history-limit", type=int)
    parser.add_argument("--history-lookback-days", type=int)
    parser.add_argument("--max-historical-queries", type=int)
    parser.add_argument("--max-historical-pages", type=int)
    parser.add_argument("--max-analogs", type=int)
    parser.add_argument("--minimum-analog-score", type=int)
    parser.add_argument("--customer-history", action="store_true")
    parser.add_argument("--no-customer-history", action="store_true")
    parser.add_argument("--supplier-history", action="store_true")
    parser.add_argument("--no-supplier-history", action="store_true")
    parser.add_argument("--find-no-participant-opportunities", action="store_true")
    parser.add_argument("--refresh-history", action="store_true")
    parser.add_argument("--offline-history-input")
    parser.add_argument("--published-within-days", type=int)
    parser.add_argument("--updated-within-days", type=int)
    parser.add_argument("--sort-by")
    parser.add_argument("--sort-direction", choices=["asc", "desc"])
    parser.add_argument("--verify-open-from-detail", action="store_true")
    parser.add_argument("--no-verify-open-from-detail", action="store_true")
    parser.add_argument("--minimum-open-target", type=int)
    parser.add_argument("--max-total-pages", type=int)
    parser.add_argument("--max-total-queries", type=int)
    parser.add_argument("--diagnose-search", action="store_true")
    parser.add_argument("--status-audit", action="store_true")
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--query-file")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    validate_live_history_args(
        history_only=args.history_only,
        allow_completed_source=args.allow_completed_source,
        procurement_numbers=args.procurement_number,
        source_url=args.source_url,
    )
    config = load_config(args.config)
    if args.output:
        config.radar.output_dir = args.output
    if args.db:
        config.radar.database = args.db
    if args.max_documents_per_procurement is not None:
        config.enrichment.max_documents_per_procurement = args.max_documents_per_procurement
    if args.max_total_download_mb is not None:
        config.enrichment.max_total_download_mb_per_run = args.max_total_download_mb
    if args.max_single_file_mb is not None:
        config.enrichment.max_single_file_mb = args.max_single_file_mb
    if args.discovery_mode:
        config.discovery.mode = args.discovery_mode
    if args.history:
        config.historical.enabled = True
    if args.no_history:
        config.historical.enabled = False
    if args.history_lookback_days is not None:
        config.historical.search.lookback_days = args.history_lookback_days
    if args.max_historical_queries is not None:
        config.historical.search.maximum_queries_per_procurement = args.max_historical_queries
    if args.max_historical_pages is not None:
        config.historical.search.maximum_pages_per_query = args.max_historical_pages
    if args.max_analogs is not None:
        config.historical.search.maximum_selected_analogs = args.max_analogs
    if args.minimum_analog_score is not None:
        config.historical.similarity.minimum_score = args.minimum_analog_score
    if args.customer_history:
        config.historical.customer_history.enabled = True
    if args.no_customer_history:
        config.historical.customer_history.enabled = False
    if args.supplier_history:
        config.historical.supplier_history.enabled = True
    if args.no_supplier_history:
        config.historical.supplier_history.enabled = False
    if args.published_within_days is not None:
        config.discovery.published_within_days = args.published_within_days
    if args.updated_within_days is not None:
        config.discovery.updated_within_days = args.updated_within_days
    if args.sort_by:
        config.discovery.sort["field"] = args.sort_by
    if args.sort_direction:
        config.discovery.sort["direction"] = args.sort_direction
    if args.verify_open_from_detail:
        config.discovery.verify_open_status_from_detail_page = True
    if args.no_verify_open_from_detail:
        config.discovery.verify_open_status_from_detail_page = False
    if args.minimum_open_target is not None:
        config.discovery.minimum_open_candidates_target = args.minimum_open_target
    if args.max_total_pages is not None:
        config.discovery.maximum_total_pages = args.max_total_pages
    if args.max_total_queries is not None:
        config.discovery.maximum_queries_per_run = args.max_total_queries
    if args.source_url:
        if len(args.procurement_number) != 1:
            raise ValueError("--source-url is valid only with exactly one --procurement-number")
        normalize_eis_url(args.source_url, args.procurement_number[0])

    profiles = select_profiles(load_search_profiles(), args.profile, args.all_profiles)
    as_of = parse_as_of(args.as_of, config.radar.timezone)
    started_at = datetime.now(as_of.tzinfo)
    run_id = started_at.strftime("%Y%m%d_%H%M%S")

    if args.enrichment_only:
        if not args.offline_input:
            raise ValueError("--enrichment-only currently requires --offline-input for card context")
    explicit_queries = list(args.query)
    if args.query_file:
        explicit_queries.extend(
            [
                line.strip()
                for line in Path(args.query_file).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        )
    source_resolution_diagnostics = None
    source_resolution_result = None
    if args.history_only and args.procurement_number and args.offline_input is None:
        if args.allow_completed_source:
            source_resolution_result = resolve_procurement_source(
                args.procurement_number[0],
                source_url=args.source_url,
                output_dir=config.radar.output_dir,
            )
            source_card = source_resolution_result.source_card or RadarCard(
                procurement_number=args.procurement_number[0],
                source_url=source_resolution_result.canonical_url or args.source_url or "",
                status_normalized="COMPLETED",
            )
            source_resolution_diagnostics = source_resolution_result.to_dict()
            source_card.discovered_at = started_at.isoformat(timespec="seconds")
            source_card.last_seen_at = started_at.isoformat(timespec="seconds")
            cards = [source_card]
        else:
            cards = [
                RadarCard(
                    procurement_number=number,
                    source_url=args.source_url or "",
                    discovered_at=started_at.isoformat(timespec="seconds"),
                    last_seen_at=started_at.isoformat(timespec="seconds"),
                )
                for number in args.procurement_number
            ]
        diagnostics = {"mode": "history-only", "discovery_mode": "OFFLINE", "raw_cards": len(cards), "unique_cards": len(cards), "errors": [], "search_diagnostics": [], "status_audit": [], "open_verifications": []}
        if source_resolution_diagnostics:
            diagnostics["source_resolution"] = source_resolution_diagnostics
    else:
        cards, diagnostics = discover_cards(
            config=config,
            profiles=profiles,
            offline_input=args.offline_input,
            limit=args.limit,
            max_pages=args.max_pages,
            as_of=as_of,
            discovery_mode=args.discovery_mode,
            explicit_queries=explicit_queries or None,
        )
    diagnostics["diagnose_search"] = args.diagnose_search
    diagnostics["status_audit_requested"] = args.status_audit
    diagnostics["dry_run"] = args.dry_run
    diagnostics["force_refresh"] = args.force_refresh

    state = None
    if args.dry_run and not Path(config.radar.database).exists():
        flags = {card.procurement_number: (True, False) for card in cards}
    else:
        state = RadarState(config.radar.database)
        flags = state.preview_flags(cards)
    assessments = []
    for card in cards:
        eligibility, days_left, eligibility_reasons = evaluate_eligibility(card, as_of, config, profiles)
        is_new, is_changed = flags.get(card.procurement_number, (True, False))
        assessments.append(
            assess_card(
                card,
                eligibility,
                days_left,
                config,
                profiles,
                is_new=is_new,
                is_changed=is_changed,
                eligibility_reasons=eligibility_reasons,
            )
        )

    historical_bundles = []
    live_validation_result = None
    if config.historical.enabled or args.history_only:
        if args.allow_completed_source:
            for assessment in assessments:
                exclude_validation_source_from_active_assessment(assessment)
            live_validation_result = run_live_historical_validation(
                cards[0],
                assessments[0],
                config,
                output_dir=Path(config.radar.output_dir),
                dry_run=args.dry_run,
                resume=args.resume_history,
                source_resolution=source_resolution_result,
            )
            historical_bundles = [live_validation_result.bundle]
            historical_diagnostics = dict(live_validation_result.diagnostics)
            historical_diagnostics["historical_live_validation"] = live_validation_result.to_dict()
        else:
            historical_bundles, historical_diagnostics = run_historical_for_cards(
                cards,
                assessments,
                config,
                offline_history_input=args.offline_history_input,
                history_limit=args.history_limit,
            )
        diagnostics.update(historical_diagnostics)
        diagnostics["historical"] = [bundle.to_dict() for bundle in historical_bundles]
        diagnostics["historical_enabled"] = True
    else:
        diagnostics["historical_enabled"] = False

    finished_at = datetime.now(as_of.tzinfo)
    enrichment_result = None
    should_enrich = (args.enrich or args.enrichment_only) and not args.no_enrich and not args.history_only
    if should_enrich:
        decisions = args.enrich_decisions.split(",") if args.enrich_decisions else None
        enrichment_result = run_enrichment(
            cards,
            assessments,
            config,
            state=state,
            offline_enrichment_input=args.offline_enrichment_input,
            download_dir=args.download_dir,
            analysis_dir=args.analysis_dir,
            dry_run=args.dry_run,
            skip_download=args.skip_download,
            skip_analysis=args.skip_analysis,
            refresh_enrichment=args.refresh_enrichment,
            decisions=decisions,
            total_limit=args.enrich_limit,
            priority_limit=args.priority_enrich_limit,
            review_limit=args.review_enrich_limit,
            procurement_numbers=args.procurement_number,
            source_url=args.source_url,
            force_enrich=args.force_enrich,
        )
        diagnostics.update(enrichment_result.diagnostics)
        diagnostics["enrichment_plan"] = enrichment_result.plan.to_dict()

    if not args.dry_run:
        if state is None:
            state = RadarState(config.radar.database)
        state_info = state.save_run(
            run_id=run_id,
            started_at=started_at.isoformat(timespec="seconds"),
            finished_at=finished_at.isoformat(timespec="seconds"),
            as_of=as_of.isoformat(timespec="seconds"),
            radar_version=radar_version,
            diagnostics=diagnostics,
                cards=cards,
                assessments=assessments,
                historical_bundles=historical_bundles,
            )
        diagnostics.update(state_info)
        if enrichment_result is not None:
            state.save_enrichment_run(
                enrichment_run_id=f"enrich_{run_id}",
                radar_run_id=run_id,
                started_at=started_at.isoformat(timespec="seconds"),
                finished_at=finished_at.isoformat(timespec="seconds"),
                requested_limit=args.enrich_limit or config.enrichment.total_limit_per_run,
                selected_count=len(enrichment_result.plan.selected),
                skipped_count=len(enrichment_result.plan.skipped),
                diagnostics=enrichment_result.diagnostics,
                config_snapshot=config.enrichment.__dict__,
                cards=cards,
                deep_assessments=enrichment_result.deep_assessments,
                artifacts=enrichment_result.artifacts,
            )
    else:
        diagnostics["state"] = "dry-run: SQLite was not modified"
    if state is not None:
        state.close()

    report_paths = write_reports(
        output_dir=Path(config.radar.output_dir),
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        as_of=as_of,
        profiles=[profile.name for profile in profiles],
        diagnostics=diagnostics,
        cards=cards,
        assessments=assessments,
        historical_bundles=historical_bundles,
        deep_assessments=enrichment_result.deep_assessments if enrichment_result else [],
        artifacts=enrichment_result.artifacts if enrichment_result else [],
        enrichment_plan=enrichment_result.plan.to_dict() if enrichment_result else None,
        dry_run=args.dry_run,
        publish_blocked=args.publish_blocked and not args.no_publish_blocked,
    )
    if args.verbose or args.dry_run:
        print(f"Radar {radar_version}: {len(cards)} unique cards, reports: {report_paths}")
        if args.dry_run:
            print("Dry run: state was not saved and latest.* was not overwritten.")
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
