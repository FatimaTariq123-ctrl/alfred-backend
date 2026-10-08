"""
Step 3 (team head item 9): every quality issue a stage raises must be PERSISTED and COUNTED, never discarded.

Before this fix, pipeline.normalizer.normalize() built a full list of QualityIssue objects (UNIT_CONSISTENCY,
DIMENSION_AMBIGUITY, PERIOD_MAPPING, MISSING_PERIOD) and returned them as norm_issues, but orchestration.py
only captured that variable and never passed it anywhere: the issues were computed and then thrown away.
quality_issue stayed empty (0 rows) on both CF and EXP even though real findings existed.

Fix: QualityHarness.validate() now accepts external_issues, saves them in ONE batch (db.save_quality_issues)
and folds them into the same QualityReport the harness's own 10 rules produce. orchestration.py passes the
normalizer's norm_issues as external_issues. This file tests the mechanism at three levels: the raw DB batch
method, the harness wiring with a fake DB, and an end-to-end run of the REAL Normalizer against a real database.
"""
import json
import datetime as dt
from pathlib import Path

import psycopg
import pytest

from schema.models import Issuer, Filing, FactObservation, QualityIssue
from quality.harness import QualityHarness
from pipeline.normalizer import Normalizer
from storage.db import DatabaseManager


ISSUER = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF Industries", ticker="CF", cik="1324404", fiscal_year_end="1231")


def issue(code, run_id="run_1", **kw):
    return QualityIssue(issue_id=f"issue_{code}_{kw.get('fact_id', kw.get('filing_id', '1'))}", run_id=run_id,
                        rule_code=code, severity=kw.pop("severity", "WARNING"), status=kw.pop("status", "OPEN"),
                        details=kw.pop("details", {}), **kw)


# ---------------------------------------------------------------- harness wiring (no database)
class FakeDB:
    def __init__(self):
        self.batches = []     # calls to the new batch method (external_issues)
        self.singles = []     # calls to the old single-row method (the harness's own 10 rules)

    def save_quality_issues(self, issues):
        self.batches.append(list(issues))

    def save_quality_issue(self, issue):
        self.singles.append(issue)


def test_external_issues_are_saved_in_one_batch_and_counted():
    db = FakeDB()
    harness = QualityHarness(db_manager=db)
    ext = [issue("MISSING_PERIOD", run_id="run_1", filing_id="f1", details={"metric_code": "REVENUE", "period": "FY2021"}),
           issue("UNIT_CONSISTENCY", run_id="run_1", fact_id="x1", severity="WARNING")]
    report = harness.validate(run_id="run_1", issuer=ISSUER, filings=[], facts=[], versions=[], metrics=[], external_issues=ext)
    assert len(db.batches) == 1 and len(db.batches[0]) == 2             # exactly one batch call, not one commit per issue
    assert report.total_issues >= 2
    codes = {i.rule_code for i in report.issues}
    assert {"MISSING_PERIOD", "UNIT_CONSISTENCY"} <= codes
    assert report.warning_count >= 2


def test_no_external_issues_means_no_extra_db_call():
    """When a stage passes no external_issues, the new batch method is never called (only the harness's own
    per-rule saves may happen, exactly as before this change)."""
    db = FakeDB()
    harness = QualityHarness(db_manager=db)
    harness.validate(run_id="run_1", issuer=ISSUER, filings=[], facts=[], versions=[], metrics=[], external_issues=None)
    assert db.batches == []


def test_external_blocker_makes_the_report_invalid():
    db = FakeDB()
    harness = QualityHarness(db_manager=db)
    ext = [issue("CUSTOM_CHECK", severity="BLOCKER")]
    report = harness.validate(run_id="run_1", issuer=ISSUER, filings=[], facts=[], versions=[], metrics=[], external_issues=ext)
    assert report.is_valid is False and report.blocker_count >= 1


# ---------------------------------------------------------------- db.save_quality_issues batch method (real sandbox DB)
def db_url():
    import os
    return os.environ["DATABASE_URL"]


