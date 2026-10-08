"""
LOCAL-ONLY test: does the project's DB layer survive a dropped connection?

Run (project folder, venv active):
    python scripts\\connection_kill_test.py

It creates a temporary issuer 'ZZTEST' with a few test rows, then kills this process's own DB connection
from a second connection (like the pooler / network does) and checks that each kind of write and read still works.
At the end it deletes only its own test rows. It refuses to run on a non-local database.
"""
import sys
import time
import uuid
import logging
from pathlib import Path
from datetime import date, datetime, timezone
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402
from storage.db import DatabaseManager  # noqa: E402
from schema.models import Issuer, Filing, FactObservation, NormalizedMetric, FilingAsset  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="        log> %(message)s")
ISS, FIL, ACC = "issuer_US_ZZTEST", "filing_ZZTEST_1", "ZZTEST-0000-000001"


def main():
    db = DatabaseManager()                                   # prints the target host
    if getattr(db, "host", "") not in ("localhost", "127.0.0.1", "::1"):
        sys.exit("STOP: this test only runs on a LOCAL database.")
    if hasattr(db, "PING_AFTER_IDLE_SECONDS"):
        db.PING_AFTER_IDLE_SECONDS = 10 ** 6                 # switch the idle check off: test the retry path itself
    ctl = psycopg.connect(db.url, autocommit=True)           # second connection: kills and counts

    def count(sql, *p):
        return ctl.execute(sql, p).fetchone()[0]

    def kill():
        pid = db.get_connection().info.backend_pid
        ctl.execute("SELECT pg_terminate_backend(%s)", (pid,))
        time.sleep(0.3)

    def fact(i):
        return FactObservation(fact_id=f"zz{uuid.uuid4().hex[:12]}", canonical_fact_key=f"zzkey{i:04d}", filing_id=FIL,
                               concept=f"test:ZZ{i}", value=float(i), unit="USD", currency="USD",
                               period_end=date(2026, 3, 31), context_ref="c", parser_version="test")

    results = []

    def case(name, fn):
        try:
            ok, detail = fn()
        except Exception as e:                               # a missing method or an unhandled error is a FAIL, not a crash
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))

    flaky = {"n": 0}
    real_commit = psycopg.Connection.commit

    def flaky_commit(self):                                  # the production error, once: pooler says "database removed"
        flaky["n"] += 1
        if flaky["n"] == 1:
            raise psycopg.errors.ProtocolViolation("database removed")
        return real_commit(self)

    try:
        db.save_issuer(Issuer(issuer_id=ISS, market="US", legal_name="ZZ Test", ticker="ZZTEST", cik="0", fiscal_year_end="1231"))
        db.save_filing(Filing(filing_id=FIL, issuer_id=ISS, accession_number=ACC, form_type="10-K", filing_date=date(2026, 3, 1),
                              report_period=date(2025, 12, 31), source_uri="u", source_hash="h"))
        print("\n=== CONNECTION KILL TEST (local DB, temporary issuer ZZTEST) ===")

        def c1():
            kill()
            db.save_fact_observations([fact(i) for i in range(30)])
            n = count("SELECT COUNT(*) FROM fact_observation WHERE filing_id = %s", FIL)
            return n == 30, f"{n} of 30 facts stored"
        case("1. connection killed, then BATCH write of facts", c1)

        def c2():
            kill()
            ms = [NormalizedMetric(metric_id=f"zzm{i}", issuer_id=ISS, metric_code="REVENUE", period=f"FY{2000 + i}", value=float(i), unit="USD",
                                   provenance_fact_ids=[], provenance_filing_ids=[FIL], comparability_status="COMPARABLE", is_derived=False)
                  for i in range(5)]
            db.save_normalized_metrics(ms)
            n = count("SELECT COUNT(*) FROM normalized_metric WHERE issuer_id = %s", ISS)
            return n == 5, f"{n} of 5 metrics stored"
        case("2. connection killed, then BATCH write of metrics", c2)

        def c3():
            kill()
            db.save_filing_asset(FilingAsset(asset_id="zzasset1", filing_id=FIL, asset_type="IXBRL", storage_uri="file:///x",
                                             mime_type="text/html", hash="h", retrieved_at=datetime.now(timezone.utc)))
            n = count("SELECT COUNT(*) FROM filing_asset WHERE filing_id = %s", FIL)
            return n == 1, f"{n} of 1 asset stored"
        case("3. connection killed, then ONE-ROW write (save_filing_asset)", c3)

        def c4():
            kill()
            rows = db.get_filing_assets(FIL)
            return len(rows) == 1, f"{len(rows)} of 1 row read"
        case("4. connection killed, then a READ (get_filing_assets)", c4)

        def c5():
            flaky["n"] = 0
            with mock.patch.object(psycopg.Connection, "commit", flaky_commit):
                db.save_fact_observations([fact(100 + i) for i in range(10)])
            n = count("SELECT COUNT(*) FROM fact_observation WHERE filing_id = %s AND concept LIKE 'test:ZZ1__'", FIL)
            return n == 10, f"{n} of 10 stored, commit tried {flaky['n']} times"
        case("5. production error 'ProtocolViolation: database removed' at COMMIT, in a BATCH write", c5)

        def c6():
            flaky["n"] = 0
            with mock.patch.object(psycopg.Connection, "commit", flaky_commit):
                db.save_fact_observation(fact(200))
            n = count("SELECT COUNT(*) FROM fact_observation WHERE concept = 'test:ZZ200'")
            return n == 1, f"{n} of 1 stored, commit tried {flaky['n']} times"
        case("6. same error in a ONE-ROW write (save_fact_observation)", c6)

        def c7():
            before = count("SELECT COUNT(*) FROM fact_observation WHERE filing_id = %s", FIL)
            kill()
            db.save_fact_observations([fact(i) for i in range(30)])          # same 30 facts again, new random ids
            after = count("SELECT COUNT(*) FROM fact_observation WHERE filing_id = %s", FIL)
            return before == after, f"rows before {before}, after {after} (must be equal: no double writes)"
        case("7. same batch sent again after a kill: no duplicates", c7)
    finally:
        for sql in ("DELETE FROM normalized_metric WHERE issuer_id = %s", "DELETE FROM fact_observation WHERE filing_id = %s",
                    "DELETE FROM filing_asset WHERE filing_id = %s", "DELETE FROM filing WHERE filing_id = %s",
                    "DELETE FROM issuer WHERE issuer_id = %s"):
            try:
                ctl.execute(sql, (FIL if "filing_id" in sql else ISS,))
            except Exception as e:
                print(f"  (cleanup warning: {e})")
        print("  (test rows removed)")

    print(f"\n=== RESULT: {sum(results)} PASS, {len(results) - sum(results)} FAIL (of {len(results)}) ===")


if __name__ == "__main__":
    main()
