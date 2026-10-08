"""
READ-ONLY root-cause check for why a VALUE_CHANGE keeps landing in RECAST_COMPARATIVE: pulls the raw
period_start / period_end / instant_date / canonical_fact_key / parser_version of the exact fact pairs
behind the real RESTATEMENT_OR_REVISION events, straight from fact_observation, so the real dates decide
the fix instead of another guess.

    python scripts\\diagnose_revision_dates.py --ticker CF

Nothing is written. Uses DatabaseManager (same local/remote guard as the rest of the pipeline).
"""
import sys
from pathlib import Path
import argparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Show the raw dates behind RESTATEMENT_OR_REVISION fact pairs (read-only)")
    ap.add_argument("--ticker", required=True)
    args = ap.parse_args()
    issuer_id = f"issuer_US_{args.ticker.upper()}"

    db = DatabaseManager()
    conn = db.get_connection()
    conn.rollback()
    cur = conn.cursor()

    events = cur.execute(
        "SELECT event_id, details->>'concept' AS concept, details->>'original_filing_id' AS orig_fid, "
        "details->>'preferred_filing_id' AS pref_fid, details->>'revision_category' AS category, "
        "details->>'canonical_fact_key' AS ckey "
        "FROM material_event WHERE issuer_id = %s AND event_type = 'RESTATEMENT_OR_REVISION' ORDER BY concept",
        (issuer_id,)
    ).fetchall()
    print(f"{len(events)} RESTATEMENT_OR_REVISION events for {issuer_id}\n")

    for e in events:
        rows = cur.execute(
            "SELECT fact_id, filing_id, period_start, period_end, instant_date, parser_version, value "
            "FROM fact_observation WHERE canonical_fact_key = %s ORDER BY filing_id",
            (e["ckey"],)
        ).fetchall()
        fmap = cur.execute(
            "SELECT filing_id, form_type, filing_date, report_period FROM filing WHERE filing_id = ANY(%s)",
            ([r["filing_id"] for r in rows],)
        ).fetchall()
        fmap = {f["filing_id"]: f for f in fmap}
        print(f"=== {e['concept']}  category={e['category']} ===")
        for r in rows:
            f = fmap.get(r["filing_id"], {})
            print(f"    fact={r['fact_id']:20} filing={r['filing_id']:30} form={f.get('form_type')} "
                  f"filing_date={f.get('filing_date')} report_period={f.get('report_period')} "
                  f"period_start={r['period_start']} period_end={r['period_end']} instant_date={r['instant_date']} "
                  f"parser_version={r['parser_version']} value={r['value']}")
        print()

    conn.rollback()


if __name__ == "__main__":
    main()
