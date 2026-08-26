from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable
from urllib import request
from urllib.error import HTTPError, URLError

from radar.config import TelegramConfig
from radar.state import RadarState


TELEGRAM_MESSAGE_LIMIT = 4096
CHANNEL = "telegram"


@dataclass
class DeliveryResult:
    alert_fingerprint: str
    channel: str
    chat_id: str
    status: str
    attempted_at: str
    delivered_at: str = ""
    run_id: str = ""
    attempt_count: int = 0
    error_message: str = ""
    response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


HttpPost = Callable[[str, dict[str, Any], int], tuple[int, dict[str, Any]]]
Sleep = Callable[[float], None]


def deliver_alert_feed(
    alerts: list[dict[str, Any]],
    config: TelegramConfig,
    state: RadarState,
    *,
    run_id: str,
    now: datetime | None = None,
    http_post: HttpPost | None = None,
    sleep: Sleep = time.sleep,
) -> list[dict[str, Any]]:
    if not config.enabled or not alerts:
        return []
    token = os.getenv(config.bot_token_env) or config.bot_token
    chat_id = os.getenv(config.chat_id_env) or config.chat_id
    if not token or not chat_id:
        return [
            _record(
                state,
                alert,
                chat_id or "",
                "FAILED",
                run_id,
                now,
                0,
                "telegram token or chat_id is not configured",
            ).to_dict()
            for alert in alerts
        ]
    results: list[DeliveryResult] = []
    poster = http_post or post_telegram_message
    for alert in alerts:
        fingerprint = alert.get("fingerprint", "")
        if state.was_alert_delivered(fingerprint, CHANNEL, chat_id):
            results.append(_record(state, alert, chat_id, "SKIPPED_DUPLICATE", run_id, now, 0, "already delivered"))
            continue
        text_parts = split_message(format_alert_message(alert), config.max_message_chars)
        status = "FAILED"
        response: dict[str, Any] = {}
        error = ""
        attempts_used = 0
        for attempt in range(1, max(1, config.max_retries + 1) + 1):
            attempts_used = attempt
            try:
                for chunk_index, text in enumerate(text_parts, start=1):
                    chunk_key = delivery_chunk_key(fingerprint, CHANNEL, chat_id, chunk_index)
                    if state.was_alert_chunk_delivered(chunk_key):
                        continue
                    code, response = poster(
                        send_message_url(config.api_base_url, token),
                        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                        config.timeout_seconds,
                    )
                    if code >= 500:
                        _record_chunk(state, fingerprint, chat_id, chunk_index, len(text_parts), "FAILED", run_id, now, f"telegram transient HTTP {code}", response)
                        raise RuntimeError(f"telegram transient HTTP {code}")
                    if code >= 400:
                        _record_chunk(state, fingerprint, chat_id, chunk_index, len(text_parts), "FAILED", run_id, now, f"telegram HTTP {code}", response)
                        raise PermanentTelegramError(f"telegram HTTP {code}")
                    _record_chunk(state, fingerprint, chat_id, chunk_index, len(text_parts), "SENT", run_id, now, response=response)
                status = "SENT"
                error = ""
                break
            except PermanentTelegramError as exc:
                error = str(exc)
                break
            except (RuntimeError, URLError, TimeoutError, OSError) as exc:
                error = str(exc)
                if attempt <= config.max_retries:
                    sleep(config.retry_backoff_seconds)
                    continue
                break
        results.append(_record(state, alert, chat_id, status, run_id, now, attempts_used, error, response))
    return [item.to_dict() for item in results]


class PermanentTelegramError(RuntimeError):
    pass


def send_message_url(api_base_url: str, token: str) -> str:
    return f"{api_base_url.rstrip('/')}/bot{token}/sendMessage"


def delivery_chunk_key(alert_fingerprint: str, channel: str, chat_id: str, chunk_index: int) -> str:
    return f"{channel}:{chat_id}:{alert_fingerprint}:{chunk_index}"


def post_telegram_message(url: str, payload: dict[str, Any], timeout_seconds: int) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        payload = json.loads(body or "{}") if body else {}
        return int(exc.code), payload


def format_alert_message(alert: dict[str, Any]) -> str:
    lines = [
        f"[{alert.get('alert_priority', 'LOW')}] {alert.get('alert_type', 'ALERT')}",
        f"Procurement: {alert.get('procurement_number', '')}",
        f"Reason: {alert.get('reason', '')}",
    ]
    if alert.get("score") is not None or alert.get("radar_decision"):
        lines.append(f"Score/decision: {alert.get('score', '')} / {alert.get('radar_decision', '')}")
    if alert.get("alert_type") != "INTERESTING_NEW_PROCUREMENT" and (alert.get("previous_value") or alert.get("current_value")):
        lines.append(f"Change: {alert.get('previous_value', '')} -> {alert.get('current_value', '')}")
    return "\n".join(lines)


def split_message(text: str, max_chars: int) -> list[str]:
    limit = min(max(1, max_chars), TELEGRAM_MESSAGE_LIMIT)
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return parts


def _record(
    state: RadarState,
    alert: dict[str, Any],
    chat_id: str,
    status: str,
    run_id: str,
    now: datetime | None,
    attempt_count: int,
    error_message: str = "",
    response: dict[str, Any] | None = None,
) -> DeliveryResult:
    timestamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    result = DeliveryResult(
        alert_fingerprint=alert.get("fingerprint", ""),
        channel=CHANNEL,
        chat_id=chat_id,
        status=status,
        attempted_at=timestamp,
        delivered_at=timestamp if status == "SENT" else "",
        run_id=run_id,
        attempt_count=attempt_count,
        error_message=error_message,
        response=response or {},
    )
    state.record_alert_delivery(
        alert_fingerprint=result.alert_fingerprint,
        channel=result.channel,
        chat_id=result.chat_id,
        status=result.status,
        attempted_at=result.attempted_at,
        delivered_at=result.delivered_at,
        run_id=result.run_id,
        attempt_count=result.attempt_count,
        error_message=result.error_message,
        response=result.response,
    )
    return result


def _record_chunk(
    state: RadarState,
    alert_fingerprint: str,
    chat_id: str,
    chunk_index: int,
    chunk_count: int,
    status: str,
    run_id: str,
    now: datetime | None,
    error_message: str = "",
    response: dict[str, Any] | None = None,
) -> None:
    timestamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    state.record_alert_chunk_delivery(
        chunk_key=delivery_chunk_key(alert_fingerprint, CHANNEL, chat_id, chunk_index),
        alert_fingerprint=alert_fingerprint,
        channel=CHANNEL,
        chat_id=chat_id,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        status=status,
        attempted_at=timestamp,
        delivered_at=timestamp if status == "SENT" else "",
        run_id=run_id,
        error_message=error_message,
        response=response,
    )
