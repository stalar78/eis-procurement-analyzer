import subprocess
import sys
from pathlib import Path

import importlib.util


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("analyzer", ROOT / "analyze_candidate_documents.py")
analyzer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["analyzer"] = analyzer
SPEC.loader.exec_module(analyzer)


def test_strict_extraction_regression():
    root = ROOT
    script = root / "analyze_candidate_documents.py"
    result = subprocess.run(
        [sys.executable, str(script), "--run-regression-tests"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REGRESSION PASS" in result.stdout


def test_classifier_filename_rules():
    cases = [
        ("III. Техническая часть.docx", "technical_specification"),
        ("V. ПРОЕКТ КОНТРАКТА.docx", "contract_draft"),
        ("1. Описание объекта закупки ЭА-25.docx", "technical_specification"),
        ("ТЗ Портал МСП .docx", "technical_specification"),
        ("3. Требования к содержанию, составу заявки.docx", "application_requirements"),
    ]
    for filename, expected in cases:
        assert analyzer.classify_document(Path(filename), "documents", "") == expected


def test_unreadable_doc_is_not_missing():
    rows = [
        {
            "source_path": r"C:\x\downloads\documents\3. Проект контракта.doc",
            "original_filename": "3. Проект контракта.doc",
            "detected_type": "contract_draft",
            "extraction_status": "error",
            "text_length": "0",
        }
    ]
    statuses = analyzer.document_statuses(rows)
    assert statuses["contract_status"] == "unreadable"


def test_rejected_money_not_in_contradictions():
    card = {"procurement_number": "x", "contradictions": [{"field": "contract_price", "old": 569066.67, "new": 690.67}]}
    analyzer.strict_reanalyze(card, [], [], [])
    assert not card["contradictions"]
    assert card["rejected_candidates"]


def test_missing_protocol_does_not_block_technical_verdict():
    card = {
        "technical_specification_status": "read",
        "contract_status": "read",
        "application_requirements_status": "read",
        "final_protocol_status": "missing",
        "short_scope": "Разработка бизнес-портала с CMS, формами и поиском.",
        "analysis_reliability": "HIGH",
        "data_completeness_score": 85,
        "solo_developer_fit_score": 7,
        "ai_fit_score": 8,
        "financial_risk_score": 3,
        "technical_complexity_score": 4,
        "recommended_min_price": 300000,
        "recommended_comfort_price": 450000,
        "nmck": 600000,
    }
    analyzer.apply_verdict_gate(card, [])
    assert card["technical_participation_verdict"] != "INSUFFICIENT_TECHNICAL_DATA"
    assert card["market_result_status"] == "PROTOCOL_NOT_AVAILABLE"
    assert card["overall_recommendation"] == "PROMISING_BUT_MARKET_UNKNOWN"


def test_take_now_requires_application_requirements():
    card = {
        "technical_specification_status": "read",
        "contract_status": "read",
        "application_requirements_status": "missing",
        "final_protocol_status": "missing",
        "short_scope": "Разработка сайта с CMS.",
        "analysis_reliability": "HIGH",
        "data_completeness_score": 85,
        "solo_developer_fit_score": 8,
        "ai_fit_score": 8,
        "financial_risk_score": 3,
        "technical_complexity_score": 3,
        "recommended_min_price": 100000,
        "recommended_comfort_price": 150000,
        "nmck": 300000,
    }
    analyzer.apply_verdict_gate(card, [])
    assert card["technical_participation_verdict"] != "TAKE_NOW"


def test_extreme_reduction_excluded_from_market_aggregates():
    card = {
        "technical_specification_status": "read",
        "contract_status": "read",
        "application_requirements_status": "read",
        "final_protocol_status": "read",
        "short_scope": "Разработка портала.",
        "analysis_reliability": "HIGH",
        "data_completeness_score": 95,
        "solo_developer_fit_score": 7,
        "ai_fit_score": 8,
        "financial_risk_score": 3,
        "technical_complexity_score": 4,
        "nmck": 100000,
        "contract_price": 10000,
        "participants_count": 3,
        "winner_application_number": "1",
        "price_reduction_percent": 90,
        "recommended_min_price": 50000,
        "recommended_comfort_price": 70000,
    }
    analyzer.apply_verdict_gate(card, [])
    assert card["market_result_status"] == "EXTREME_REDUCTION_REVIEW_REQUIRED"
    assert card["excluded_from_market_aggregates"] is True


def test_extreme_reduction_sets_review_status_even_without_protocol_file():
    card = {
        "technical_specification_status": "read",
        "contract_status": "read",
        "application_requirements_status": "read",
        "final_protocol_status": "missing",
        "short_scope": "Р Р°Р·СЂР°Р±РѕС‚РєР° РїРѕСЂС‚Р°Р»Р°.",
        "analysis_reliability": "HIGH",
        "data_completeness_score": 90,
        "solo_developer_fit_score": 7,
        "ai_fit_score": 8,
        "financial_risk_score": 3,
        "technical_complexity_score": 4,
        "nmck": 100966.67,
        "contract_price": 6858.56,
        "price_reduction_percent": 93.21,
        "recommended_min_price": 50000,
        "recommended_comfort_price": 70000,
    }
    analyzer.apply_verdict_gate(card, [])
    assert card["market_result_status"] == "EXTREME_REDUCTION_REVIEW_REQUIRED"
    assert card["manual_review_required"] is True


def test_top_candidates_excludes_insufficient_data():
    rows = analyzer.top_candidate_rows(
        [
            {
                "procurement_number": "bad",
                "overall_recommendation": "INSUFFICIENT_DATA",
                "technical_participation_verdict": "INSUFFICIENT_TECHNICAL_DATA",
                "analysis_reliability": "HIGH",
                "technical_specification_status": "read",
                "contract_status": "read",
            },
            {
                "procurement_number": "ok",
                "overall_recommendation": "PROMISING_BUT_MARKET_UNKNOWN",
                "technical_participation_verdict": "TAKE_WITH_CONDITIONS",
                "analysis_reliability": "HIGH",
                "technical_specification_status": "read",
                "contract_status": "read",
                "ai_fit_score": 8,
                "solo_developer_fit_score": 7,
            },
        ]
    )
    assert [r["procurement_number"] for r in rows] == ["ok"]


def test_summary_market_sample_size_uses_confirmed_non_excluded_rows():
    rows = analyzer.build_summary_rows(
        [
            {
                "procurement_number": "confirmed",
                "market_result_status": "FULL_RESULT_AVAILABLE",
                "excluded_from_market_aggregates": False,
                "contract_price": 100000,
                "price_reduction_percent": 10,
                "participants_count": 3,
            },
            {
                "procurement_number": "extreme",
                "market_result_status": "EXTREME_REDUCTION_REVIEW_REQUIRED",
                "excluded_from_market_aggregates": True,
                "contract_price": 10000,
                "price_reduction_percent": 90,
                "participants_count": 2,
            },
            {
                "procurement_number": "missing",
                "market_result_status": "PROTOCOL_NOT_AVAILABLE",
                "excluded_from_market_aggregates": True,
            },
        ]
    )
    summary = {row["metric"]: row["value"] for row in rows}
    assert summary["sample_size_for_market_statistics"] == 1
    assert summary["confirmed_average_contract_price"] == 100000.0
    assert summary["market_statistics_warning"]


def test_simple_business_portal_gets_solo_fit_at_least_six():
    card = {
        "procurement_name": "CMS portal",
        "short_scope": "Р Р°Р·СЂР°Р±РѕС‚РєР° Р±РёР·РЅРµСЃ-РїРѕСЂС‚Р°Р»Р° СЃ CMS, С„РѕСЂРјР°РјРё Рё РїРѕРёСЃРєРѕРј.",
        "content_management": True,
        "admin_panel": True,
        "search": True,
        "data_completeness_score": 80,
        "nmck": 600000,
    }
    evidence = []
    analyzer.strict_score_procurement(card, [], evidence)
    assert card["solo_developer_fit_score"] >= 6
    assert card["ai_fit_score"] >= 7


def test_1c_project_requires_preparation_and_not_take_now():
    card = {
        "technical_specification_status": "read",
        "contract_status": "read",
        "application_requirements_status": "read",
        "final_protocol_status": "missing",
        "procurement_name": "1C integration",
        "short_scope": "РњРѕРґРµСЂРЅРёР·Р°С†РёСЏ 1C СЃРёСЃС‚РµРјС‹.",
        "analysis_reliability": "HIGH",
        "data_completeness_score": 90,
        "nmck": 900000,
    }
    analyzer.strict_score_procurement(card, [], [])
    analyzer.apply_verdict_gate(card, [])
    assert card["specific_platform"] == "1C"
    assert card["platform_expertise_required"] is True
    assert card["technical_participation_verdict"] != "TAKE_NOW"
