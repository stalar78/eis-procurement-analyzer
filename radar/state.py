from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from radar.models import ArtifactRecord, ChangeFeedEvent, DeepAssessment, EnrichmentStatus, NoCompetitionOpportunity, OpportunityTransition, ProcurementFailureEvent, RadarAssessment, RadarCard, RepeatedProcurementLink


TRACKED_FIELDS = {
    "title": "title",
    "customer": "customer",
    "nmck": "nmck",
    "deadline": "application_deadline",
    "status": "status_normalized",
    "source_url": "source_url",
    "updated_at": "updated_at",
}
ASSESSMENT_TRACKED_FIELDS = {
    "preliminary_score": "total_score",
    "preliminary_decision": "radar_decision",
    "history_adjusted_score": "history_adjusted_score",
    "history_adjusted_decision": "history_adjusted_decision",
}


def _string_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    if value is None:
        return ""
    return str(value)


def _event_type_for_field(field_name: str) -> str:
    mapping = {
        "deadline": "DEADLINE_CHANGED",
        "nmck": "NMCK_CHANGED",
        "status": "STATUS_CHANGED",
        "preliminary_score": "PRELIMINARY_SCORE_CHANGED",
        "preliminary_decision": "PRELIMINARY_DECISION_CHANGED",
        "history_adjusted_score": "HISTORY_SCORE_CHANGED",
        "history_adjusted_decision": "HISTORY_DECISION_CHANGED",
        "opportunity_score": "OPPORTUNITY_SCORE_CHANGED",
        "opportunity_level": "OPPORTUNITY_DECISION_CHANGED",
    }
    return mapping.get(field_name, "PROCUREMENT_CHANGED")


def _severity_for_event(event_type: str) -> str:
    if event_type in {"PROCUREMENT_CLOSED", "OPPORTUNITY_NO_LONGER_ACTIVE"}:
        return "WARNING"
    if event_type in {"NEW_PROCUREMENT", "NEW_OPPORTUNITY"}:
        return "INFO"
    return "NOTICE"


