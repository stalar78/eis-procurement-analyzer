from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from radar import radar_version
from radar.alerts import build_alert_feed
from radar.config import PROJECT_ROOT, load_config, normalize_runtime_paths
from radar.discovery import discover_cards
from radar.enrichment import run_enrichment
from radar.historical import run_historical_for_cards
from radar.historical_live_validation import (
    exclude_validation_source_from_active_assessment,
    run_live_historical_validation,
    validate_live_history_args,
)
from radar.live_collection import normalize_eis_url
from radar.models import EligibilityStatus, RadarAssessment, RadarCard, RadarDecision
from radar.orchestration import FAILURE_EXIT_CODE, LOCKED_EXIT_CODE, acquire_run_lock, retain_runtime_runs, RunLockedError
from radar.opportunities import assess_failed_opportunities, assess_failure_history
from radar.prefilter import evaluate_eligibility, parse_as_of
from radar.preflight import PREFLIGHT_EXIT_CODE, run_production_preflight
from radar.reporting import write_reports
from radar.scoring import assess_card
from radar.search_profiles import load_search_profiles, select_profiles
from radar.source_resolution import resolve_procurement_source
from radar.state import RadarState
from radar.telegram_delivery import deliver_alert_feed


HEALTHY_EXIT_CODE = 0
STALE_HEALTH_EXIT_CODE = 2
UNHEALTHY_EXIT_CODE = 3
DEFAULT_HEALTH_MAX_AGE_HOURS = 7.0
DEFAULT_HEALTH_MAX_RUN_HOURS = 12.0
KNOWN_LIFECYCLE_STATUSES = {"STARTED", "SUCCESS", "FAILED", "SKIPPED_LOCKED"}
UNHEALTHY_LATEST_STATUSES = {"FAILED", "SKIPPED_LOCKED"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EIS Procurement Radar Stage R1.")
    parser.add_argument("--config", default="config/radar.example.yaml")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
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
    parser.add_argument("--discovery-mode", choices=["ACTIVE_ONLY", "ACTIVE_AND_RECENT", "ALL_STATUSES", "COMPLETED_ONLY", "COMPLETED_AND_FAILED", "FAILED_ONLY", "FAILED_AND_COMPLETED", "CUSTOMER_HISTORY", "SUPPLIER_HISTORY"])
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
    parser.add_argument("--failed-opportunities", action="store_true")
    parser.add_argument("--no-failed-opportunities", action="store_true")
    parser.add_argument("--failure-history-only", action="store_true")
    parser.add_argument("--offline-failure-input")
    parser.add_argument("--max-failure-queries", type=int)
    parser.add_argument("--max-failure-pages", type=int)
    parser.add_argument("--max-failure-candidates", type=int)
    parser.add_argument("--max-republication-links", type=int)
    parser.add_argument("--minimum-opportunity-score", type=int)
    parser.add_argument("--refresh-failure-history", action="store_true")
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
    parser.add_argument("--recurring", action="store_true")
    parser.add_argument("--lock-stale-minutes", type=int)
    parser.add_argument("--retain-runs", type=int)
    parser.add_argument("--retain-failed-runs", type=int)
    parser.add_argument("--send-telegram-alerts", action="store_true")
    parser.add_argument("--no-send-telegram-alerts", action="store_true")
    parser.add_argument("--telegram-bot-token")
    parser.add_argument("--telegram-chat-id")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--health-max-age-hours", type=float, default=DEFAULT_HEALTH_MAX_AGE_HOURS)
    parser.add_argument("--health-max-run-hours", type=float, default=DEFAULT_HEALTH_MAX_RUN_HOURS)
    return parser.parse_args(argv)


def _open_lifecycle_readonly(database: str) -> sqlite3.Connection | None:
    path = Path(database)
    if not path.exists():
        return None
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _parse_lifecycle_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, str]:
    return dict(row) if row is not None else {}


def _age_hours(now: datetime, earlier: datetime) -> float:
    if earlier.tzinfo is None and now.tzinfo is not None:
        earlier = earlier.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - earlier).total_seconds() / 3600)


def _valid_positive_finite(value: float) -> bool:
    return math.isfinite(value) and value > 0


