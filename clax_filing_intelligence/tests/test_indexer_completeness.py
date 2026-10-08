"""
Step 1b: the indexer must not lose filings silently, and must not download a filing just to learn its report period.
No network, no database: a fake EDGAR Company and a fake DB.
"""
import datetime as dt
import logging
import pytest

import edgar
from pipeline.indexer import FilingIndexer


class Rec:
    """One EDGAR index record. period_of_report mimics edgartools: reading it costs a download and may fail."""
    def __init__(self, form, acc, filing_date, report_date="", header=None, header_error=None, items=""):
        self.form, self.accession_number, self.filing_date = form, acc, filing_date
        self.report_date = report_date
        self.items = items
        self._header, self._header_error = header, header_error
        self.header_reads = 0

    @property
    def period_of_report(self):
        self.header_reads += 1
        if self._header_error:
            raise self._header_error
        return self._header


class FakeDB:
    def __init__(self):
        self.saved = []

    def save_issuer(self, issuer): pass

    def save_filings(self, filings):
        self.saved.extend(filings)
        return True


def run_index(monkeypatch, records, as_of=dt.date(2026, 10, 6)):
    class Co:
        cik, name, fiscal_year_end = 1324404, "CF Industries", "1231"
        def __init__(self, t): pass
        def get_filings(self): return records
    monkeypatch.setattr(edgar, "Company", Co)
    db = FakeDB()
    idx = FilingIndexer(db_manager=db)
    _, filings = idx.get_full_filing_index("CF", as_of)
    return idx, filings, db


def test_report_period_comes_from_the_index_and_nothing_is_downloaded(monkeypatch):
    r = Rec("10-Q", "0001324404-26-000013", dt.date(2026, 5, 7), report_date="2026-03-31", header=dt.date(1999, 1, 1))
    _, filings, _ = run_index(monkeypatch, [r])
    assert filings[0].report_period == dt.date(2026, 3, 31)
    assert r.header_reads == 0                      # the SGML header was never touched


def test_header_is_the_fallback_when_the_index_has_no_report_date(monkeypatch):
    r = Rec("10-K", "0001324404-26-000007", dt.date(2026, 2, 25), report_date="", header=dt.date(2025, 12, 31))
    _, filings, _ = run_index(monkeypatch, [r])
    assert filings[0].report_period == dt.date(2025, 12, 31)
    assert r.header_reads == 1                      # read once, not twice


def test_a_failing_header_read_keeps_the_filing(monkeypatch, caplog):
    r = Rec("8-K", "0001104659-25-123145", dt.date(2025, 12, 19), report_date="", header_error=RuntimeError("SEC timeout"), items="5.02,9.01")
    with caplog.at_level(logging.WARNING):
        idx, filings, db = run_index(monkeypatch, [r])
    assert [f.accession_number for f in filings] == ["0001104659-25-123145"]       # kept, not silently dropped
    assert filings[0].report_period == dt.date(2025, 12, 19)                         # filing date as the stated fallback
    assert filings[0].sec_items == ["5.02", "9.01"]
    assert idx.skipped == []
    assert any("could not be read" in m for m in caplog.messages)


def test_unusable_records_are_listed_and_warned_never_silent(monkeypatch, caplog):
    good = Rec("8-K", "0001324404-26-000017", dt.date(2026, 8, 5), report_date="2026-08-05")
    no_acc = Rec("8-K", "", dt.date(2026, 8, 6))
    no_form = Rec("", "0001324404-26-000018", dt.date(2026, 8, 7))
    bad_date = Rec("8-K", "0001324404-26-000019", "not a date")
    with caplog.at_level(logging.WARNING):
        idx, filings, _ = run_index(monkeypatch, [good, no_acc, no_form, bad_date])
    assert [f.accession_number for f in filings] == ["0001324404-26-000017"]
    assert len(idx.skipped) == 3
    assert {s["accession"] for s in idx.skipped} >= {"0001324404-26-000018", "0001324404-26-000019"}
    assert all(s["reason"] for s in idx.skipped)
    assert any("skipped 3 EDGAR record" in m for m in caplog.messages)


def test_filings_after_the_analysis_date_are_ignored_and_not_reported_as_errors(monkeypatch):
    future = Rec("8-K", "0001324404-26-000099", dt.date(2026, 12, 1), report_date="2026-12-01")
    idx, filings, _ = run_index(monkeypatch, [future, Rec("8-K", "0001324404-26-000017", dt.date(2026, 8, 5), report_date="2026-08-05")])
    assert [f.accession_number for f in filings] == ["0001324404-26-000017"]
    assert idx.skipped == []


def test_amendment_still_links_to_its_base_using_the_index_period(monkeypatch):
    base = Rec("10-K", "0001324404-26-000007", dt.date(2026, 2, 25), report_date="2025-12-31")
    amend = Rec("10-K/A", "0001324404-26-000030", dt.date(2026, 4, 1), report_date="2025-12-31")
    _, filings, db = run_index(monkeypatch, [base, amend])
    by_acc = {f.accession_number: f for f in filings}
    assert by_acc["0001324404-26-000030"].amendment_flag is True
    assert by_acc["0001324404-26-000030"].base_filing_id == by_acc["0001324404-26-000007"].filing_id


def test_every_record_is_processed_exactly_once(monkeypatch):
    recs = [Rec("10-Q", f"0001324404-25-{n:06d}", dt.date(2025, 5, 1) + dt.timedelta(days=n), report_date="", header=dt.date(2025, 3, 31)) for n in range(5)]
    _, filings, db = run_index(monkeypatch, recs)
    assert len(filings) == 5 and len(db.saved) == 5
    assert all(r.header_reads == 1 for r in recs)   # the old two-pass code read each header twice


def test_verify_script_finds_missing_accessions():
    import importlib.util, pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "verify_index_completeness.py"
    spec = importlib.util.spec_from_file_location("verify_index_completeness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    direct = [Rec("8-K", "A-1", dt.date(2026, 1, 1)), Rec("8-K", "A-2", dt.date(2026, 1, 2)), Rec("8-K", "A-3", dt.date(2027, 1, 1))]
    missing = mod.missing_from_index(["A-1"], direct, dt.date(2026, 10, 6))
    assert [m.accession_number for m in missing] == ["A-2"]          # A-3 is after the analysis date, so it does not count
