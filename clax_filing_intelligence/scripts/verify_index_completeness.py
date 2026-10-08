"""
Acceptance check for Step 1b: does the pipeline's indexer now see every 8-K that a direct SEC query sees?

    python scripts\\verify_index_completeness.py --ticker CF
    python scripts\\verify_index_completeness.py --ticker EXP --as_of 2026-10-06

It runs the REAL indexer code against SEC EDGAR (read-only) but with a database stand-in that throws everything away.
Nothing is read from or written to any database, local or Neon.
"""
import sys
import time
import argparse
from datetime import date, datetime
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class NullDB:
    def save_issuer(self, issuer):
        return None

    def save_filings(self, filings):
        return True


def missing_from_index(indexed_accessions, direct_records, as_of):
    """Records of the direct query (filed up to as_of) whose accession is not among the indexed ones."""
    indexed = set(indexed_accessions)
    out = []
    for r in direct_records:
        d = r.filing_date if isinstance(r.filing_date, date) else datetime.strptime(str(r.filing_date)[:10], "%Y-%m-%d").date()
        if d <= as_of and str(r.accession_number) not in indexed:
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser(description="Compare the pipeline indexer with a direct 8-K query (read-only, no database)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--as_of", default=date.today().isoformat())
    args = ap.parse_args()
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    from pipeline.indexer import FilingIndexer
    t = time.time()
    idx = FilingIndexer(db_manager=NullDB())
    issuer, filings = idx.get_full_filing_index(args.ticker, as_of)
    print(f"\nindexer: {len(filings)} filings for {issuer.ticker} in {time.time() - t:.0f} s")
    print("  by form: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(f.form_type for f in filings).items())))
    print(f"  skipped (unusable records): {len(idx.skipped)}")
    for s in idx.skipped[:10]:
        print(f"      {s['accession']}: {s['reason']}")

    from edgar import Company
    direct = list(Company(args.ticker).get_filings(form="8-K"))
    missing = missing_from_index([f.accession_number for f in filings], direct, as_of)
    eight_k = [f for f in filings if f.form_type == "8-K"]
    print(f"\ndirect 8-K query: {len(direct)} records | indexer 8-Ks: {len(eight_k)}")
    print(f"  [{'PASS' if not missing else 'FAIL'}] every 8-K of the direct query is in the index ({len(missing)} missing)")
    for r in missing[:10]:
        print(f"      {r.accession_number}  filed {r.filing_date}")
    print(f"  [{'PASS' if not idx.skipped else 'INFO'}] no record was skipped")
    no_items = [f for f in eight_k if not f.sec_items]
    print(f"  [{'PASS' if not no_items else 'INFO'}] every 8-K carries item numbers ({len(no_items)} without)")


if __name__ == "__main__":
    main()
