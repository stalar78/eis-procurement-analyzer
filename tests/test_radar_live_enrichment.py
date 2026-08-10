import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import collect_candidate_details
from radar.artifact_registry import ArtifactRecord, ensure_inside, fingerprint_records
from radar.live_collection import (
    ProcurementCollectionTarget,
    deduplicate_document_links,
    normalize_eis_url,
    section_url,
)
from radar.runner import run


VALID_URL = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0123456789012345678"


def test_valid_eis_url_normalization() -> None:
    url, number = normalize_eis_url(VALID_URL)
    assert number == "0123456789012345678"
    assert url.startswith("https://zakupki.gov.ru/")


def test_reject_non_eis_url() -> None:
    with pytest.raises(ValueError):
        normalize_eis_url("https://example.com/epz/order?regNumber=0123456789012345678")


def test_reject_procurement_number_mismatch() -> None:
    with pytest.raises(ValueError):
        normalize_eis_url(VALID_URL, "9999999999999999999")


def test_section_url_construction() -> None:
    assert "documents.html" in section_url(VALID_URL, "documents")
    assert "supplier-results.html" in section_url(VALID_URL, "results")


def test_document_link_deduplication() -> None:
    links = [
        {"url": "https://zakupki.gov.ru/file.pdf#x", "section": "documents"},
        {"url": "https://zakupki.gov.ru/file.pdf", "section": "documents"},
    ]
    assert len(deduplicate_document_links(links)) == 1


def test_html_page_rejected_as_document() -> None:
    assert collect_candidate_details.looks_like_html(b"<!doctype html><html></html>", "application/octet-stream")


def test_file_signature_validation_accepts_pdf_like_content(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.7\nbody")
    assert path.read_bytes().startswith(b"%PDF")


def test_changed_hash_updates_document_set_fingerprint() -> None:
    first = [
        ArtifactRecord("1", "document", source_url="u", original_filename="a.pdf", size_bytes=1, sha256="a"),
    ]
    second = [
        ArtifactRecord("1", "document", source_url="u", original_filename="a.pdf", size_bytes=1, sha256="b"),
    ]
    assert fingerprint_records(first) != fingerprint_records(second)


def test_deadline_only_change_does_not_update_document_set_fingerprint() -> None:
    records = [
        ArtifactRecord("1", "document", source_url="u", original_filename="a.pdf", size_bytes=1, sha256="a"),
    ]
    assert fingerprint_records(records) == fingerprint_records(records)


def test_generated_paths_stay_under_procurement_root(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    child = root / "documents" / "a.pdf"
    child.parent.mkdir(parents=True)
    child.write_text("x", encoding="utf-8")
    assert ensure_inside(root, child) == child.resolve()


def test_dry_run_produces_plan_without_browser_start(tmp_path: Path) -> None:
    output = tmp_path / "out"
    db = tmp_path / "db.sqlite"
    run(
        [
            "--offline-input",
            "tests/fixtures/radar_cards.json",
            "--as-of",
            "2026-08-04",
            "--enrich",
            "--enrich-limit",
            "1",
            "--dry-run",
            "--output",
            str(output),
            "--db",
            str(db),
        ]
    )
    plans = list((output / "preview").glob("*/enrichment_plan.json"))
    assert plans
    data = json.loads(plans[0].read_text(encoding="utf-8"))
    assert data["selected_procurements"][0]["expected_action"] == "COLLECT_AND_ANALYZE"
    assert not db.exists()


def test_explicit_url_enrichment_mismatch_is_hard_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run(
            [
                "--offline-input",
                "tests/fixtures/radar_cards.json",
                "--enrichment-only",
                "--procurement-number",
                "9999999999999999999",
                "--source-url",
                VALID_URL,
                "--force-enrich",
                "--output",
                str(tmp_path / "out"),
                "--db",
                str(tmp_path / "db.sqlite"),
            ]
        )


def test_direct_collection_target_without_queue_file(monkeypatch, tmp_path: Path) -> None:
    async def fake_collect(*args, **kwargs):
        return [
            SimpleNamespace(
                procurement_number="0123456789012345678",
                source_url=VALID_URL,
                procurement_directory=str(tmp_path),
                status="COMPLETE",
                to_dict=lambda: {"status": "COMPLETE"},
            )
        ]

    monkeypatch.setattr(collect_candidate_details, "_collect_direct_targets_async", fake_collect)
    results = collect_candidate_details.collect_candidate_details_for_procurements(
        [ProcurementCollectionTarget("0123456789012345678", VALID_URL)],
        tmp_path,
    )
    assert results[0].status == "COMPLETE"

