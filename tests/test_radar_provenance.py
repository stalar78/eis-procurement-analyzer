import json
import subprocess
from pathlib import Path

import pytest

import radar
from radar.runner import run


@pytest.fixture(autouse=True)
def _clear_build_identity_cache():
    radar.build_identity.cache_clear()
    yield
    radar.build_identity.cache_clear()


def test_version_output_includes_radar_version(capsys) -> None:
    code = run(["--version"])

    output = capsys.readouterr().out
    assert code == 0
    assert f"Radar version: {radar.radar_version}" in output
    assert "Build identity:" in output


def test_known_git_sha_becomes_build_identity(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="abc1234\n", stderr="")

    monkeypatch.setattr(radar.subprocess, "run", fake_run)

    assert radar.build_identity() == "abc1234"


def test_git_unavailable_build_identity_is_unknown(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(radar.subprocess, "run", fake_run)

    assert radar.build_identity() == "unknown"


def test_version_output_survives_git_unavailable(monkeypatch, capsys) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(radar.subprocess, "run", fake_run)

    code = run(["--version"])

    output = capsys.readouterr().out
    assert code == 0
    assert f"Radar version: {radar.radar_version}" in output
    assert "Build identity: unknown" in output


def test_report_run_survives_git_unavailable(monkeypatch, tmp_path: Path) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(radar.subprocess, "run", fake_run)
    output = tmp_path / "out"
    db = tmp_path / "radar.db"

    code = run(
        [
            "--offline-input",
            "tests/fixtures/radar_cards.json",
            "--as-of",
            "2026-08-04",
            "--output",
            str(output),
            "--db",
            str(db),
            "--all-profiles",
        ]
    )

    payload = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert code == 0
    assert payload["summary"]["build_identity"] == "unknown"