def seed_run(cur, run_id="run_qi_1", issuer_id=ISSUER.issuer_id):
    cur.execute("INSERT INTO issuer(issuer_id, market, legal_name, ticker, cik, fiscal_year_end) VALUES (%s,'US','x',%s,'0','1231') ON CONFLICT DO NOTHING",
                (issuer_id, issuer_id[-2:]))
    cur.execute("INSERT INTO ingestion_run(run_id, issuer_id, as_of_date, policy_version, status) VALUES (%s,%s,'2026-10-06','v1.1','RUNNING') ON CONFLICT DO NOTHING",
                (run_id, issuer_id))


@pytest.fixture
def pg_conn():
    conn = psycopg.connect(db_url(), autocommit=True)
    cur = conn.cursor()
    cur.execute("DELETE FROM quality_issue WHERE run_id LIKE 'run_qi_%'")
    cur.execute("DELETE FROM normalized_metric WHERE issuer_id = 'issuer_US_QITEST'")
    cur.execute("DELETE FROM filing WHERE filing_id LIKE 'filing_qi_%'")
    cur.execute("DELETE FROM ingestion_run WHERE run_id LIKE 'run_qi_%'")
    cur.execute("DELETE FROM issuer WHERE issuer_id = 'issuer_US_QITEST'")
    yield conn
    cur.execute("DELETE FROM quality_issue WHERE run_id LIKE 'run_qi_%'")
    cur.execute("DELETE FROM normalized_metric WHERE issuer_id = 'issuer_US_QITEST'")
    cur.execute("DELETE FROM filing WHERE filing_id LIKE 'filing_qi_%'")
    cur.execute("DELETE FROM ingestion_run WHERE run_id LIKE 'run_qi_%'")
    cur.execute("DELETE FROM issuer WHERE issuer_id = 'issuer_US_QITEST'")


def test_batch_save_writes_every_issue_with_correct_columns(pg_conn):
    cur = pg_conn.cursor()
    seed_run(cur, "run_qi_1", "issuer_US_QITEST")
    db = DatabaseManager()
    issues = [issue("MISSING_PERIOD", run_id="run_qi_1", filing_id=None, details={"metric_code": "REVENUE", "period": "FY2021"}),
              issue("DIMENSION_AMBIGUITY", run_id="run_qi_1", severity="WARNING", status="OPEN")]
    db.save_quality_issues(issues)
    rows = cur.execute("SELECT issue_id, run_id, rule_code, severity, status, details FROM quality_issue WHERE run_id = 'run_qi_1' ORDER BY issue_id").fetchall()
    assert len(rows) == 2
    by_code = {r[2]: r for r in rows}
    assert by_code["MISSING_PERIOD"][5] == {"metric_code": "REVENUE", "period": "FY2021"}
    assert all(r[1] == "run_qi_1" for r in rows)


def test_batch_save_is_idempotent_on_rerun(pg_conn):
    cur = pg_conn.cursor()
    seed_run(cur, "run_qi_1", "issuer_US_QITEST")
    db = DatabaseManager()
    issues = [issue("MISSING_PERIOD", run_id="run_qi_1")]
    db.save_quality_issues(issues)
    n1 = cur.execute("SELECT COUNT(*) FROM quality_issue WHERE run_id = 'run_qi_1'").fetchone()[0]
    db.save_quality_issues(issues)                                       # same issue_id again
    n2 = cur.execute("SELECT COUNT(*) FROM quality_issue WHERE run_id = 'run_qi_1'").fetchone()[0]
    assert n1 == 1 and n2 == 1


def test_batch_save_empty_list_does_nothing(pg_conn):
    db = DatabaseManager()
    db.save_quality_issues([])      # must not raise, must not touch the connection in a way that breaks later use
    assert db.get_connection() is not None


