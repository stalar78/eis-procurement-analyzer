from __future__ import annotations

import ssl
from pathlib import Path

import pytest
import requests

from radar import http


def test_windows_session_mounts_native_trust_adapter(monkeypatch) -> None:
    http._trusted_session.cache_clear()
    created_contexts = []

    class FakeTrustContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

    def fake_context():
        context = FakeTrustContext()
        created_contexts.append(context)
        return context

    monkeypatch.setattr(http.sys, "platform", "win32")
    monkeypatch.setattr(http, "_native_windows_ssl_context", fake_context)

    session = http._trusted_session()

    assert created_contexts
    assert isinstance(session.adapters["https://"], http.NativeTrustHTTPSAdapter)
    assert session.adapters["https://"]._ssl_context.check_hostname is True
    assert session.adapters["https://"]._ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_non_windows_session_uses_normal_requests_verification(monkeypatch) -> None:
    http._trusted_session.cache_clear()

    def fail_context():
        raise AssertionError("native trust should not be initialized")

    monkeypatch.setattr(http.sys, "platform", "linux")
    monkeypatch.setattr(http, "_native_windows_ssl_context", fail_context)

    session = http._trusted_session()

    assert isinstance(session.adapters["https://"], requests.adapters.HTTPAdapter)
    assert not isinstance(session.adapters["https://"], http.NativeTrustHTTPSAdapter)


def test_native_trust_initialization_failure_does_not_disable_verification(monkeypatch) -> None:
    http._trusted_session.cache_clear()

    def fail_context():
        raise requests.exceptions.SSLError("native trust unavailable")

    monkeypatch.setattr(http.sys, "platform", "win32")
    monkeypatch.setattr(http, "_native_windows_ssl_context", fail_context)

    with pytest.raises(requests.exceptions.SSLError, match="native trust unavailable"):
        http.get("https://zakupki.gov.ru", timeout=1)


def test_production_http_code_does_not_disable_tls_verification() -> None:
    production_modules = [
        Path("radar/discovery.py"),
        Path("radar/source_resolution.py"),
        Path("radar/historical_live_validation.py"),
        Path("radar/result_extraction.py"),
        Path("radar/http.py"),
    ]

    for path in production_modules:
        text = path.read_text(encoding="utf-8")
        assert "verify=False" not in text
        assert "disable_warnings" not in text
        assert "InsecureRequestWarning" not in text
        assert "CERT_NONE" not in text
        assert "check_hostname = False" not in text
