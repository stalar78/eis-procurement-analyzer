from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from radar.config import RadarConfig
from radar.models import RadarAssessment, RadarCard, RadarDecision
from radar.prefilter import parse_datetime


PRIORITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
INTERESTING_DECISIONS = {RadarDecision.PRIORITY.value, RadarDecision.REVIEW.value}
OPPORTUNITY_LEVEL_ORDER = {"INSUFFICIENT_DATA": 0, "LOW": 1, "REVIEW": 2, "MEDIUM": 2, "HIGH": 3}
NEW_PROCUREMENT_ALERT_REASON = "New procurement matched Radar criteria"


@dataclass
class AlertFeedItem:
    procurement_number: str
    alert_type: str
    alert_priority: str
    detected_at: str
    reason: str
    event_types: list[str] = field(default_factory=list)
    field_names: list[str] = field(default_factory=list)
    previous_value: str = ""
    current_value: str = ""
    source_events: list[dict[str, Any]] = field(default_factory=list)
    score: int | None = None
    radar_decision: str = ""
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["fingerprint"]:
            data["fingerprint"] = alert_fingerprint(data)
        return data


def alert_fingerprint(alert: dict[str, Any]) -> str:
    payload = {
        "procurement_number": alert.get("procurement_number", ""),
        "alert_type": alert.get("alert_type", ""),
        "previous_value": alert.get("previous_value", ""),
        "current_value": alert.get("current_value", ""),
        "event_types": alert.get("event_types", []),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_alert_feed(
    change_feed: list[dict[str, Any]],
    cards: list[RadarCard],
    assessments: list[RadarAssessment],
    config: RadarConfig,
    as_of: datetime,
) -> list[dict[str, Any]]:
    if not config.alerts.enabled or not change_feed:
        return []
    card_by_number = {item.procurement_number: item for item in cards}
    assessment_by_number = {item.procurement_number: item for item in assessments}
    alerts: list[AlertFeedItem] = []
    for event in change_feed:
        number = event.get("procurement_number", "")
        assessment = assessment_by_number.get(number)
        card = card_by_number.get(number)
        alert = classify_event(event, card, assessment, config, as_of)
        if alert is not None:
            alerts.append(alert)
    return [item.to_dict() for item in deduplicate_alerts(alerts)]


def classify_event(
    event: dict[str, Any],
    card: RadarCard | None,
    assessment: RadarAssessment | None,
    config: RadarConfig,
    as_of: datetime,
) -> AlertFeedItem | None:
    event_type = event.get("event_type", "")
    previous = str(event.get("previous_value", "") or "")
    current = str(event.get("current_value", "") or "")
    number = event.get("procurement_number", "")
    score = assessment.total_score if assessment else None
    decision = assessment.radar_decision.value if assessment else ""
    reason = event.get("explanation") or f"{event_type}: {previous} -> {current}"

    if event_type == "NEW_OPPORTUNITY":
        return _alert(event, "NEW_OPPORTUNITY", _opportunity_priority(current), reason, score, decision)
    if event_type == "NEW_PROCUREMENT":
        if assessment and (decision in INTERESTING_DECISIONS or assessment.total_score >= config.alerts.minimum_new_score):
            priority = "HIGH" if decision == RadarDecision.PRIORITY.value or assessment.total_score >= config.alerts.high_priority_score else "MEDIUM"
            return _alert(event, "INTERESTING_NEW_PROCUREMENT", priority, NEW_PROCUREMENT_ALERT_REASON, score, decision)
        return None
    if event_type in {"PRELIMINARY_DECISION_CHANGED", "HISTORY_DECISION_CHANGED"} and current == RadarDecision.PRIORITY.value:
        return _alert(event, "DECISION_TO_PRIORITY", "HIGH", reason, score, decision)
    if event_type == "OPPORTUNITY_UPDATED":
        increase = _score_delta(previous, current)
        if increase >= config.alerts.significant_opportunity_score_increase or _opportunity_level(current) > _opportunity_level(previous):
            priority = "HIGH" if _opportunity_level(current) >= OPPORTUNITY_LEVEL_ORDER["HIGH"] else "MEDIUM"
            return _alert(event, "SIGNIFICANT_OPPORTUNITY_CHANGE", priority, reason, score, decision)
        return None
    if event_type == "NMCK_CHANGED":
        percent = _percent_change(previous, current)
        if percent >= config.alerts.significant_nmck_change_percent:
            return _alert(event, "SIGNIFICANT_NMCK_CHANGE", "MEDIUM", f"{reason}; change={percent:.1f}%", score, decision)
        return None
    if event_type == "DEADLINE_CHANGED":
        days_left = _days_until(current, as_of)
        previous_days = _days_until(previous, as_of)
        if days_left is not None and days_left <= config.alerts.urgent_deadline_days and (previous_days is None or previous_days > config.alerts.urgent_deadline_days):
            return _alert(event, "URGENT_DEADLINE", "HIGH", f"{reason}; days_left={days_left}", score, decision)
        return None
    if event_type in {"PROCUREMENT_CLOSED", "OPPORTUNITY_NO_LONGER_ACTIVE"}:
        if event_type == "OPPORTUNITY_NO_LONGER_ACTIVE" or _was_interesting(assessment, config):
            priority = "HIGH" if _was_high_interest(assessment, config) else "MEDIUM"
            return _alert(event, event_type, priority, reason, score, decision)
        return None
    return None


def deduplicate_alerts(alerts: list[AlertFeedItem]) -> list[AlertFeedItem]:
    grouped: dict[str, AlertFeedItem] = {}
    for alert in alerts:
        existing = grouped.get(alert.procurement_number)
        if existing is None:
            grouped[alert.procurement_number] = alert
            continue
        existing.source_events.extend(alert.source_events)
        existing.event_types = sorted(set(existing.event_types + alert.event_types))
        existing.field_names = sorted(set(existing.field_names + alert.field_names))
        if PRIORITY_ORDER[alert.alert_priority] > PRIORITY_ORDER[existing.alert_priority]:
            existing.alert_priority = alert.alert_priority
            existing.alert_type = alert.alert_type
            existing.reason = alert.reason
            existing.previous_value = alert.previous_value
            existing.current_value = alert.current_value
        elif alert.reason not in existing.reason:
            existing.reason = f"{existing.reason}; {alert.reason}"
        existing.fingerprint = ""
    ordered = sorted(grouped.values(), key=lambda item: (-PRIORITY_ORDER[item.alert_priority], item.procurement_number))
    return ordered


def _alert(event: dict[str, Any], alert_type: str, priority: str, reason: str, score: int | None, decision: str) -> AlertFeedItem:
    item = AlertFeedItem(
        procurement_number=event.get("procurement_number", ""),
        alert_type=alert_type,
        alert_priority=priority,
        detected_at=event.get("detected_at", ""),
        reason=reason,
        event_types=[event.get("event_type", "")],
        field_names=[event.get("field_name", "")],
        previous_value=str(event.get("previous_value", "") or ""),
        current_value=str(event.get("current_value", "") or ""),
        source_events=[event],
        score=score,
        radar_decision=decision,
    )
    item.fingerprint = alert_fingerprint(item.to_dict())
    return item


def _was_interesting(assessment: RadarAssessment | None, config: RadarConfig) -> bool:
    if assessment is None:
        return False
    return assessment.radar_decision.value in INTERESTING_DECISIONS or assessment.total_score >= config.alerts.minimum_new_score


def _was_high_interest(assessment: RadarAssessment | None, config: RadarConfig) -> bool:
    if assessment is None:
        return False
    return assessment.radar_decision == RadarDecision.PRIORITY or assessment.total_score >= config.alerts.high_priority_score


def _opportunity_priority(value: str) -> str:
    return "HIGH" if _opportunity_level(value) >= OPPORTUNITY_LEVEL_ORDER["HIGH"] else "MEDIUM"


def _opportunity_level(value: str) -> int:
    level = str(value or "").split(":", 1)[0].upper()
    return OPPORTUNITY_LEVEL_ORDER.get(level, 0)


def _score_delta(previous: str, current: str) -> int:
    return max(0, _score_from_level_value(current) - _score_from_level_value(previous))


def _score_from_level_value(value: str) -> int:
    try:
        return int(str(value).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def _percent_change(previous: str, current: str) -> float:
    try:
        old = float(previous)
        new = float(current)
    except ValueError:
        return 0
    if old == 0:
        return 100 if new else 0
    return abs(new - old) / abs(old) * 100


def _days_until(value: str, as_of: datetime) -> int | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None and as_of.tzinfo is not None:
        parsed = parsed.replace(tzinfo=as_of.tzinfo)
    delta = parsed - as_of
    return int(delta.total_seconds() // 86400)
