"""
Fix (surfaced while verifying Step 4 on real CF data): the handover's data_quality.missing_periods and
data_quality.warnings arrays were [None, None, ...] whenever the issues came from the normalizer, because
contract.py read details["message"] while the normalizer's issues (MISSING_PERIOD, DIMENSION_AMBIGUITY,
UNIT_CONSISTENCY, PERIOD_MAPPING) use details["reason"]. This bug predates Step 4; it only produced visible
garbage once quality_issue stopped being empty (Step 3) and started holding many real issues (Step 4).
"""
import datetime as dt

from schema.models import Issuer, Filing, HistoryDecision, QualityIssue
from quality.harness import QualityReport
from handover.contract import HandoverContractGenerator, _issue_text


ISSUER = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF", ticker="CF", cik="1324404", fiscal_year_end="1231")


def issue(rule_code, **details_kwargs):
    return QualityIssue(issue_id=f"issue_{rule_code}_1", run_id="r1", rule_code=rule_code, severity="WARNING",
                        status="OPEN", details=details_kwargs or None)


def test_issue_text_prefers_message_then_reason_then_a_fallback():
    assert _issue_text(issue("X", message="from the harness")) == "from the harness"
    assert _issue_text(issue("X", reason="from the normalizer")) == "from the normalizer"
    assert _issue_text(issue("X", message="m", reason="r")) == "m"           # message wins when both exist
    assert _issue_text(issue("X")) == "X (issue_X_1)"                        # never None, never empty


def test_handover_missing_periods_and_warnings_never_contain_none():
    report = QualityReport(
        run_id="r1", issuer_id=ISSUER.issuer_id, total_filings_evaluated=1, total_facts_evaluated=1,
        total_issues=2, blocker_count=0, warning_count=2, info_count=0, is_valid=True,
        issues=[
            issue("MISSING_PERIOD", metric_code="REVENUE", period="FY2021", reason="No fact found for expected metric and period."),
            issue("DIMENSION_AMBIGUITY", reason="Only dimensioned facts present for metric OPERATING_INCOME period FY2024."),
        ]
    )
    gen = HandoverContractGenerator()
    filing = Filing(filing_id="f1", issuer_id=ISSUER.issuer_id, accession_number="a1", form_type="10-K",
                    filing_date=dt.date(2026, 2, 1), report_period=dt.date(2025, 12, 31), source_uri="u", source_hash="h")
    hd = HistoryDecision(decision_id="h1", issuer_id=ISSUER.issuer_id, run_id="r1", mode="NORMAL", years_selected=5, policy_version="v1.1")
    state = gen.generate_contract(issuer=ISSUER, as_of_date=dt.date(2026, 10, 6), history_decision=hd, filings=[filing],
                                  metrics=[], versions=[], events=[], quality_report=report)
    assert None not in state.data_quality["missing_periods"]
    assert None not in state.data_quality["warnings"]
    assert state.data_quality["missing_periods"] == ["No fact found for expected metric and period."]
    assert "Only dimensioned facts present" in state.data_quality["warnings"][1]
