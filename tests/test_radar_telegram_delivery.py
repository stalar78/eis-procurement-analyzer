from datetime import datetime
from pathlib import Path

from radar.config import RadarConfig
from radar.state import RadarState
from radar.telegram_delivery import CHANNEL, deliver_alert_feed, format_alert_message, split_message


def _alert() -> dict[str, object]:
    return {
        "procurement_number": "1",
        "alert_type": "NEW_OPPORTUNITY",
        "alert_priority": "HIGH",
        "detected_at": "2026-08-11T10:00:00+03:00",
        "reason": "new opportunity detected",
        "event_types": ["NEW_OPPORTUNITY"],
        "field_names": ["opportunity"],
        "previous_value": "",
        "current_value": "HIGH",
        "source_events": [],
        "score": 88,
        "radar_decision": "PRIORITY",
        "fingerprint": "fingerprint-1",
    }


def test_successful_send_records_delivery(tmp_path: Path) -> None:
    config = RadarConfig().telegram
    config.enabled = True
    config.bot_token = "token"
    config.chat_id = "chat"
    state = RadarState(tmp_path / "radar.db")
    calls: list[tuple[str, dict[str, object], int]] = []

    def http_post(url: str, payload: dict[str, object], timeout: int):
        calls.append((url, payload, timeout))
        return 200, {"ok": True}

    result = deliver_alert_feed([_alert()], config, state, run_id="run-1", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post)
    assert result[0]["status"] == "SENT"
    assert calls and calls[0][1]["chat_id"] == "chat"
    assert state.was_alert_delivered("fingerprint-1", CHANNEL, "chat")
    state.close()


def test_duplicate_alert_is_skipped(tmp_path: Path) -> None:
    config = RadarConfig().telegram
    config.enabled = True
    config.bot_token = "token"
    config.chat_id = "chat"
    state = RadarState(tmp_path / "radar.db")
    state.record_alert_delivery(
        alert_fingerprint="fingerprint-1",
        channel=CHANNEL,
        chat_id="chat",
        status="SENT",
        attempted_at="2026-08-11T10:00:00+03:00",
        delivered_at="2026-08-11T10:00:00+03:00",
        run_id="seed",
        attempt_count=1,
        response={},
    )
    calls: list[tuple[str, dict[str, object], int]] = []

    def http_post(url: str, payload: dict[str, object], timeout: int):
        calls.append((url, payload, timeout))
        return 200, {"ok": True}

    result = deliver_alert_feed([_alert()], config, state, run_id="run-2", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post)
    assert result[0]["status"] == "SKIPPED_DUPLICATE"
    assert calls == []
    state.close()


def test_failed_send_remains_retryable(tmp_path: Path) -> None:
    config = RadarConfig().telegram
    config.enabled = True
    config.bot_token = "token"
    config.chat_id = "chat"
    config.max_retries = 0
    state = RadarState(tmp_path / "radar.db")

    def http_post(_url: str, _payload: dict[str, object], _timeout: int):
        return 500, {"ok": False}

    result = deliver_alert_feed([_alert()], config, state, run_id="run-1", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post, sleep=lambda _seconds: None)
    assert result[0]["status"] == "FAILED"
    assert not state.was_alert_delivered("fingerprint-1", CHANNEL, "chat")
    state.close()


def test_transient_retry_then_success(tmp_path: Path) -> None:
    config = RadarConfig().telegram
    config.enabled = True
    config.bot_token = "token"
    config.chat_id = "chat"
    config.max_retries = 1
    state = RadarState(tmp_path / "radar.db")
    attempts = {"count": 0}

    def http_post(_url: str, _payload: dict[str, object], _timeout: int):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return 500, {"ok": False}
        return 200, {"ok": True}

    result = deliver_alert_feed([_alert()], config, state, run_id="run-1", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post, sleep=lambda _seconds: None)
    assert result[0]["status"] == "SENT"
    assert attempts["count"] == 2
    state.close()


def test_message_splitting(tmp_path: Path) -> None:
    config = RadarConfig().telegram
    config.enabled = True
    config.bot_token = "token"
    config.chat_id = "chat"
    config.max_message_chars = 120
    state = RadarState(tmp_path / "radar.db")
    payloads: list[dict[str, object]] = []

    def http_post(url: str, payload: dict[str, object], timeout: int):
        payloads.append(payload)
        return 200, {"ok": True}

    alert = _alert()
    alert["reason"] = "x" * 400
    result = deliver_alert_feed([alert], config, state, run_id="run-1", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post)
    assert result[0]["status"] == "SENT"
    assert len(payloads) > 1
    state.close()


def test_partial_chunk_failure_retries_only_undelivered_chunks(tmp_path: Path) -> None:
    config = RadarConfig().telegram
    config.enabled = True
    config.bot_token = "token"
    config.chat_id = "chat"
    config.max_message_chars = 120
    config.max_retries = 0
    state = RadarState(tmp_path / "radar.db")
    calls: list[str] = []
    attempts = {"count": 0}

    def http_post(url: str, payload: dict[str, object], timeout: int):
        calls.append(str(payload["text"]))
        attempts["count"] += 1
        if attempts["count"] == 2:
            return 500, {"ok": False}
        return 200, {"ok": True}

    alert = _alert()
    alert["reason"] = "x" * 400
    expected_chunks = split_message(format_alert_message(alert), config.max_message_chars)

    first = deliver_alert_feed([alert], config, state, run_id="run-1", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post, sleep=lambda _seconds: None)
    assert first[0]["status"] == "FAILED"
    assert len(calls) == 2
    assert not state.was_alert_delivered("fingerprint-1", CHANNEL, "chat")

    second_calls: list[str] = []

    def http_post_retry(url: str, payload: dict[str, object], timeout: int):
        second_calls.append(str(payload["text"]))
        return 200, {"ok": True}

    second = deliver_alert_feed([alert], config, state, run_id="run-2", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post_retry, sleep=lambda _seconds: None)
    assert second[0]["status"] == "SENT"
    assert second_calls == expected_chunks[1:]
    assert state.was_alert_delivered("fingerprint-1", CHANNEL, "chat")
    state.close()


def test_disabled_delivery_makes_no_requests(tmp_path: Path) -> None:
    config = RadarConfig().telegram
    config.enabled = False
    state = RadarState(tmp_path / "radar.db")
    calls: list[tuple[str, dict[str, object], int]] = []

    def http_post(url: str, payload: dict[str, object], timeout: int):
        calls.append((url, payload, timeout))
        return 200, {"ok": True}

    result = deliver_alert_feed([_alert()], config, state, run_id="run-1", now=datetime.fromisoformat("2026-08-11T10:00:00+03:00"), http_post=http_post)
    assert result == []
    assert calls == []
    state.close()
