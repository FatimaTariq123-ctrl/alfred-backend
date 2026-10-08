"""
READ-ONLY diagnosis for a reported gap: why does a metric (RECEIVABLES, SHORT_TERM_DEBT, PAYABLES, ...)
have fewer years/quarters than the rest? For every missing (metric, period), it shows every XBRL concept
actually stored in fact_observation for that filing whose LOCAL NAME looks related (same keyword), so you
can tell a tag-naming change (fix the policy's tag list) apart from a real "the company did not report
this" absence (nothing to fix).

    python scripts\\diagnose_tag_gaps.py --ticker CF --metric RECEIVABLES
    python scripts\\diagnose_tag_gaps.py --ticker CF --metric SHORT_TERM_DEBT --metric PAYABLES

Reads from the local database only (uses DatabaseManager, so it refuses a non-local DB the same way the
rest of the pipeline does). Writes nothing.
"""
import sys
import re
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager  # noqa: E402
from config.policy import DEFAULT_POLICY  # noqa: E402


_GENERIC_WORDS = {"net", "current", "noncurrent", "gross", "total", "loss", "income", "value", "amount", "of", "and"}


def keywords_from_tags(tags):
    """Significant CamelCase words shared by the policy's tags (e.g. "Receivable" out of both
    "AccountsReceivableNetCurrent" and, if the filer used an older tag, "ReceivablesNetCurrent"),
    so a renamed tag with the same core word is still found. Falls back to every word of the first
    tag when the tags share nothing (still useful: shows what IS there, even if unrelated)."""
    def words(tag):
        return [w.lower() for w in re.findall(r"[A-Z][a-z]*", tag) if len(w) > 3 and w.lower() not in _GENERIC_WORDS]
    per_tag = [set(words(t)) for t in tags]
    shared = set.intersection(*per_tag) if len(per_tag) > 1 else set()
    return sorted(shared) if shared else sorted(set(words(tags[0])))


def main():
    ap = argparse.ArgumentParser(description="Diagnose a missing-period gap for one or more metrics (read-only, local DB only)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--metric", action="append", required=True, help="metric code(s) to check, e.g. RECEIVABLES")
    args = ap.parse_args()
    issuer_id = f"issuer_US_{args.ticker.upper()}"

    db = DatabaseManager()  # prints "[DatabaseManager] Target DB: host=..." -- must say localhost
    conn = db.get_connection()
    conn.rollback()
    cur = conn.cursor()

    for metric_code in args.metric:
        cfg = DEFAULT_POLICY.required_metrics.get(metric_code)
        if not cfg:
            print(f"\n{metric_code}: not a known metric code (check config/policy.py DEFAULT_REQUIRED_METRICS)")
            continue
        tags = cfg["tags"]
        keywords = keywords_from_tags(tags)
        print(f"\n=== {metric_code}  (policy tags: {tags}, period_type={cfg['period_type']}, searching for: {keywords}) ===")

        have = cur.execute(
            "SELECT period FROM normalized_metric WHERE issuer_id = %s AND metric_code = %s ORDER BY period",
            (issuer_id, metric_code)
        ).fetchall()
        have_periods = {r["period"] for r in have}
        print(f"  periods this metric HAS: {sorted(have_periods)}")

        filings = cur.execute(
            "SELECT filing_id, form_type, report_period, accession_number FROM filing "
            "WHERE issuer_id = %s AND form_type IN ('10-K','10-K/A','10-Q','10-Q/A') ORDER BY report_period",
            (issuer_id,)
        ).fetchall()
        if not filings:
            print("  no 10-K/10-Q filings indexed for this issuer locally.")
            continue

        for f in filings:
            exact = cur.execute(
                "SELECT value FROM fact_observation WHERE filing_id = %s AND concept = ANY(%s) AND dimensions IS NULL",
                (f["filing_id"], [f"us-gaap:{t}" for t in tags])
            ).fetchall()
            if exact:
                continue  # this filing has the metric; nothing to diagnose here
            pattern = "|".join(keywords) or "$impossible$"
            similar = cur.execute(
                "SELECT DISTINCT concept FROM fact_observation WHERE filing_id = %s AND concept ~* %s ORDER BY concept",
                (f["filing_id"], pattern)
            ).fetchall()
            print(f"  MISSING in {f['form_type']} {f['accession_number']} (report_period {f['report_period']}):")
            if similar:
                print(f"      concepts in this filing containing one of {keywords} (possible tag-naming change):")
                for row in similar:
                    print(f"          {row['concept']}")
            else:
                print(f"      no concept containing any of {keywords} found in this filing at all "
                      f"(the company likely did not report this line item for this period)")

    conn.rollback()


if __name__ == "__main__":
    main()