class RadarState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        cur = self.connection.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS radar_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT,
                finished_at TEXT,
                as_of TEXT,
                radar_version TEXT,
                diagnostics_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS recurring_run_lifecycle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                status TEXT,
                started_at TEXT,
                finished_at TEXT,
                failure_reason TEXT,
                lock_path TEXT,
                diagnostics_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_history (
                alert_fingerprint TEXT PRIMARY KEY,
                procurement_number TEXT,
                alert_type TEXT,
                alert_priority TEXT,
                detected_at TEXT,
                run_id TEXT,
                alert_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_delivery_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_fingerprint TEXT,
                channel TEXT,
                chat_id TEXT,
                status TEXT,
                attempted_at TEXT,
                delivered_at TEXT,
                run_id TEXT,
                attempt_count INTEGER,
                error_message TEXT,
                response_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_delivery_chunks (
                chunk_key TEXT PRIMARY KEY,
                alert_fingerprint TEXT,
                channel TEXT,
                chat_id TEXT,
                chunk_index INTEGER,
                chunk_count INTEGER,
                status TEXT,
                attempted_at TEXT,
                delivered_at TEXT,
                run_id TEXT,
                error_message TEXT,
                response_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS procurements (
                procurement_number TEXT PRIMARY KEY,
                current_json TEXT NOT NULL,
                first_seen_at TEXT,
                last_seen_at TEXT,
                last_changed_at TEXT,
                fingerprint TEXT,
                current_decision TEXT,
                current_score INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS procurement_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                procurement_number TEXT,
                observed_at TEXT,
                raw_snapshot_json TEXT,
                fingerprint TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS procurement_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                procurement_number TEXT,
                profile TEXT,
                query TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                procurement_number TEXT,
                assessment_json TEXT,
                decision TEXT,
                total_score INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                procurement_number TEXT,
                detected_at TEXT,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                change_type TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS enrichment_runs (
                enrichment_run_id TEXT PRIMARY KEY,
                radar_run_id TEXT,
                started_at TEXT,
                finished_at TEXT,
                requested_limit INTEGER,
                selected_count INTEGER,
                completed_count INTEGER,
                failed_count INTEGER,
                skipped_count INTEGER,
                downloaded_bytes INTEGER,
                status TEXT,
                config_snapshot_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS procurement_enrichment (
                procurement_number TEXT PRIMARY KEY,
                enrichment_status TEXT,
                latest_attempt_id TEXT,
                first_enriched_at TEXT,
                last_enriched_at TEXT,
                next_retry_at TEXT,
                attempt_count INTEGER,
                source_fingerprint TEXT,
                document_set_fingerprint TEXT,
                analysis_fingerprint TEXT,
                deep_assessment_version TEXT,
                latest_error_code TEXT,
                latest_error_message TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS enrichment_attempts (
                attempt_id TEXT PRIMARY KEY,
                enrichment_run_id TEXT,
                procurement_number TEXT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT,
                error_code TEXT,
                error_message TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS procurement_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                procurement_number TEXT,
                artifact_type TEXT,
                source_url TEXT,
                local_path TEXT,
                original_filename TEXT,
                content_type TEXT,
                size_bytes INTEGER,
                sha256 TEXT,
                downloaded_at TEXT,
                extraction_status TEXT,
                document_type TEXT,
                document_confidence TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS deep_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enrichment_run_id TEXT,
                procurement_number TEXT,
                deep_assessment_json TEXT,
                final_decision TEXT,
                deep_score INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS deep_assessment_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enrichment_run_id TEXT,
                procurement_number TEXT,
                evidence_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_search_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT,
                radar_version TEXT,
                diagnostics_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                procurement_number TEXT,
                query_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                procurement_number TEXT,
                candidate_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_analogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                procurement_number TEXT,
                analog_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_result_metrics (
                procurement_number TEXT PRIMARY KEY,
                metrics_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_history_profiles (
                procurement_number TEXT PRIMARY KEY,
                profile_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS supplier_history_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                procurement_number TEXT,
                profile_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS competition_assessments (
                procurement_number TEXT PRIMARY KEY,
                assessment_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS repeated_procurement_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                procurement_number TEXT,
                link_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_resolution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                procurement_number TEXT,
                resolved_at TEXT,
                status TEXT,
                strategy_used TEXT,
                canonical_url TEXT,
                confidence TEXT,
                attempts_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_snapshots (
                procurement_number TEXT PRIMARY KEY,
                last_successful_source_url TEXT,
                source_page_type TEXT,
                last_successful_fetch_time TEXT,
                content_fingerprint TEXT,
                normalized_title TEXT,
                customer TEXT,
                nmck REAL,
                status TEXT,
                source_snapshot_path TEXT,
                latest_known_validation_status TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS successful_live_validations (
                run_id TEXT PRIMARY KEY,
                procurement_number TEXT,
                created_at TEXT,
                run_quality_status TEXT,
                diagnostics_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS procurement_failure_events (
                procurement_number TEXT PRIMARY KEY,
                detected_at TEXT,
                failure_type TEXT,
                evidence_confidence TEXT,
                algorithm_version TEXT,
                event_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS republication_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                current_procurement_number TEXT,
                previous_procurement_number TEXT,
                relation_type TEXT,
                relation_score INTEGER,
                confidence TEXT,
                algorithm_version TEXT,
                link_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunity_assessments (
                current_procurement_number TEXT PRIMARY KEY,
                previous_procurement_number TEXT,
                opportunity_score INTEGER,
                opportunity_level TEXT,
                detected_at TEXT,
                algorithm_version TEXT,
                opportunity_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunity_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                procurement_number TEXT,
                transition_type TEXT,
                previous_value TEXT,
                current_value TEXT,
                detected_at TEXT
            )
            """
        )
        self.connection.commit()

    def record_run_lifecycle(
        self,
        *,
        run_id: str,
        status: str,
        started_at: str,
        finished_at: str = "",
        failure_reason: str = "",
        lock_path: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO recurring_run_lifecycle
            (run_id, status, started_at, finished_at, failure_reason, lock_path, diagnostics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                status,
                started_at,
                finished_at,
                failure_reason,
                lock_path,
                json.dumps(diagnostics or {}, ensure_ascii=False),
            ),
        )
        self.connection.commit()

    def get_run_lifecycle(self, run_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM recurring_run_lifecycle WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()

    def get_alert_fingerprint(self, fingerprint: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM alert_history WHERE alert_fingerprint = ?",
            (fingerprint,),
        ).fetchone()

    def save_alert_history(self, run_id: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cur = self.connection.cursor()
        emitted: list[dict[str, Any]] = []
        for alert in alerts:
            fingerprint = alert.get("fingerprint") or ""
            if not fingerprint:
                continue
            if self.get_alert_fingerprint(fingerprint) is not None:
                continue
            cur.execute(
                """
                INSERT OR REPLACE INTO alert_history
                (alert_fingerprint, procurement_number, alert_type, alert_priority, detected_at, run_id, alert_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    alert.get("procurement_number", ""),
                    alert.get("alert_type", ""),
                    alert.get("alert_priority", ""),
                    alert.get("detected_at", ""),
                    run_id,
                    json.dumps(alert, ensure_ascii=False),
                ),
            )
            emitted.append(alert)
        self.connection.commit()
        return emitted

    def was_alert_delivered(self, alert_fingerprint: str, channel: str, chat_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM alert_delivery_attempts
            WHERE alert_fingerprint = ? AND channel = ? AND chat_id = ? AND status = 'SENT'
            LIMIT 1
            """,
            (alert_fingerprint, channel, chat_id),
        ).fetchone()
        return row is not None

    def record_alert_delivery(
        self,
        *,
        alert_fingerprint: str,
        channel: str,
        chat_id: str,
        status: str,
        attempted_at: str,
        delivered_at: str = "",
        run_id: str = "",
        attempt_count: int = 0,
        error_message: str = "",
        response: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO alert_delivery_attempts
            (alert_fingerprint, channel, chat_id, status, attempted_at, delivered_at,
             run_id, attempt_count, error_message, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_fingerprint,
                channel,
                chat_id,
                status,
                attempted_at,
                delivered_at,
                run_id,
                attempt_count,
                error_message,
                json.dumps(response or {}, ensure_ascii=False),
            ),
        )
        self.connection.commit()

    def was_alert_chunk_delivered(self, chunk_key: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM alert_delivery_chunks WHERE chunk_key = ? AND status = 'SENT' LIMIT 1",
            (chunk_key,),
        ).fetchone()
        return row is not None

    def record_alert_chunk_delivery(
        self,
        *,
        chunk_key: str,
        alert_fingerprint: str,
        channel: str,
        chat_id: str,
        chunk_index: int,
        chunk_count: int,
        status: str,
        attempted_at: str,
        delivered_at: str = "",
        run_id: str = "",
        error_message: str = "",
        response: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO alert_delivery_chunks
            (chunk_key, alert_fingerprint, channel, chat_id, chunk_index, chunk_count,
             status, attempted_at, delivered_at, run_id, error_message, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_key,
                alert_fingerprint,
                channel,
                chat_id,
                chunk_index,
                chunk_count,
                status,
                attempted_at,
                delivered_at,
                run_id,
                error_message,
                json.dumps(response or {}, ensure_ascii=False),
            ),
        )
        self.connection.commit()

    def get_current(self, procurement_number: str) -> sqlite3.Row | None:
        cur = self.connection.execute(
            "SELECT * FROM procurements WHERE procurement_number = ?",
            (procurement_number,),
        )
        return cur.fetchone()

    def preview_flags(self, cards: list[RadarCard]) -> dict[str, tuple[bool, bool]]:
        flags: dict[str, tuple[bool, bool]] = {}
        for card in cards:
            row = self.get_current(card.procurement_number)
            if row is None:
                flags[card.procurement_number] = (True, False)
            else:
                flags[card.procurement_number] = (False, row["fingerprint"] != card.source_fingerprint)
        return flags

    def _insert_change_event(
        self,
        cur: sqlite3.Cursor,
        *,
        procurement_number: str,
        detected_at: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
        change_type: str,
    ) -> ChangeFeedEvent:
        event_type = change_type if change_type.isupper() else _event_type_for_field(field_name)
        event = ChangeFeedEvent(
            procurement_number=procurement_number,
            event_type=event_type,
            detected_at=detected_at,
            field_name=field_name,
            previous_value=_string_value(old_value),
            current_value=_string_value(new_value),
            severity=_severity_for_event(event_type),
            source="procurement_state",
            explanation=f"{field_name} changed from {_string_value(old_value)!r} to {_string_value(new_value)!r}",
        )
        cur.execute(
            """
            INSERT INTO changes
            (procurement_number, detected_at, field_name, old_value, new_value, change_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.procurement_number,
                event.detected_at,
                event.field_name,
                event.previous_value,
                event.current_value,
                event.event_type,
            ),
        )
        return event

    def _closed_missing_procurements(self, current_numbers: set[str], finished_at: str) -> list[ChangeFeedEvent]:
        cur = self.connection.cursor()
        events: list[ChangeFeedEvent] = []
        rows = cur.execute("SELECT procurement_number, current_json FROM procurements").fetchall()
        for row in rows:
            if row["procurement_number"] in current_numbers:
                continue
            payload = json.loads(row["current_json"])
            previous_status = _string_value(payload.get("status_normalized"))
            if previous_status.upper() in {"COMPLETED", "CANCELLED", "CONTRACT_SIGNED"}:
                continue
            events.append(
                self._insert_change_event(
                    cur,
                    procurement_number=row["procurement_number"],
                    detected_at=finished_at,
                    field_name="open_state",
                    old_value=previous_status or "previously_seen",
                    new_value="not_observed_in_current_run",
                    change_type="PROCUREMENT_CLOSED",
                )
            )
        return events

    def enrichment_cache_skip_reason(
        self,
        procurement_number: str,
        source_fingerprint: str,
        refresh_after_hours: int,
        as_of: Any = None,
    ) -> str:
        row = self.connection.execute(
            "SELECT * FROM procurement_enrichment WHERE procurement_number = ?",
            (procurement_number,),
        ).fetchone()
        if not row:
            return ""
        if row["enrichment_status"] != EnrichmentStatus.COMPLETE.value:
            return ""
        if row["source_fingerprint"] != source_fingerprint:
            return ""
        last = row["last_enriched_at"]
        if not last:
            return ""
        try:
            from datetime import datetime, timedelta

            last_dt = datetime.fromisoformat(last)
            now = as_of or datetime.now(last_dt.tzinfo)
            if now.tzinfo is None and last_dt.tzinfo is not None:
                now = now.replace(tzinfo=last_dt.tzinfo)
            if now - last_dt < timedelta(hours=refresh_after_hours):
                return "cached complete enrichment is still fresh"
        except ValueError:
            return ""
        return ""

    def save_run(
        self,
        run_id: str,
        started_at: str,
        finished_at: str,
        as_of: str,
        radar_version: str,
        diagnostics: dict[str, Any],
        cards: list[RadarCard],
        assessments: list[RadarAssessment],
        historical_bundles: list[Any] | None = None,
    ) -> dict[str, Any]:
        cur = self.connection.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO radar_runs VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, started_at, finished_at, as_of, radar_version, json.dumps(diagnostics, ensure_ascii=False)),
        )
        changes_count = 0
        change_feed: list[ChangeFeedEvent] = []
        assessment_by_number = {item.procurement_number: item for item in assessments}
        current_numbers = {card.procurement_number for card in cards}
        for card in cards:
            assessment = assessment_by_number.get(card.procurement_number)
            existing = self.get_current(card.procurement_number)
            is_new = existing is None
            old_json = json.loads(existing["current_json"]) if existing else {}
            is_changed = bool(existing and existing["fingerprint"] != card.source_fingerprint)
            old_assessment = None
            if existing:
                old_assessment = self.connection.execute(
                    """
                    SELECT assessment_json FROM assessments
                    WHERE procurement_number = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (card.procurement_number,),
                ).fetchone()
            old_assessment_json = json.loads(old_assessment["assessment_json"]) if old_assessment else {}

            cur.execute(
                """
                INSERT INTO procurement_observations
                (run_id, procurement_number, observed_at, raw_snapshot_json, fingerprint)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    card.procurement_number,
                    card.last_seen_at,
                    json.dumps(card.to_dict(), ensure_ascii=False),
                    card.source_fingerprint,
                ),
            )
            for query in card.search_queries:
                for profile in card.search_profiles or [""]:
                    cur.execute(
                        "INSERT INTO procurement_queries (run_id, procurement_number, profile, query) VALUES (?, ?, ?, ?)",
                        (run_id, card.procurement_number, profile, query),
                    )

            if is_new:
                change_feed.append(
                    self._insert_change_event(
                        cur,
                        procurement_number=card.procurement_number,
                        detected_at=finished_at,
                        field_name="procurement",
                        old_value="",
                        new_value=card.procurement_number,
                        change_type="NEW_PROCUREMENT",
                    )
                )
                changes_count += 1
            if is_changed:
                for display_name, attr in TRACKED_FIELDS.items():
                    old_value = old_json.get(attr)
                    new_value = getattr(card, attr)
                    if _string_value(old_value) != _string_value(new_value):
                        change_feed.append(
                            self._insert_change_event(
                                cur,
                                procurement_number=card.procurement_number,
                                detected_at=finished_at,
                                field_name=display_name,
                                old_value=old_value,
                                new_value=new_value,
                                change_type="updated",
                            )
                        )
                        changes_count += 1
            if assessment and old_assessment_json:
                for display_name, attr in ASSESSMENT_TRACKED_FIELDS.items():
                    old_value = old_assessment_json.get(attr)
                    new_value = getattr(assessment, attr)
                    if _string_value(old_value) != _string_value(new_value):
                        change_feed.append(
                            self._insert_change_event(
                                cur,
                                procurement_number=card.procurement_number,
                                detected_at=finished_at,
                                field_name=display_name,
                                old_value=old_value,
                                new_value=new_value,
                                change_type="updated",
                            )
                        )
                        changes_count += 1

            first_seen_at = card.discovered_at if is_new else existing["first_seen_at"]
            last_changed_at = finished_at if is_new or is_changed else existing["last_changed_at"]
            cur.execute(
                """
                INSERT OR REPLACE INTO procurements
                (procurement_number, current_json, first_seen_at, last_seen_at, last_changed_at,
                 fingerprint, current_decision, current_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.procurement_number,
                    json.dumps(card.to_dict(), ensure_ascii=False),
                    first_seen_at,
                    card.last_seen_at,
                    last_changed_at,
                    card.source_fingerprint,
                    assessment.radar_decision.value if assessment else "",
                    assessment.total_score if assessment else None,
                ),
            )
            if assessment:
                cur.execute(
                    """
                    INSERT INTO assessments
                    (run_id, procurement_number, assessment_json, decision, total_score)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        card.procurement_number,
                        json.dumps(assessment.to_dict(), ensure_ascii=False),
                        assessment.radar_decision.value,
                        assessment.total_score,
                    ),
                )
        for bundle in historical_bundles or []:
            cur.execute(
                "INSERT OR REPLACE INTO historical_result_metrics VALUES (?, ?)",
                (bundle.procurement_number, json.dumps(bundle.competition_metrics.to_dict(), ensure_ascii=False)),
            )
            if bundle.customer_history:
                cur.execute(
                    "INSERT OR REPLACE INTO customer_history_profiles VALUES (?, ?)",
                    (bundle.procurement_number, json.dumps(bundle.customer_history.to_dict(), ensure_ascii=False)),
                )
            for supplier in bundle.supplier_history:
                cur.execute(
                    "INSERT INTO supplier_history_profiles (procurement_number, profile_json) VALUES (?, ?)",
                    (bundle.procurement_number, json.dumps(supplier.to_dict(), ensure_ascii=False)),
                )
            cur.execute(
                "INSERT OR REPLACE INTO competition_assessments VALUES (?, ?)",
                (bundle.procurement_number, json.dumps(bundle.dumping_risk_assessment.to_dict(), ensure_ascii=False)),
            )
            for link in bundle.repeated_procurements:
                cur.execute(
                    "INSERT INTO repeated_procurement_links (procurement_number, link_json) VALUES (?, ?)",
                    (bundle.procurement_number, json.dumps(link.to_dict(), ensure_ascii=False)),
                )
        cur.execute(
            "INSERT OR REPLACE INTO historical_search_runs VALUES (?, ?, ?, ?)",
            (
                run_id,
                finished_at,
                radar_version,
                json.dumps(diagnostics, ensure_ascii=False),
            ),
        )
        closed_events = self._closed_missing_procurements(current_numbers, finished_at)
        change_feed.extend(closed_events)
        changes_count += len(closed_events)
        self.connection.commit()
        return {
            "changes_recorded": changes_count,
            "change_feed": [event.to_dict() for event in change_feed],
        }

    def save_enrichment_run(
        self,
        enrichment_run_id: str,
        radar_run_id: str,
        started_at: str,
        finished_at: str,
        requested_limit: int,
        selected_count: int,
        skipped_count: int,
        diagnostics: dict[str, Any],
        config_snapshot: dict[str, Any],
        cards: list[RadarCard],
        deep_assessments: list[DeepAssessment],
        artifacts: list[ArtifactRecord],
    ) -> None:
        cur = self.connection.cursor()
        failed = diagnostics.get("enrichments_failed_retryable", 0) + diagnostics.get("enrichments_failed_final", 0)
        status = "COMPLETE" if failed == 0 else "PARTIAL"
        cur.execute(
            """
            INSERT OR REPLACE INTO enrichment_runs
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enrichment_run_id,
                radar_run_id,
                started_at,
                finished_at,
                requested_limit,
                selected_count,
                diagnostics.get("enrichments_complete", 0),
                failed,
                skipped_count,
                diagnostics.get("total_downloaded_bytes", 0),
                status,
                json.dumps(config_snapshot, ensure_ascii=False),
            ),
        )
        card_map = {card.procurement_number: card for card in cards}
        artifact_map: dict[str, list[ArtifactRecord]] = {}
        for artifact in artifacts:
            artifact_map.setdefault(artifact.procurement_number, []).append(artifact)
            cur.execute(
                """
                INSERT INTO procurement_artifacts
                (procurement_number, artifact_type, source_url, local_path, original_filename,
                 content_type, size_bytes, sha256, downloaded_at, extraction_status,
                 document_type, document_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.procurement_number,
                    artifact.artifact_type,
                    artifact.source_url,
                    artifact.local_path,
                    artifact.original_filename,
                    artifact.content_type,
                    artifact.size_bytes,
                    artifact.sha256,
                    artifact.downloaded_at,
                    artifact.extraction_status,
                    artifact.document_type,
                    artifact.document_confidence,
                ),
            )
        for idx, deep in enumerate(deep_assessments, start=1):
            attempt_id = f"{enrichment_run_id}_{idx:03d}_{deep.procurement_number}"
            cur.execute(
                "INSERT OR REPLACE INTO enrichment_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    enrichment_run_id,
                    deep.procurement_number,
                    started_at,
                    finished_at,
                    deep.enrichment_status.value,
                    deep.error_code,
                    deep.error_message,
                ),
            )
            cur.execute(
                """
                INSERT INTO deep_assessments
                (enrichment_run_id, procurement_number, deep_assessment_json, final_decision, deep_score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    enrichment_run_id,
                    deep.procurement_number,
                    json.dumps(deep.to_dict(), ensure_ascii=False),
                    deep.final_radar_decision.value,
                    deep.deep_score,
                ),
            )
            cur.execute(
                """
                INSERT INTO deep_assessment_evidence
                (enrichment_run_id, procurement_number, evidence_json)
                VALUES (?, ?, ?)
                """,
                (
                    enrichment_run_id,
                    deep.procurement_number,
                    json.dumps(
                        {
                            "positive": deep.key_positive_factors,
                            "risks": deep.key_risks,
                            "blockers": deep.blocking_factors,
                            "questions": deep.unanswered_questions,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            previous = self.connection.execute(
                "SELECT * FROM procurement_enrichment WHERE procurement_number = ?",
                (deep.procurement_number,),
            ).fetchone()
            first_enriched_at = previous["first_enriched_at"] if previous and previous["first_enriched_at"] else finished_at
            attempt_count = int(previous["attempt_count"] or 0) + 1 if previous else 1
            card = card_map.get(deep.procurement_number)
            source_fingerprint = card.source_fingerprint if card else ""
            docs = artifact_map.get(deep.procurement_number, [])
            document_set_fingerprint = ""
            if docs:
                import hashlib

                raw = json.dumps([item.to_dict() for item in docs], ensure_ascii=False, sort_keys=True)
                document_set_fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            analysis_raw = json.dumps(deep.to_dict(), ensure_ascii=False, sort_keys=True)
            import hashlib

            analysis_fingerprint = hashlib.sha256(analysis_raw.encode("utf-8")).hexdigest()
            cur.execute(
                """
                INSERT OR REPLACE INTO procurement_enrichment
                (procurement_number, enrichment_status, latest_attempt_id, first_enriched_at,
                 last_enriched_at, next_retry_at, attempt_count, source_fingerprint,
                 document_set_fingerprint, analysis_fingerprint, deep_assessment_version,
                 latest_error_code, latest_error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deep.procurement_number,
                    deep.enrichment_status.value,
                    attempt_id,
                    first_enriched_at,
                    finished_at,
                    "",
                    attempt_count,
                    source_fingerprint,
                    document_set_fingerprint,
                    analysis_fingerprint,
                    deep.document_analysis_version,
                    deep.error_code,
                    deep.error_message,
                ),
            )
        self.connection.commit()

    def get_opportunity(self, procurement_number: str) -> NoCompetitionOpportunity | None:
        row = self.connection.execute(
            "SELECT opportunity_json FROM opportunity_assessments WHERE current_procurement_number = ?",
            (procurement_number,),
        ).fetchone()
        if not row:
            return None
        return NoCompetitionOpportunity(**json.loads(row["opportunity_json"]))

    def get_opportunity_transition_history(self, procurement_number: str) -> list[sqlite3.Row]:
        cur = self.connection.execute(
            """
            SELECT transition_type, previous_value, current_value, detected_at
            FROM opportunity_transitions
            WHERE procurement_number = ?
            ORDER BY id ASC
            """,
            (procurement_number,),
        )
        return list(cur.fetchall())

    def save_opportunity_assessment(
        self,
        *,
        algorithm_version: str,
        failure_events: list[ProcurementFailureEvent],
        republication_links: list[RepeatedProcurementLink],
        opportunities: list[NoCompetitionOpportunity],
        transitions: list[OpportunityTransition],
        detected_at: str,
        active_procurement_numbers: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        cur = self.connection.cursor()
        change_feed: list[ChangeFeedEvent] = []
        for event in failure_events:
            cur.execute(
                """
                INSERT OR REPLACE INTO procurement_failure_events
                (procurement_number, detected_at, failure_type, evidence_confidence, algorithm_version, event_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.procurement_number,
                    event.detected_at or detected_at,
                    event.failure_type,
                    event.evidence_confidence,
                    algorithm_version,
                    json.dumps(event.to_dict(), ensure_ascii=False),
                ),
            )
        for link in republication_links:
            cur.execute(
                """
                INSERT INTO republication_links
                (current_procurement_number, previous_procurement_number, relation_type, relation_score, confidence, algorithm_version, link_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.current_procurement_number,
                    link.previous_procurement_number,
                    link.relation_type,
                    link.relation_score or link.similarity_score,
                    link.confidence,
                    algorithm_version,
                    json.dumps(link.to_dict(), ensure_ascii=False),
                ),
            )
        active_opportunity_numbers = {opportunity.current_procurement_number for opportunity in opportunities}
        scoped_numbers = set(active_procurement_numbers or [])
        if scoped_numbers:
            rows = cur.execute(
                "SELECT current_procurement_number, opportunity_level FROM opportunity_assessments"
            ).fetchall()
            for row in rows:
                number = row["current_procurement_number"]
                if number not in scoped_numbers or number in active_opportunity_numbers:
                    continue
                transition = OpportunityTransition(
                    procurement_number=number,
                    transition_type="OPPORTUNITY_NO_LONGER_ACTIVE",
                    previous_value=row["opportunity_level"],
                    current_value="INACTIVE",
                    detected_at=detected_at,
                )
                transitions.append(transition)

        for opportunity in opportunities:
            previous = self.get_opportunity(opportunity.current_procurement_number)
            cur.execute(
                """
                INSERT OR REPLACE INTO opportunity_assessments
                (current_procurement_number, previous_procurement_number, opportunity_score, opportunity_level, detected_at, algorithm_version, opportunity_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.current_procurement_number,
                    opportunity.previous_procurement_number,
                    opportunity.opportunity_score,
                    opportunity.opportunity_level,
                    detected_at,
                    algorithm_version,
                    json.dumps(opportunity.to_dict(), ensure_ascii=False),
                ),
            )
            if previous is None:
                change_feed.append(
                    ChangeFeedEvent(
                        procurement_number=opportunity.current_procurement_number,
                        event_type="NEW_OPPORTUNITY",
                        detected_at=detected_at,
                        field_name="opportunity",
                        previous_value="",
                        current_value=opportunity.opportunity_level,
                        severity="INFO",
                        source="opportunity_assessment",
                        explanation="new opportunity detected",
                    )
                )
            elif previous.opportunity_level != opportunity.opportunity_level or previous.opportunity_score != opportunity.opportunity_score:
                change_feed.append(
                    ChangeFeedEvent(
                        procurement_number=opportunity.current_procurement_number,
                        event_type="OPPORTUNITY_UPDATED",
                        detected_at=detected_at,
                        field_name="opportunity",
                        previous_value=f"{previous.opportunity_level}:{previous.opportunity_score}",
                        current_value=f"{opportunity.opportunity_level}:{opportunity.opportunity_score}",
                        severity="NOTICE",
                        source="opportunity_assessment",
                        explanation="opportunity score or level changed",
                    )
                )
        for transition in transitions:
            cur.execute(
                """
                INSERT INTO opportunity_transitions
                (procurement_number, transition_type, previous_value, current_value, detected_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    transition.procurement_number,
                    transition.transition_type,
                    transition.previous_value,
                    transition.current_value,
                    transition.detected_at or detected_at,
                ),
                )
            if transition.transition_type == "OPEN_TO_CLOSED":
                change_feed.append(
                    ChangeFeedEvent(
                        procurement_number=transition.procurement_number,
                        event_type="PROCUREMENT_CLOSED",
                        detected_at=transition.detected_at or detected_at,
                        field_name="status",
                        previous_value=transition.previous_value,
                        current_value=transition.current_value,
                        severity="WARNING",
                        source="opportunity_transition",
                        explanation="open procurement became closed",
                    )
                )
            elif transition.transition_type == "NEW_OPPORTUNITY":
                change_feed.append(
                    ChangeFeedEvent(
                        procurement_number=transition.procurement_number,
                        event_type="NEW_OPPORTUNITY",
                        detected_at=transition.detected_at or detected_at,
                        field_name="opportunity",
                        previous_value=transition.previous_value,
                        current_value=transition.current_value,
                        severity="INFO",
                        source="opportunity_transition",
                        explanation="new opportunity recorded",
                    )
                )
            elif transition.transition_type == "OPPORTUNITY_UPDATED":
                change_feed.append(
                    ChangeFeedEvent(
                        procurement_number=transition.procurement_number,
                        event_type="OPPORTUNITY_UPDATED",
                        detected_at=transition.detected_at or detected_at,
                        field_name="opportunity",
                        previous_value=transition.previous_value,
                        current_value=transition.current_value,
                        severity="NOTICE",
                        source="opportunity_transition",
                        explanation="opportunity details changed",
                    )
                )
            elif transition.transition_type == "OPPORTUNITY_NO_LONGER_ACTIVE":
                change_feed.append(
                    ChangeFeedEvent(
                        procurement_number=transition.procurement_number,
                        event_type="OPPORTUNITY_NO_LONGER_ACTIVE",
                        detected_at=transition.detected_at or detected_at,
                        field_name="opportunity",
                        previous_value=transition.previous_value,
                        current_value=transition.current_value,
                        severity="WARNING",
                        source="opportunity_transition",
                        explanation="previously detected opportunity is no longer active in this run",
                    )
                )
        self.connection.commit()
        return [event.to_dict() for event in change_feed]
