"""
Deletes ALL pipeline rows of ONE issuer (for example the leftovers of a crashed run), and nothing else.

    python scripts\\purge_issuer.py --ticker EXP              <- DRY RUN: only counts, deletes nothing
    python scripts\\purge_issuer.py --ticker EXP --confirm    <- asks you to type  DELETE EXP  and then deletes

It touches ONLY these 12 pipeline tables, only rows that belong to issuer_US_<TICKER>:
  quality_issue, fact_version, normalized_metric, material_event, history_decision, fie_company_state,
  text_chunk, fact_observation, filing_asset, filing, ingestion_run, issuer (the issuer row itself is kept
  unless you pass --drop-issuer).
Other issuers and every other table of the database (for example the trading app's tables) are never touched.
Everything runs in ONE transaction: if anything fails, nothing is deleted.
The database is reached through DatabaseManager, so a non-local DB needs CLAX_ALLOW_REMOTE_DB=1 (same guard as the pipeline).
"""
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager  # noqa: E402

# (label, SELECT count, DELETE) -- order matters (foreign keys): children first
FILINGS = "(SELECT filing_id FROM filing WHERE issuer_id = %(i)s)"
FACTS = f"(SELECT fact_id FROM fact_observation WHERE filing_id IN {FILINGS})"
RUNS = "(SELECT run_id FROM ingestion_run WHERE issuer_id = %(i)s)"
STEPS = [
    ("quality_issue", f"FROM quality_issue WHERE run_id IN {RUNS} OR filing_id IN {FILINGS} OR fact_id IN {FACTS}"),
    ("fact_version", f"FROM fact_version WHERE original_fact_id IN {FACTS} OR preferred_fact_id IN {FACTS}"),
    ("normalized_metric", "FROM normalized_metric WHERE issuer_id = %(i)s"),
    ("material_event", "FROM material_event WHERE issuer_id = %(i)s"),
    ("history_decision", f"FROM history_decision WHERE issuer_id = %(i)s OR run_id IN {RUNS}"),
    ("fie_company_state", f"FROM fie_company_state WHERE issuer_id = %(i)s OR run_id IN {RUNS}"),
    ("text_chunk", f"FROM text_chunk WHERE filing_id IN {FILINGS}"),
    ("fact_observation", f"FROM fact_observation WHERE filing_id IN {FILINGS}"),
    ("filing_asset", f"FROM filing_asset WHERE filing_id IN {FILINGS}"),
    ("filing", "FROM filing WHERE issuer_id = %(i)s"),
    ("ingestion_run", "FROM ingestion_run WHERE issuer_id = %(i)s"),
]


def main():
    ap = argparse.ArgumentParser(description="Delete all pipeline rows of one issuer (dry run unless --confirm)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--confirm", action="store_true", help="really delete (you will also have to type DELETE <TICKER>)")
    ap.add_argument("--drop-issuer", action="store_true", help="also delete the issuer row itself")
    args = ap.parse_args()
    ticker = args.ticker.upper()
    p = {"i": f"issuer_US_{ticker}"}

    db = DatabaseManager()                     # prints the target host
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM issuer WHERE issuer_id = %(i)s", p)
    if not cur.fetchone():
        print(f"No issuer {p['i']} in this database. Nothing to do.")
        sys.exit(0)

    print(f"\nHost: {db.host}   Database: {db.dbname}   Issuer: {p['i']}")
    print("\nRows that belong to this issuer:")
    total = 0
    counts = {}
    for name, frm in STEPS:
        cur.execute(f"SELECT COUNT(*) AS n {frm}", p)
        counts[name] = cur.fetchone()["n"]
        total += counts[name]
        print(f"   {name:20} {counts[name]:>8}")
    cur.execute("SELECT COUNT(*) AS n FROM issuer WHERE issuer_id <> %(i)s", p)
    print(f"\n   (rows of OTHER issuers are never touched; there are {cur.fetchone()['n']} other issuer(s) in this database)")
    conn.rollback()

    if not args.confirm:
        print(f"\nDRY RUN: nothing was deleted. {total} rows would be deleted.")
        print(f"To really delete:  python scripts\\purge_issuer.py --ticker {ticker} --confirm")
        return

    typed = input(f"\nThis DELETES {total} rows from {db.dbname} on {db.host}.\nType  DELETE {ticker}  to continue: ").strip()
    if typed != f"DELETE {ticker}":
        print("Not confirmed. Nothing was deleted.")
        return
    try:
        # the filing table points to itself (amendment -> base filing): break those links first
        cur.execute("UPDATE filing SET base_filing_id = NULL WHERE issuer_id = %(i)s", p)
        for name, frm in STEPS:
            cur.execute(f"DELETE {frm}", p)
            print(f"   deleted {cur.rowcount:>8} from {name}")
        if args.drop_issuer:
            cur.execute("DELETE FROM issuer WHERE issuer_id = %(i)s", p)
            print(f"   deleted {cur.rowcount:>8} from issuer")
        conn.commit()
        print("\nDONE. All deletes were committed together.")
    except Exception as e:
        conn.rollback()
        print(f"\nFAILED, everything was rolled back, nothing was deleted: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
