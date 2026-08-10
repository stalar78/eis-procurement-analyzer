from __future__ import annotations

from pathlib import Path

import pytest

from radar.config import RadarConfig
from radar.discovery import normalize_card
from radar.historical_live_validation import (
    DECISION_CONTEXT,
    SOURCE_LABEL,
    build_metric_evidence,
    build_query_plan,
    collect_result_for_analog,
    exclude_validation_source_from_active_assessment,
    run_live_historical_validation,
    search_filter_audit,
    validate_live_history_args,
    validate_source_values,
)
from radar.models import EligibilityStatus, HistoricalAnalog, RadarAssessment, RadarDecision
from radar.runner import run


def source_card():
    return normalize_card(
        {
            "procurement_number": "0122300036525000031",
            "title": "Разработка инвестиционного портала для бизнеса",
            "customer": "Администрация тестового района",
            "law": "44-FZ",
            "procedure_type": "Электронный аукцион",
            "status": "Определение поставщика завершено",
            "status_normalized": "COMPLETED",
            "nmck": 750000,
            "source_url": "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0122300036525000031",
            "raw_text": "инвестиционный портал информационный портал интернет-портал API",
        }
    )


def preliminary(number: str = "0122300036525000031") -> RadarAssessment:
    return RadarAssessment(procurement_number=number, eligibility_status=EligibilityStatus.CLOSED, days_to_deadline=None, total_score=80, radar_decision=RadarDecision.PRIORITY)


def analog_cards():
    rows = []
    for index in range(8):
        rows.append(
            normalize_card(
                {
                    "procurement_number": f"9000000000000000000{index}",
                    "title": "Разработка инвестиционного портала личный кабинет API",
                    "customer": "Администрация тестового района" if index < 2 else "Другой заказчик",
                    "law": "44-FZ",
                    "procedure_type": "Электронный аукцион",
                    "status": "Определение поставщика завершено",
                    "status_normalized": "COMPLETED",
                    "nmck": 700000 + index * 10000,
                    "source_url": f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=9000000000000000000{index}",
                    "raw_text": "портал API личный кабинет",
                }
            )
        )
    return rows


def test_completed_source_accepted_only_with_flag() -> None:
    with pytest.raises(ValueError):
        validate_live_history_args(history_only=False, allow_completed_source=True, procurement_numbers=["1"], source_url=None)
    validate_live_history_args(history_only=True, allow_completed_source=True, procurement_numbers=["1"], source_url=None)


def test_source_url_mismatch_fails() -> None:
    with pytest.raises(ValueError):
        validate_live_history_args(
            history_only=True,
            allow_completed_source=True,
            procurement_numbers=["1111111111111111111"],
            source_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=2222222222222222222",
        )


def test_validation_source_excluded_from_current_priority_review() -> None:
    assessment = preliminary()
    exclude_validation_source_from_active_assessment(assessment)
    assert assessment.radar_decision == RadarDecision.INSUFFICIENT_DATA
    assert assessment.total_score == 0
    assert "historical validation source only" in assessment.negative_reasons[0]


def test_historical_query_plan_generated() -> None:
    config = RadarConfig()
    config.historical.search.maximum_queries_per_procurement = 3
    plan = build_query_plan(source_card(), config)
    assert plan
    assert len(plan) <= 3
    assert plan[0]["completed_status_filter"] == {"pc": "on"}


def test_completed_only_filters_are_preserved() -> None:
    rows = search_filter_audit(build_query_plan(source_card(), RadarConfig()), RadarConfig())
    assert rows
    assert all(row["completed_filter_present"] for row in rows)
    assert all(row["active_only_params_absent"] for row in rows)


def test_source_validation_pass_and_tolerances() -> None:
    card = source_card()
    result = validate_source_values(
        card.procurement_number,
        card,
        {"contract_price": 41500.2, "reduction_percent": 94.43, "participant_count": 55, "evidence": []},
    )
    assert result["validation_status"] == "PASS"
    assert result["absolute_differences"]["contract_price"] <= 1
    assert result["absolute_differences"]["reduction_percent"] <= 0.1


def test_source_validation_partial_pass() -> None:
    card = source_card()
    result = validate_source_values(card.procurement_number, card, {"contract_price": None, "reduction_percent": 94.47, "participant_count": None, "evidence": []})
    assert result["validation_status"] == "PARTIAL_PASS"


def test_participant_exact_match_validation() -> None:
    card = normalize_card({"procurement_number": "0360100030524000979", "nmck": 569066.67})
    result = validate_source_values(card.procurement_number, card, {"contract_price": 138783.88, "reduction_percent": 75.61, "participant_count": 11, "evidence": []})
    assert result["absolute_differences"]["participant_count"] == 0