# ---------------------------------------------------------------- end-to-end: the REAL normalizer's own issues, persisted
def test_real_normalizer_missing_period_issue_is_persisted_via_harness(pg_conn, monkeypatch):
    """
    A filing with no REVENUE/NET_INCOME/OPERATING_INCOME fact triggers normalizer MISSING_PERIOD.
    That issue must come back from Normalizer.normalize(), survive the trip through QualityHarness.validate()
    (as external_issues, exactly as orchestration.py wires it), and land in the quality_issue table.
    """
    cur = pg_conn.cursor()
    seed_run(cur, "run_qi_1", "issuer_US_QITEST")
    issuer = Issuer(issuer_id="issuer_US_QITEST", market="US", legal_name="QI Test", ticker="QITEST", cik="999999999", fiscal_year_end="1231")
    filing = Filing(filing_id="filing_qi_1", issuer_id=issuer.issuer_id, accession_number="0000000000-26-000001", form_type="10-K",
                    filing_date=dt.date(2026, 2, 1), report_period=dt.date(2025, 12, 31), source_uri="u", source_hash="h")
    cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (filing.filing_id, filing.issuer_id, filing.accession_number, filing.form_type, filing.filing_date,
                 filing.report_period, filing.source_uri, filing.source_hash))
    # one fact that is NOT one of the expected metrics, so MISSING_PERIOD fires for REVENUE/NET_INCOME/OPERATING_INCOME
    fact = FactObservation(fact_id="fact_qi_1", canonical_fact_key="k_qi_1", filing_id="filing_qi_1", concept="us-gaap:Assets",
                           value=100.0, unit="USD", currency="USD", instant_date=dt.date(2025, 12, 31))

    class SilentDB(DatabaseManager):
        """Real DatabaseManager (so save_quality_issues really writes), but normalize() must not need any other DB call."""
        def __init__(self):
            super().__init__()

    db = SilentDB()
    normalizer = Normalizer(db_manager=db)
    monkeypatch.setattr(db, "save_fact_observations", lambda facts: facts)   # normalize() saves facts first; stub it out here
    _, metrics, norm_issues = normalizer.normalize(issuer=issuer, filings=[filing], facts=[fact], run_id="run_qi_1")

    assert any(i.rule_code == "MISSING_PERIOD" for i in norm_issues), "the normalizer itself must still raise MISSING_PERIOD"

    harness = QualityHarness(db_manager=db)
    report = harness.validate(run_id="run_qi_1", issuer=issuer, filings=[filing], facts=[fact], versions=[], metrics=metrics,
                              external_issues=norm_issues)

    assert any(i.rule_code == "MISSING_PERIOD" for i in report.issues)
    stored = cur.execute("SELECT rule_code, details FROM quality_issue WHERE run_id = 'run_qi_1' AND rule_code = 'MISSING_PERIOD'").fetchall()
    assert len(stored) >= 1
    assert stored[0][1]["metric_code"] in {"REVENUE", "NET_INCOME", "OPERATING_INCOME"}


# ---------------------------------------------------------------- guard against the exact original regression
def test_orchestration_passes_normalizer_issues_to_the_harness():
    """
    This is the precise bug this step fixes: orchestration.py called
        normalized_facts, metrics, norm_issues = normalizer.normalize(...)
    and then never used norm_issues again, so every issue the normalizer found was silently thrown away.
    A harness-level or db-level test cannot catch that regression (it does not go through orchestration.py at
    all), so this test reads the orchestration source directly and fails if the wiring is ever removed again.
    """
    src = Path(__file__).resolve().parent.parent.joinpath("orchestration.py").read_text(encoding="utf-8")
    assert "norm_issues" in src, "orchestration.py no longer captures the normalizer's issues at all"
    harness_call = src[src.index("harness.validate(") : src.index("harness.validate(") + 600]
    assert "external_issues=norm_issues" in harness_call, (
        "orchestration.py must pass external_issues=norm_issues into harness.validate(), "
        "otherwise the normalizer's MISSING_PERIOD / UNIT_CONSISTENCY / DIMENSION_AMBIGUITY / PERIOD_MAPPING "
        "issues are computed and then discarded, exactly like before this fix."
    )