def evaluate_health(database: str, *, now: datetime, max_age_hours: float, max_run_hours: float) -> dict[str, object]:
    connection = _open_lifecycle_readonly(database)
    if connection is None:
        return {
            "health_status": "UNHEALTHY",
            "reason": "database not found",
            "latest": {},
            "last_success": {},
            "last_success_age_hours": None,
            "latest_started_age_hours": None,
        }
    try:
        latest = connection.execute("SELECT * FROM recurring_run_lifecycle ORDER BY id DESC LIMIT 1").fetchone()
        last_success = connection.execute("SELECT * FROM recurring_run_lifecycle WHERE status = 'SUCCESS' ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.Error as error:
        return {
            "health_status": "UNHEALTHY",
            "reason": f"lifecycle unavailable: {error}",
            "latest": {},
            "last_success": {},
            "last_success_age_hours": None,
            "latest_started_age_hours": None,
        }
    finally:
        connection.close()

    if last_success is None:
        return {
            "health_status": "UNHEALTHY",
            "reason": "no successful recurring run recorded",
            "latest": _row_to_dict(latest),
            "last_success": {},
            "last_success_age_hours": None,
            "latest_started_age_hours": None,
        }

    latest_status = str(latest["status"] if latest else "")
    if latest_status not in KNOWN_LIFECYCLE_STATUSES:
        return {
            "health_status": "UNHEALTHY",
            "reason": f"unknown latest lifecycle status: {latest_status or 'NONE'}",
            "latest": _row_to_dict(latest),
            "last_success": _row_to_dict(last_success),
            "last_success_age_hours": None,
            "latest_started_age_hours": None,
        }

    success_time = _parse_lifecycle_time(last_success["finished_at"] or last_success["started_at"])
    if success_time is None:
        return {
            "health_status": "UNHEALTHY",
            "reason": "last successful run timestamp is invalid",
            "latest": _row_to_dict(latest),
            "last_success": _row_to_dict(last_success),
            "last_success_age_hours": None,
            "latest_started_age_hours": None,
        }
    success_age_hours = _age_hours(now, success_time)

    latest_started_age_hours = None
    if latest_status == "STARTED":
        started_time = _parse_lifecycle_time(latest["started_at"])
        if started_time is None:
            health_status = "UNHEALTHY"
            reason = "latest STARTED timestamp is invalid"
        else:
            latest_started_age_hours = _age_hours(now, started_time)
            if latest_started_age_hours > max_run_hours:
                health_status = "UNHEALTHY"
                reason = "latest STARTED run exceeded max run duration"
            elif success_age_hours > max_age_hours:
                health_status = "STALE"
                reason = "last successful recurring run is stale"
            else:
                health_status = "HEALTHY"
                reason = "last successful recurring run is fresh"
    elif latest_status in UNHEALTHY_LATEST_STATUSES:
        health_status = "UNHEALTHY"
        reason = f"latest lifecycle status is {latest_status}"
    elif success_age_hours > max_age_hours:
        health_status = "STALE"
        reason = "last successful recurring run is stale"
    else:
        health_status = "HEALTHY"
        reason = "last successful recurring run is fresh"
    return {
        "health_status": health_status,
        "reason": reason,
        "latest": _row_to_dict(latest),
        "last_success": _row_to_dict(last_success),
        "last_success_age_hours": round(success_age_hours, 2),
        "latest_started_age_hours": round(latest_started_age_hours, 2) if latest_started_age_hours is not None else None,
    }


def print_health_report(report: dict[str, object], *, max_age_hours: float, max_run_hours: float) -> None:
    latest = report.get("latest") or {}
    last_success = report.get("last_success") or {}
    latest_status = latest.get("status", "NONE") if isinstance(latest, dict) else "NONE"
    latest_run_id = latest.get("run_id", "") if isinstance(latest, dict) else ""
    success_at = ""
    if isinstance(last_success, dict):
        success_at = last_success.get("finished_at") or last_success.get("started_at") or ""
    age = report.get("last_success_age_hours")
    age_text = "unknown" if age is None else f"{age}h"
    print(f"Radar health: {report['health_status']}")
    print(f"Latest lifecycle: {latest_status} {latest_run_id}".rstrip())
    print(f"Last success: {success_at or 'NONE'} age={age_text} max_age_hours={max_age_hours}")
    started_age = report.get("latest_started_age_hours")
    if started_age is not None:
        print(f"Latest STARTED age: {started_age}h max_run_hours={max_run_hours}")
    print(f"Reason: {report['reason']}")


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.production and args.config == "config/radar.example.yaml":
        args.config = str(PROJECT_ROOT / "config" / "radar.production.yaml")
    if args.production:
        args.recurring = True
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
    if args.lock_stale_minutes is not None:
        config.recurring.lock_stale_after_minutes = args.lock_stale_minutes
    if args.retain_runs is not None:
        config.recurring.retain_successful_runs = args.retain_runs
    if args.retain_failed_runs is not None:
        config.recurring.retain_failed_runs = args.retain_failed_runs
    if args.send_telegram_alerts:
        config.telegram.enabled = True
    if args.no_send_telegram_alerts:
        config.telegram.enabled = False
    if args.telegram_bot_token:
        config.telegram.bot_token = args.telegram_bot_token
    if args.telegram_chat_id:
        config.telegram.chat_id = args.telegram_chat_id
    if args.health:
        if args.production:
            normalize_runtime_paths(config, PROJECT_ROOT)
        if not _valid_positive_finite(args.health_max_age_hours):
            print("Health check failed: --health-max-age-hours must be a finite value > 0")
            return UNHEALTHY_EXIT_CODE
        if not _valid_positive_finite(args.health_max_run_hours):
            print("Health check failed: --health-max-run-hours must be a finite value > 0")
            return UNHEALTHY_EXIT_CODE
        now = datetime.now().astimezone()
        report = evaluate_health(
            config.radar.database,
            now=now,
            max_age_hours=args.health_max_age_hours,
            max_run_hours=args.health_max_run_hours,
        )
        print_health_report(
            report,
            max_age_hours=args.health_max_age_hours,
            max_run_hours=args.health_max_run_hours,
        )
        if report["health_status"] == "HEALTHY":
            return HEALTHY_EXIT_CODE
        if report["health_status"] == "STALE":
            return STALE_HEALTH_EXIT_CODE
        return UNHEALTHY_EXIT_CODE
    if args.production or args.preflight_only:
        normalize_runtime_paths(config, PROJECT_ROOT)
        preflight = run_production_preflight(args.config, config)
        if not preflight.ok:
            if args.verbose or args.preflight_only:
                for error in preflight.sanitized_errors():
                    print(f"Preflight failed: {error}")
            return PREFLIGHT_EXIT_CODE
        if args.preflight_only:
            if args.verbose:
                print("Preflight OK")
            return 0
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
    if args.failed_opportunities:
        config.opportunities.enabled = True
    if args.no_failed_opportunities:
        config.opportunities.enabled = False
    if args.failure_history_only:
        config.opportunities.enabled = True
    if args.max_failure_queries is not None:
        config.opportunities.failure_history.maximum_queries_per_procurement = args.max_failure_queries
    if args.max_failure_pages is not None:
        config.opportunities.failure_history.maximum_pages_per_query = args.max_failure_pages
    if args.max_failure_candidates is not None:
        config.opportunities.failure_history.maximum_candidates = args.max_failure_candidates
    if args.max_republication_links is not None:
        config.opportunities.failure_history.maximum_result_resolutions = args.max_republication_links
    if args.minimum_opportunity_score is not None:
        config.opportunities.scoring.minimum_opportunity_score = args.minimum_opportunity_score
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
    if args.recurring:
        run_id = started_at.strftime("%Y%m%d_%H%M%S_%f")
    run_lock = None
    if args.recurring and not args.dry_run:
        state_for_lifecycle = RadarState(config.radar.database)
        try:
            run_lock = acquire_run_lock(
                config.radar.output_dir,
                run_id,
                started_at,
                config.recurring.lock_stale_after_minutes,
            )
        except RunLockedError as exc:
            finished_at = datetime.now(as_of.tzinfo)
            state_for_lifecycle.record_run_lifecycle(
                run_id=run_id,
                status="SKIPPED_LOCKED",
                started_at=started_at.isoformat(timespec="seconds"),
                finished_at=finished_at.isoformat(timespec="seconds"),
                failure_reason="active recurring run lock",
                lock_path=str(exc.lock_path),
                diagnostics={"existing_lock": exc.metadata},
            )
            state_for_lifecycle.close()
            if args.verbose:
                print(f"Radar {radar_version}: skipped, active lock at {exc.lock_path}")
            return LOCKED_EXIT_CODE
        state_for_lifecycle.record_run_lifecycle(
            run_id=run_id,
            status="STARTED",
            started_at=started_at.isoformat(timespec="seconds"),
            lock_path=str(run_lock.path),
            diagnostics={"stale_lock_recovered": run_lock.stale_recovered},
        )
        state_for_lifecycle.close()

    try:
        exit_code = _run_pipeline(args, config, profiles, as_of, started_at, run_id, run_lock.stale_recovered if run_lock else False)
        if args.recurring and not args.dry_run:
            finished_at = datetime.now(as_of.tzinfo)
            state_for_lifecycle = RadarState(config.radar.database)
            state_for_lifecycle.record_run_lifecycle(
                run_id=run_id,
                status="SUCCESS",
                started_at=started_at.isoformat(timespec="seconds"),
                finished_at=finished_at.isoformat(timespec="seconds"),
                lock_path=str(run_lock.path) if run_lock else "",
                diagnostics={"stale_lock_recovered": run_lock.stale_recovered if run_lock else False},
            )
            state_for_lifecycle.close()
            retention = retain_runtime_runs(
                config.radar.output_dir,
                config.recurring.retain_successful_runs,
                config.recurring.retain_failed_runs,
            )
            if args.verbose and any(retention.values()):
                print(f"Radar {radar_version}: retention removed {retention}")
        return exit_code
    except Exception as exc:
        if args.recurring and not args.dry_run:
            finished_at = datetime.now(as_of.tzinfo)
            state_for_lifecycle = RadarState(config.radar.database)
            state_for_lifecycle.record_run_lifecycle(
                run_id=run_id,
                status="FAILED",
                started_at=started_at.isoformat(timespec="seconds"),
                finished_at=finished_at.isoformat(timespec="seconds"),
                failure_reason=f"{type(exc).__name__}: {exc}",
                lock_path=str(run_lock.path) if run_lock else "",
            )
            state_for_lifecycle.close()
            if args.verbose:
                print(f"Radar {radar_version}: failed: {type(exc).__name__}: {exc}")
            return FAILURE_EXIT_CODE
        raise
    finally:
        if run_lock:
            run_lock.release()


def _run_pipeline(args: argparse.Namespace, config, profiles, as_of: datetime, started_at: datetime, run_id: str, stale_lock_recovered: bool) -> int:
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
    diagnostics["recurring"] = bool(args.recurring)
    diagnostics["stale_lock_recovered"] = stale_lock_recovered

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
    opportunities = []
    opportunity_result = None
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

    failure_history_live_results = []
    if (config.opportunities.enabled or args.failure_history_only) and cards:
        previous_opportunities = {}
        if state is not None:
            previous_opportunities = {
                card.procurement_number: stored
                for card in cards
                if (stored := state.get_opportunity(card.procurement_number)) is not None
            }
        opportunity_result = assess_failed_opportunities(
            cards,
            assessments,
            config,
            offline_failure_input=args.offline_failure_input,
            previous_opportunities=previous_opportunities,
        )
        opportunities = opportunity_result.opportunities
        diagnostics["opportunities"] = opportunity_result.to_dict()
    elif config.opportunities.enabled or args.failure_history_only:
        diagnostics["failed_opportunity_fallback_reason"] = "NO_CURRENT_OPEN_CARDS_AFTER_ACTIVE_VERIFICATION"
        fallback_card = next((card for card in cards if card.status_normalized == "COMPLETED"), None) or (cards[0] if cards else None)
        if fallback_card is None:
            fallback_query = ""
            if diagnostics.get("search_diagnostics"):
                fallback_query = diagnostics["search_diagnostics"][0].get("query", "")
            if not fallback_query and explicit_queries:
                fallback_query = explicit_queries[0]
            if not fallback_query and profiles:
                fallback_query = profiles[0].queries[0] if profiles[0].queries else ""
            fallback_card = RadarCard(
                procurement_number="R3B1_HISTORICAL_SEED",
                title=fallback_query,
                customer="",
                law="",
                published_at=started_at.isoformat(timespec="seconds"),
                status_normalized="COMPLETED",
                raw_text=fallback_query,
            )
        fallback_assessment = next((assessment for assessment in assessments if assessment.procurement_number == getattr(fallback_card, "procurement_number", "")), None)
        if fallback_assessment is None:
            fallback_assessment = RadarAssessment(
                procurement_number=fallback_card.procurement_number,
                eligibility_status=EligibilityStatus.CLOSED,
                days_to_deadline=None,
                total_score=0,
                radar_decision=RadarDecision.INSUFFICIENT_DATA,
            )
        if fallback_card is not None and fallback_assessment is not None:
            fallback = assess_failure_history(
                fallback_card,
                fallback_assessment,
                config,
                as_of=as_of,
                offline_failure_input=args.offline_failure_input,
            )
            failure_history_live_results.append(fallback)
            diagnostics["failure_discovery"] = fallback.to_dict()

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
        if opportunity_result is not None:
            from radar import opportunity_intelligence_version

            opportunity_change_feed = state.save_opportunity_assessment(
                algorithm_version=opportunity_intelligence_version,
                failure_events=opportunity_result.failure_events,
                republication_links=opportunity_result.republication_links,
                opportunities=opportunities,
                transitions=opportunity_result.transitions,
                detected_at=finished_at.isoformat(timespec="seconds"),
                active_procurement_numbers=[card.procurement_number for card in cards],
            )
            diagnostics.setdefault("change_feed", []).extend(opportunity_change_feed)
        alert_feed = build_alert_feed(
            diagnostics.get("change_feed", []),
            cards,
            assessments,
            config,
            as_of,
        )
        diagnostics["alert_feed"] = state.save_alert_history(run_id, alert_feed)
        diagnostics["telegram_delivery"] = deliver_alert_feed(
            diagnostics["alert_feed"],
            config.telegram,
            state,
            run_id=run_id,
        )
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
        opportunities=opportunities,
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
