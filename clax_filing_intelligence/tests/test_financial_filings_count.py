"""
Team head's "Final Ingestion Fix" blocker: financial_filings and filings_quarantined previously
counted the whole filing window including 8-Ks, then (after a first fix) counted the issuer's
ENTIRE indexed filing history (every 10-K/10-Q ever filed) instead of just the filings THIS RUN
selected for its 5-year analytical window -- for an issuer with decades on file, that inflated
CF to 86 and EXP to 124 instead of the correct 13. Both must now come from the same `filings`
list orchestration.py actually selected for this run (threaded through the payload), never from
re-querying the shared `filing` table, which spans far more than one run's window.
"""
import datetime as dt
import psycopg
from psycopg.rows import dict_row
import pytest

from schema.models import Issuer, Filing, FactObservation, HistoryDecision
from quality.harness import QualityReport
from storage.db import DatabaseManager
from handover.contract import HandoverContractGenerator


def db_url():
    import os
    return os.environ["DATABASE_URL"]


ISSUER_ID = "issuer_US_FFCTEST"


@pytest.fixture
def pg_conn():
    conn = psycopg.connect(db_url(), autocommit=True, row_factory=dict_row)
    cur = conn.cursor()
    for t in ["fact_observation", "filing", "issuer"]:
        cur.execute(f"DELETE FROM {t} WHERE issuer_id = %s" if t != "fact_observation" else
                   "DELETE FROM fact_observation WHERE filing_id LIKE 'filing_ffc_%'", (ISSUER_ID,) if t != "fact_observation" else None)
    yield conn
    for t in ["fact_observation", "filing", "issuer"]:
        cur.execute(f"DELETE FROM {t} WHERE issuer_id = %s" if t != "fact_observation" else
                   "DELETE FROM fact_observation WHERE filing_id LIKE 'filing_ffc_%'", (ISSUER_ID,) if t != "fact_observation" else None)


def seed(cur, n_10k_in_window=5, n_10q_in_window=8, n_8k_in_window=30, n_10k_out_of_window=0, n_10q_out_of_window=0):
    """Seeds the `filing` table exactly like a real issuer: some financial filings are inside this
    run's window, some (older) ones are outside it but still sit in the shared `filing` table because
    the indexer indexes the issuer's whole history."""
    cur.execute("INSERT INTO issuer(issuer_id, market, legal_name, ticker, cik, fiscal_year_end) "
               "VALUES (%s,'US','Test','FFC','1','1231') ON CONFLICT DO NOTHING", (ISSUER_ID,))
    i = 0
    in_window = []
    for _ in range(n_10k_in_window):
        i += 1
        fid = f"filing_ffc_{i}"
        cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
                   "VALUES (%s,%s,%s,'10-K',%s,%s,'u','h')", (fid, ISSUER_ID, f"acc_ffc_{i}", dt.date(2024, 1, 1), dt.date(2023, 12, 31)))
        cur.execute("INSERT INTO fact_observation(fact_id, canonical_fact_key, filing_id, concept, value, unit, currency, period_start, period_end) "
                   "VALUES (%s,%s,%s,'c',1.0,'USD','USD',%s,%s)", (f"fact_ffc_{i}", f"k_ffc_{i}", fid, dt.date(2023, 1, 1), dt.date(2023, 12, 31)))
        in_window.append(fid)
    for _ in range(n_10q_in_window):
        i += 1
        fid = f"filing_ffc_{i}"
        cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
                   "VALUES (%s,%s,%s,'10-Q',%s,%s,'u','h')", (fid, ISSUER_ID, f"acc_ffc_{i}", dt.date(2024, 1, 1), dt.date(2023, 9, 30)))
        cur.execute("INSERT INTO fact_observation(fact_id, canonical_fact_key, filing_id, concept, value, unit, currency, period_start, period_end) "
                   "VALUES (%s,%s,%s,'c',1.0,'USD','USD',%s,%s)", (f"fact_ffc_{i}", f"k_ffc_{i}", fid, dt.date(2023, 7, 1), dt.date(2023, 9, 30)))
        in_window.append(fid)
    for _ in range(n_8k_in_window):
        i += 1
        fid = f"filing_ffc_{i}"
        cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
                   "VALUES (%s,%s,%s,'8-K',%s,%s,'u','h')", (fid, ISSUER_ID, f"acc_ffc_{i}", dt.date(2024, 1, 1), dt.date(2024, 1, 1)))
        in_window.append(fid)
    # out-of-window historical financial filings: in the `filing` table (indexer indexed them), but NOT
    # selected for this run and NOT parsed (no facts) -- exactly like a 20-year-old 10-K still on file
    for _ in range(n_10k_out_of_window):
        i += 1
        cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
                   "VALUES (%s,%s,%s,'10-K',%s,%s,'u','h')", (f"filing_ffc_{i}", ISSUER_ID, f"acc_ffc_{i}", dt.date(2005, 1, 1), dt.date(2004, 12, 31)))
    for _ in range(n_10q_out_of_window):
        i += 1
        cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
                   "VALUES (%s,%s,%s,'10-Q',%s,%s,'u','h')", (f"filing_ffc_{i}", ISSUER_ID, f"acc_ffc_{i}", dt.date(2005, 1, 1), dt.date(2004, 9, 30)))
    return in_window


