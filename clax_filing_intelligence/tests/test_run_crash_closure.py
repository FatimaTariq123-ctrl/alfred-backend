"""
Step 6 (team head items 1/6): a crashed or interrupted run must never leave ingestion_run.status at
"RUNNING" forever. Production held 11 such abandoned rows for CF and 2 for EXP. orchestration.py had no
top-level exception handling, so any failure anywhere in the pipeline (network error, Ctrl+C, a bug in any
stage) left the row exactly as it started: RUNNING, completed_at NULL.
"""
import datetime as dt
import psycopg
import pytest

from storage.db import DatabaseManager
from pipeline.indexer import FilingIndexer
import orchestration


@pytest.fixture
def pg_conn():
    import os
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    conn.execute("DELETE FROM ingestion_run WHERE issuer_id = 'issuer_US_CRASHTEST'")
    conn.execute("DELETE FROM issuer WHERE issuer_id = 'issuer_US_CRASHTEST'")
    yield conn
    conn.execute("DELETE FROM ingestion_run WHERE issuer_id = 'issuer_US_CRASHTEST'")
    conn.execute("DELETE FROM issuer WHERE issuer_id = 'issuer_US_CRASHTEST'")


def test_a_stage_failure_marks_the_run_failed_not_left_running(pg_conn, monkeypatch):
    def boom(self, ticker_or_cik, as_of_date):
        raise RuntimeError("simulated SEC outage")
    monkeypatch.setattr(FilingIndexer, "get_full_filing_index", boom)

    db = DatabaseManager()
    with pytest.raises(RuntimeError, match="simulated SEC outage"):
        orchestration.run_filing_intelligence(ticker_or_cik="CRASHTEST", as_of_date=dt.date(2026, 10, 6), db_manager=db)

    row = pg_conn.execute("SELECT status, completed_at FROM ingestion_run WHERE issuer_id = 'issuer_US_CRASHTEST'").fetchone()
    assert row is not None, "the run row must exist (it is written before the pipeline body runs)"
    assert row[0] == "FAILED"
    assert row[1] is not None, "completed_at must be set, not left NULL like an abandoned RUNNING row"


def test_the_real_exception_still_propagates_to_the_caller(monkeypatch):
    """The fix must not swallow the error -- the caller (run_pipeline.py, or whoever scripted the run) still
    needs to see what actually failed."""
    def boom(self, ticker_or_cik, as_of_date):
        raise ValueError("a specific, identifiable failure")
    monkeypatch.setattr(FilingIndexer, "get_full_filing_index", boom)
    db = DatabaseManager()
    with pytest.raises(ValueError, match="a specific, identifiable failure"):
        orchestration.run_filing_intelligence(ticker_or_cik="CRASHTEST", as_of_date=dt.date(2026, 10, 6), db_manager=db)
