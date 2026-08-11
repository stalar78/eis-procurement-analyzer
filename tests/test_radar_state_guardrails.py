from datetime import datetime
from pathlib import Path

from radar.alerts import build_alert_feed
from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.models import EligibilityStatus
from radar.scoring import assess_card
from radar.state import RadarState
from radar.telegram_delivery import deliver_alert_feed


def test_absence_only_does_not_generate_closed_alert_or_telegram_delivery(tmp_path: Path) -> None:
    config = RadarConfig()
    state = RadarState(tmp_path / "radar.db")
    missing = normalize_card(
        {
            "procurement_number": "1",
            "title": "Interesting portal build",
            "status_normalized": "APPLICATION_SUBMISSION",
            "application_deadline": "2026-08-20",
            "nmck": 1_800_000,
        }
    )
    observed = normalize_card(
        {
            "procurement_number": "2",
            "title": "Other bounded result",
            "status_normalized": "APPLICATION_SUBMISSION",
            "application_deadline": "2026-08-20",
            "nmck": 1_000_000,
        }
    )
    missing_assessment = assess_card(missing, EligibilityStatus.OPEN, 10, config, [], is_new=True)
    observed_assessment = assess_card(observed, EligibilityStatus.OPEN, 10, config, [], is_new=True)
    state.save_run("r1", "s", "f", "a", "0.4.6-r4f1-state-guardrails", {}, [missing], [missing_assessment])

    result = state.save_run("r2", "s2", "f2", "a", "0.4.6-r4f1-state-guardrails", {}, [observed], [observed_assessment])

    assert not any(event["event_type"] == "PROCUREMENT_CLOSED" for event in result["change_feed"])
    alerts = build_alert_feed(
        result["change_feed"],
        [observed],
        [observed_assessment],
        config,
        datetime.fromisoformat("2026-08-11T10:00:00+03:00"),
    )
    assert alerts == []
    config.telegram.enabled = True
    config.telegram.bot_token = "token"
    config.telegram.chat_id = "chat"
    calls = []

    def http_post(_url: str, payload: dict[str, object], _timeout: int):
        calls.append(payload)
        return 200, {"ok": True}

    delivery = deliver_alert_feed(alerts, config.telegram, state, run_id="r2", http_post=http_post)
    assert delivery == []
    assert calls == []
    state.close()
