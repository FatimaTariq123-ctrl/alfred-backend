"""
READ-ONLY diagnosis: why does the pipeline's EDGAR index hold fewer 8-Ks than a direct 8-K query?

    python scripts\\diagnose_index_gaps.py --ticker CF
    python scripts\\diagnose_index_gaps.py --ticker CF --accession 0001104659-25-123145 --accession 0001104659-26-003338

It reads from SEC EDGAR only (through edgartools). No database, nothing is written anywhere.
It does what the pipeline indexer does (company.get_filings(), the full list) and compares it with the direct 8-K query.
For every accession that is missing from the full list, or that you name with --accession, it tries to read the
report period the way the OLD indexer did and prints the exact error, if any.
"""
import sys
import time
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    ap = argparse.ArgumentParser(description="Why did the indexer lose filings? (read-only, SEC only)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--accession", action="append", default=[], help="accession number(s) to test even if they are in the list")
    args = ap.parse_args()

    from config.settings import init_edgar_identity
    init_edgar_identity()
    from edgar import Company
    co = Company(args.ticker)

    t = time.time()
    full = list(co.get_filings())                     # exactly what the pipeline indexer iterates
    print(f"full list from company.get_filings(): {len(full)} records ({time.time() - t:.0f} s)")
    direct = list(co.get_filings(form="8-K"))
    print(f"direct 8-K query                    : {len(direct)} records")

    in_full = {str(getattr(f, 'accession_number', '')) for f in full}
    missing = [f for f in direct if str(f.accession_number) not in in_full]
    print(f"\n8-Ks that the direct query has but the full list does NOT have: {len(missing)}")
    for f in missing:
        print(f"    {f.accession_number}  filed {f.filing_date}  items {getattr(f, 'items', '')}")

    by_acc = {str(f.accession_number): f for f in full}
    by_acc.update({str(f.accession_number): f for f in direct})
    targets = [str(f.accession_number) for f in missing] + [a for a in args.accession if a not in {str(m.accession_number) for m in missing}]
    print(f"\nreading the report period the OLD way (item.period_of_report) for {len(targets)} accession(s):")
    for acc in targets:
        rec = by_acc.get(acc)
        if rec is None:
            print(f"    {acc}  NOT FOUND in either list")
            continue
        t = time.time()
        try:
            value = rec.period_of_report
            print(f"    {acc}  OK  period_of_report = {value}   (index reportDate = {getattr(rec, 'report_date', None)!r}, {time.time() - t:.1f} s)")
        except Exception as e:
            print(f"    {acc}  FAILED  {type(e).__name__}: {str(e)[:150]}   (the old indexer silently dropped this filing)")
    print("\nReading: if the accessions are in the full list but FAILED here, the old indexer dropped them silently."
          "\nIf they are NOT in the full list, EDGAR's list itself is short and a direct 8-K query must be used as a cross-check.")


if __name__ == "__main__":
    main()
