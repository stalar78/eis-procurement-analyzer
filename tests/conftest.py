import pytest


@pytest.fixture(autouse=True)
def isolate_host_telegram_credentials(monkeypatch):
    monkeypatch.delenv("RADAR_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("RADAR_TELEGRAM_CHAT_ID", raising=False)