def test_gate_fields_use_payload_window_count_not_whole_filing_table(pg_conn):
    """The exact real-world bug: filing table has MANY more historical 10-Ks/10-Qs than this run's
    13-filing window (CF really has 86, EXP really has 124, on file) -- financial_filings must reflect
    the window (13), never the full indexed history."""
    cur = pg_conn.cursor()
    seed(cur, n_10k_in_window=5, n_10q_in_window=8, n_8k_in_window=30,
        n_10k_out_of_window=40, n_10q_out_of_window=33)  # +73 historical financial filings, like CF's 86 total

    db = DatabaseManager()
    gate = db._handover_gate_fields(cur, ISSUER_ID, "PASS WITH FLAGS",
                                    {"financial_state": {"provenance_filings_count": 43, "financial_filings_selected": 13, "metrics_summary": {}},
                                     "material_events": [], "handover_blockers": [], "data_quality": {}})
    assert gate["financial_filings"] == 13           # not 86
    assert gate["financial_filings_parsed_ok"] == 13
    assert gate["filings_quarantined"] == 0           # not 73


def test_exp_shaped_124_total_on_file_but_13_in_window(pg_conn):
    cur = pg_conn.cursor()
    seed(cur, n_10k_in_window=5, n_10q_in_window=8, n_8k_in_window=21,
        n_10k_out_of_window=50, n_10q_out_of_window=50)  # +100, like EXP's 124 total

    db = DatabaseManager()
    gate = db._handover_gate_fields(cur, ISSUER_ID, "PASS WITH FLAGS",
                                    {"financial_state": {"provenance_filings_count": 34, "financial_filings_selected": 13, "metrics_summary": {}},
                                     "material_events": [], "handover_blockers": [], "data_quality": {}})
    assert gate["financial_filings"] == 13
    assert gate["filings_quarantined"] == 0


def test_a_selected_financial_filing_with_zero_facts_is_genuinely_quarantined(pg_conn):
    """If a filing IN THIS RUN'S WINDOW truly produced no facts (a real parsing failure), it should
    still count as quarantined -- the fix must not make genuine failures structurally invisible."""
    cur = pg_conn.cursor()
    cur.execute("INSERT INTO issuer(issuer_id, market, legal_name, ticker, cik, fiscal_year_end) "
               "VALUES (%s,'US','Test','FFC','1','1231') ON CONFLICT DO NOTHING", (ISSUER_ID,))
    cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
               "VALUES ('filing_ffc_ok',%s,'acc_ok','10-K',%s,%s,'u','h')", (ISSUER_ID, dt.date(2024,1,1), dt.date(2023,12,31)))
    cur.execute("INSERT INTO fact_observation(fact_id, canonical_fact_key, filing_id, concept, value, unit, currency, period_start, period_end) "
               "VALUES ('fact_ffc_ok','k_ok','filing_ffc_ok','c',1.0,'USD','USD',%s,%s)", (dt.date(2023,1,1), dt.date(2023,12,31)))
    cur.execute("INSERT INTO filing(filing_id, issuer_id, accession_number, form_type, filing_date, report_period, source_uri, source_hash) "
               "VALUES ('filing_ffc_fail',%s,'acc_fail','10-K',%s,%s,'u','h')", (ISSUER_ID, dt.date(2024,1,1), dt.date(2022,12,31)))

    db = DatabaseManager()
    gate = db._handover_gate_fields(cur, ISSUER_ID, "PASS WITH FLAGS",
                                    {"financial_state": {"provenance_filings_count": 2, "financial_filings_selected": 2, "metrics_summary": {}},
                                     "material_events": [], "handover_blockers": [], "data_quality": {}})
    assert gate["financial_filings"] == 2
    assert gate["financial_filings_parsed_ok"] == 1
    assert gate["filings_quarantined"] == 1


def test_contract_computes_financial_filings_selected_from_the_run_window_only():
    """generate_contract() itself must compute financial_filings_selected purely from its own
    `filings` parameter (this run's window) -- the thing orchestration.py actually selected --
    never by querying the DB for the issuer's whole history."""
    issuer = Issuer(issuer_id="issuer_US_FFC2", market="US", legal_name="FFC", ticker="FFC", cik="1", fiscal_year_end="1231")
    filings = (
        [Filing(filing_id=f"tenk_{i}", issuer_id=issuer.issuer_id, accession_number=f"a{i}", form_type="10-K",
               filing_date=dt.date(2024,1,1), report_period=dt.date(2023,12,31), source_uri="u", source_hash="h") for i in range(5)]
        + [Filing(filing_id=f"tenq_{i}", issuer_id=issuer.issuer_id, accession_number=f"b{i}", form_type="10-Q",
               filing_date=dt.date(2024,1,1), report_period=dt.date(2023,9,30), source_uri="u", source_hash="h") for i in range(8)]
        + [Filing(filing_id=f"8k_{i}", issuer_id=issuer.issuer_id, accession_number=f"c{i}", form_type="8-K",
               filing_date=dt.date(2024,1,1), report_period=dt.date(2024,1,1), source_uri="u", source_hash="h") for i in range(30)]
    )
    history_decision = HistoryDecision(decision_id="hd1", run_id="r1", issuer_id=issuer.issuer_id, mode="NORMAL", years_selected=5, triggers=[], policy_version="v1.1")
    quality_report = QualityReport(run_id="r1", issuer_id=issuer.issuer_id, is_valid=True, issues=[],
                                   total_filings_evaluated=43, total_facts_evaluated=100, total_issues=0,
                                   blocker_count=0, warning_count=0, info_count=0,
                                   reconciled_count=8, reconciliation_total=8)

    gen = HandoverContractGenerator()
    state = gen.generate_contract(issuer=issuer, as_of_date=dt.date(2026,10,6), history_decision=history_decision,
                                  filings=filings, metrics=[], versions=[], events=[], quality_report=quality_report)
    assert state.financial_state["provenance_filings_count"] == 43
    assert state.financial_state["financial_filings_selected"] == 13   # 5 + 8, not 43
