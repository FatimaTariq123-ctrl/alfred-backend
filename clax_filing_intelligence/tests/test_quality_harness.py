"""
Unit Tests: Quality Validation Harness (§12, §14)

Verifies that the 10-point quality harness correctly flags BLOCKER severity issues
and prevents invalid runs from emitting a PASS status.
Pure-logic test using lightweight unit-test DB double.
"""

import sys
from pathlib import Path
from datetime import date

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schema.models import Issuer, Filing, FactObservation, FactVersion, NormalizedMetric, QualityIssue
from quality.harness import QualityHarness


class MockDBManager:
    """Lightweight unit-test double for pure-logic quality harness testing."""
    def __init__(self):
        self.quality_issues = {}

    def save_quality_issue(self, issue: QualityIssue):
        self.quality_issues[issue.issue_id] = issue


def test_quality_harness_blocker_detection():
    mock_db = MockDBManager()
    harness = QualityHarness(db_manager=mock_db)

    run_id = "test_run_quality_01"
    issuer_id = "issuer_US_AAPL"
    issuer = Issuer(
        issuer_id=issuer_id,
        market="US",
        legal_name="Apple Inc.",
        ticker="AAPL"
    )

    filing = Filing(
        filing_id="f1",
        issuer_id=issuer_id,
        accession_number="0000320193-23-000106",
        form_type="10-K",
        filing_date=date(2023, 11, 3),
        report_period=date(2023, 9, 30),
        source_uri="http://example.com/aapl.htm",
        source_hash="h1"
    )

    # Empty facts array -> Triggers EXTRACTION_ACCURACY (Blocker)
    report = harness.validate(
        run_id=run_id,
        issuer=issuer,
        filings=[filing],
        facts=[],
        versions=[],
        metrics=[]
    )

    assert not report.is_valid, "Report must be invalid when BLOCKER issues are present"
    assert report.blocker_count >= 1, "Must detect at least 1 BLOCKER severity issue"
    assert report.issues[0].rule_code == "EXTRACTION_ACCURACY"

    print("Quality harness blocker detection unit test passed successfully!")


if __name__ == "__main__":
    test_quality_harness_blocker_detection()
