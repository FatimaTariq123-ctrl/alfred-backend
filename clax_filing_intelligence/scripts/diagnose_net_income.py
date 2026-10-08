"""
READ-ONLY, focused follow-up on claim 2 (CF NET_INCOME): the earlier diagnostic only looked at
10-K filings. This one looks at EVERY form type that carries us-gaap:NetIncomeLoss or
us-gaap:ProfitLoss, and runs the REAL policy's parent-attribution matching logic against the
REAL stored facts (not a hand-reconstructed copy), period by period, to show exactly which
periods resolve and which do not, and why.

    python scripts\\diagnose_net_income.py --ticker CF

Nothing is written.
"""
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager  # noqa: E402
from config.policy import DEFAULT_POLICY  # noqa: E402
from pipeline.normalizer import Normalizer  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Focused NET_INCOME diagnostic across every form type (read-only)")
    ap.add_argument("--ticker", required=True)
    args = ap.parse_args()
    issuer_id = f"issuer_US_{args.ticker.upper()}"
    cfg = DEFAULT_POLICY.required_metrics["NET_INCOME"]
    tags = cfg["tags"]
    parent_dim = cfg.get("attributable_to_parent_dimension")
    print(f"NET_INCOME tags: {tags}  |  parent-attribution dimension: {parent_dim}")

    db = DatabaseManager()
    conn = db.get_connection()
    conn.rollback()
    cur = conn.cursor()

    concepts = [f"us-gaap:{t}" for t in tags]
    rows = cur.execute(
        "SELECT fo.fact_id, fo.filing_id, f.form_type, f.filing_date, f.report_period, fo.concept, fo.value, "
        "fo.period_start, fo.period_end, fo.instant_date, fo.dimensions "
        "FROM fact_observation fo JOIN filing f USING (filing_id) "
        "WHERE f.issuer_id = %s AND fo.concept = ANY(%s) ORDER BY f.report_period DESC, f.form_type, fo.concept",
        (issuer_id, concepts)
    ).fetchall()
    print(f"\n{len(rows)} total raw facts across ALL form types for {concepts}\n")

    by_form = defaultdict(int)
    for r in rows:
        by_form[r["form_type"]] += 1
    print("  by form type:", dict(by_form))

    print("\n  every row NOT from a 10-K / 10-K/A (these were missing from the earlier diagnostic):")
    non_10k = [r for r in rows if r["form_type"] not in ("10-K", "10-K/A")]
    for r in non_10k:
        dims = r["dimensions"] if r["dimensions"] else {}
        print(f"      {r['form_type']:8} filed={r['filing_date']} report_period={r['report_period']}  concept={r['concept']:22} "
              f"value={r['value']:>15}  period={r['period_start']}..{r['period_end']}  instant={r['instant_date']}  dims={json.dumps(dims)}")
    if not non_10k:
        print("      (none -- NET_INCOME is only reported via 10-K/10-K/A for this issuer)")

    print("\n  grouped by (period_start, period_end, dimensions) across ALL form types, to see exactly what")
    print("  the normalizer's per-period candidate groups would look like:")
    groups = defaultdict(list)
    for r in rows:
        dims_key = json.dumps(r["dimensions"] if r["dimensions"] else {}, sort_keys=True)
        groups[(r["period_start"], r["period_end"], dims_key)].append(r)
    for (ps, pe, dims_key), grp in sorted(groups.items(), key=lambda kv: (kv[0][1] or "", kv[0][2])):
        values = sorted({g["value"] for g in grp})
        if len(values) > 1:
            print(f"      ** CONFLICT ** period={ps}..{pe} dims={dims_key}: {len(grp)} facts, VALUES DIFFER: {values}")

    conn.rollback()


if __name__ == "__main__":
    main()
