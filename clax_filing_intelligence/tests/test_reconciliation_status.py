"""
Step 7 (team head item 7): reconciliation_status in the handover was always the constant "RECONCILED",
even for a run that checked zero facts or whose SEC reconciliation query itself failed. It now reflects
what the harness's EXTRACTION_ACCURACY rule actually found: RECONCILED (everything checked matched),
PARTIAL (some matched), MISMATCHES_FOUND (a genuine value mismatch -> blocker), or UNVERIFIED (nothing
could be checked at all).
"""
import datetime as dt

from schema.models import Issuer, Filing, HistoryDecision, QualityIssue
from quality.harness import QualityReport
from handover.contract import HandoverContractGenerator


ISSUER = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF", ticker="CF", cik="1324404", fiscal_year_end="1231")


def hd():
    return HistoryDecision(decision_id="h1", issuer_id=ISSUER.issuer_id, run_id="r1", mode="NORMAL", years_selected=5, policy_version="v1.1")


def build_state(report):
    f = Filing(filing_id="f1", issuer_id=ISSUER.issuer_id, accession_number="a1", form_type="10-K",
              filing_date=dt.date(2026, 2, 1), report_period=dt.date(2025, 12, 31), source_uri="u", source_hash="h")
    gen = HandoverContractGenerator()
    return gen.generate_contract(issuer=ISSUER, as_of_date=dt.date(2026, 10, 6), history_decision=hd(), filings=[f],
                                 metrics=[], versions=[], events=[], quality_report=report)


def test_all_checked_facts_match_is_reconciled():
    report = QualityReport(run_id="r1", issuer_id=ISSUER.issuer_id, total_filings_evaluated=1, total_facts_evaluated=1,
                           total_issues=0, blocker_count=0, warning_count=0, info_count=0, is_valid=True, issues=[],
                           reconciled_count=11, reconciliation_total=11)
    state = build_state(report)
    assert state.data_quality["reconciliation_status"] == "RECONCILED"
    assert state.data_quality["reconciled_count"] == 11 and state.data_quality["reconciliation_total"] == 11


def test_nothing_could_be_checked_is_unverified_not_silently_reconciled():
    """Before this fix, a run that checked ZERO facts still reported reconciliation_status = RECONCILED."""
    report = QualityReport(run_id="r1", issuer_id=ISSUER.issuer_id, total_filings_evaluated=0, total_facts_evaluated=0,
                           total_issues=0, blocker_count=0, warning_count=0, info_count=0, is_valid=True, issues=[],
                           reconciled_count=0, reconciliation_total=0)
    state = build_state(report)
    assert state.data_quality["reconciliation_status"] == "UNVERIFIED"


def test_a_genuine_mismatch_is_reported_as_mismatches_found():
    issue = QualityIssue(issue_id="i1", run_id="r1", rule_code="EXTRACTION_ACCURACY", severity="BLOCKER", status="OPEN",
                         details={"message": "value mismatch"})
    report = QualityReport(run_id="r1", issuer_id=ISSUER.issuer_id, total_filings_evaluated=1, total_facts_evaluated=1,
                           total_issues=1, blocker_count=1, warning_count=0, info_count=0, is_valid=False, issues=[issue],
                           reconciled_count=5, reconciliation_total=6)
    state = build_state(report)
    assert state.data_quality["reconciliation_status"] == "MISMATCHES_FOUND"


def test_a_warning_severity_extraction_issue_does_not_count_as_a_mismatch():
    """Only a BLOCKER-severity EXTRACTION_ACCURACY issue means a genuine mismatch; a WARNING-severity one
    (e.g. a different EXTRACTION_ACCURACY note) must not downgrade an otherwise-reconciled run."""
    issue = QualityIssue(issue_id="i1", run_id="r1", rule_code="EXTRACTION_ACCURACY", severity="WARNING", status="FLAGGED",
                         details={"message": "a non-blocking extraction note"})
    report = QualityReport(run_id="r1", issuer_id=ISSUER.issuer_id, total_filings_evaluated=1, total_facts_evaluated=1,
                           total_issues=1, blocker_count=0, warning_count=1, info_count=0, is_valid=True, issues=[issue],
                           reconciled_count=6, reconciliation_total=6)
    state = build_state(report)
    assert state.data_quality["reconciliation_status"] == "RECONCILED"