def test_metric_evidence_records_contributors_and_exclusions() -> None:
    analogs = [
        HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a1", participant_count=3, reduction_percent=10, similarity_score=80, result_data_status="COMPLETE"),
        HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a2", participant_count=4, reduction_percent=None, similarity_score=20, result_data_status="PARTIAL"),
    ]
    evidence = build_metric_evidence(analogs, RadarConfig())
    assert evidence["reduction_aggregates"]["contributing_procurement_numbers"] == ["a1"]
    assert evidence["participant_aggregates"]["contributing_procurement_numbers"] == ["a1", "a2"]
    assert evidence["reduction_aggregates"]["excluded_procurement_numbers"] == ["a2"]


def test_download_limits_and_no_technical_docs(tmp_path: Path) -> None:
    analog = HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a1", source_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=a1", nmck=100000)
    calls = []

    def fetch(url: str) -> str:
        calls.append(url)
        return "Цена контракта 10 000 руб. Участников 3. Победитель ООО Тест"

    updated, diagnostics = collect_result_for_analog(analog, fetch=fetch, cache_dir=tmp_path, byte_budget={"total": 0})
    assert updated.contract_price == 10000
    assert diagnostics["bytes"] > 0
    assert all("documents" not in url for url in calls)


def test_resume_reuses_completed_artifact_and_failed_retry(tmp_path: Path) -> None:
    analog = HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a1", source_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=a1", nmck=100000)
    cache = tmp_path / "a1_result.html"
    cache.write_text("Цена контракта 10 000 руб. Участников 3", encoding="utf-8")
    updated, diagnostics = collect_result_for_analog(analog, fetch=lambda _url: (_ for _ in ()).throw(RuntimeError("should not fetch")), cache_dir=tmp_path, resume=True)
    assert diagnostics["cache_hit"]
    assert updated.contract_price == 10000
    failed = HistoricalAnalog(source_procurement_number="s", analog_procurement_number="a2", source_url="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=a2", nmck=100000)
    _, retry_diag = collect_result_for_analog(failed, fetch=lambda _url: "Участников 2", cache_dir=tmp_path, resume=True)
    assert retry_diag["attempted"]


def test_mocked_full_flow_creates_reports_and_labels_decision(tmp_path: Path) -> None:
    config = RadarConfig()
    config.historical.search.maximum_queries_per_procurement = 3
    config.historical.search.maximum_pages_per_query = 2
    config.historical.search.maximum_selected_analogs = 5
    config.historical.similarity.minimum_score = 20

    def collector(_request, _config, _limit, _pages):
        return analog_cards()

    def fetch(_url: str) -> str:
        return "Цена контракта 41 500 руб. Участников 55. Победитель ООО Портал"

    result = run_live_historical_validation(source_card(), preliminary(), config, output_dir=tmp_path, collector=collector, fetch=fetch)
    assert result.source_card.search_profiles[-1] == SOURCE_LABEL
    assert result.diagnostics["decision_context"] == DECISION_CONTEXT
    assert result.bundle.history_adjusted_assessment is not None
    assert result.source_validation["validation_status"] in {"PASS", "PARTIAL_PASS"}
    assert Path(result.output_paths["historical_query_plan"]).exists()
    assert Path(result.output_paths["analog_review"]).exists()
    assert len({analog.analog_procurement_number for analog in result.bundle.historical_analogs}) == len(result.bundle.historical_analogs)
    assert "# R3A Live Historical Validation" in Path(result.output_paths["historical_live_validation_markdown"]).read_text(encoding="utf-8")


def test_diagnostics_contain_no_secrets(tmp_path: Path) -> None:
    config = RadarConfig()
    config.historical.similarity.minimum_score = 20
    result = run_live_historical_validation(source_card(), preliminary(), config, output_dir=tmp_path, dry_run=True, fetch=lambda _url: "")
    serialized = str(result.diagnostics).lower()
    assert "authorization" not in serialized
    assert "cookie" not in serialized
    assert "token" not in serialized


def test_runner_cli_rejects_completed_source_without_history_only() -> None:
    with pytest.raises(ValueError):
        run(["--allow-completed-source", "--procurement-number", "0122300036525000031", "--dry-run"])


def test_strict_existing_procurement_regression_unchanged() -> None:
    result = validate_source_values("0360100030524000979", normalize_card({"procurement_number": "0360100030524000979", "nmck": 569066.67}), {"contract_price": 138783.88, "reduction_percent": 75.61, "participant_count": 11, "evidence": []})
    assert result["validation_status"] == "PASS"
