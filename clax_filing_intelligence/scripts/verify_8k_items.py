"""
Acceptance check for Step 1: classify the REAL 8-K filings of a company from their SEC item numbers.

    python scripts\\verify_8k_items.py --ticker CF
    python scripts\\verify_8k_items.py --ticker EXP --as_of 2026-10-06 --months 24

It only READS from SEC EDGAR (through edgartools). It uses no database at all: nothing is read from or written to
any DB, local or Neon. The result tells you, for every 8-K in the event window:
  - the item numbers EDGAR lists for it,
  - the event type(s) the pipeline would now emit,
  - whether anything is still typed MAJOR_ACQUISITION (must be none, unless item 2.01),
  - 8-Ks filed on the same day (possible duplicate submissions), with their items side by side.
"""
import sys
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schema.models import Issuer, Filing  # noqa: E402
from pipeline.events import MaterialEventEmitter  # noqa: E402
from pipeline.indexer import parse_sec_items  # noqa: E402


class NullDB:
    """The emitter saves events through a DB object; this one throws everything away."""
    def save_material_events(self, events):
        return None


def _as_date(v):
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def months_back(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, 28))


def filings_from_company(company, as_of: date, months: int):
    """Builds Filing objects (with sec_items) for the 8-Ks of the window from an edgartools Company-like object."""
    cutoff = months_back(as_of, months)
    out = []
    for item in company.get_filings(form="8-K"):
        d = _as_date(item.filing_date)
        if d > as_of or d < cutoff:
            continue
        acc = str(item.accession_number)
        out.append(Filing(
            filing_id=f"filing_{acc.replace('-', '_')}", issuer_id="issuer_US_CHECK", accession_number=acc, form_type="8-K",
            filing_date=d, report_period=d, source_uri="", source_hash="",
            sec_items=parse_sec_items(getattr(item, "items", None)),
        ))
    return sorted(out, key=lambda f: (f.filing_date, f.accession_number))


def classify(filings, ticker="CHECK"):
    issuer = Issuer(issuer_id="issuer_US_CHECK", market="US", legal_name=ticker, ticker=ticker)
    emitter = MaterialEventEmitter(db_manager=NullDB())
    events = emitter.emit_events(issuer, filings, [])
    by_filing = defaultdict(list)
    for e in events:
        by_filing[e.filing_id].append(e)
    return events, by_filing, emitter.notes


def main():
    ap = argparse.ArgumentParser(description="Classify the real 8-Ks of a company from their SEC items (read-only, no database)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--as_of", default=date.today().isoformat())
    ap.add_argument("--months", type=int, default=24, help="event window in months (the pipeline policy uses 24)")
    args = ap.parse_args()
    as_of = _as_date(args.as_of)

    from config.settings import init_edgar_identity
    init_edgar_identity()
    from edgar import Company
    company = Company(args.ticker)
    filings = filings_from_company(company, as_of, args.months)
    events, by_filing, notes = classify(filings, args.ticker.upper())

    print(f"\n{args.ticker.upper()}: {len(filings)} 8-K filings from {months_back(as_of, args.months)} to {as_of}  ->  {len(events)} events\n")
    print(f"  {'filed':10}  {'accession':20}  {'EDGAR items':18}  event types")
    for f in filings:
        types = [e.event_type for e in by_filing[f.filing_id]]
        print(f"  {f.filing_date}  {f.accession_number:20}  {','.join(f.sec_items) or '(none)':18}  {', '.join(types)}")

    print("\n  Events by type:")
    for t, n in Counter(e.event_type for e in events).most_common():
        print(f"      {t:30} {n}")
    print("  Filings by EDGAR item:")
    for it, n in sorted(Counter(i for f in filings for i in f.sec_items).items()):
        print(f"      Item {it:6} in {n} filing(s)")

    bad = [e for e in events if e.event_type == "MAJOR_ACQUISITION"]
    acq = [e for e in events if e.event_type == "ACQUISITION_OR_DISPOSITION"]
    empty = [f for f in filings if not f.sec_items]
    print("\n  CHECKS")
    print(f"    [{'PASS' if not bad else 'FAIL'}] no event is typed MAJOR_ACQUISITION ({len(bad)} found)")
    print(f"    [{'PASS' if all(e.details.get('item') == '2.01' for e in acq) else 'FAIL'}] ACQUISITION_OR_DISPOSITION only for item 2.01 ({len(acq)} events)")
    print(f"    [{'PASS' if not empty else 'INFO'}] every 8-K has item numbers in the EDGAR index ({len(empty)} without; they fall back to the filing text)")
    real_notes = [n for n in notes if n["rule_code"] != "EVENT_SAME_DAY_UNDETERMINED"]
    print(f"    [{'PASS' if not real_notes else 'INFO'}] classification notes: {len(real_notes)}")
    for n in real_notes[:10]:
        print(f"        {n['rule_code']}: {n['message']}")
    if len(real_notes) != len(notes):
        print("    (same-day pairs are only listed below: this script has no filing text, so it cannot compare them."
              " Use scripts\\investigate_same_day_8k.py for that.)")

    days = defaultdict(list)
    for f in filings:
        days[f.filing_date].append(f)
    pairs = {d: fs for d, fs in days.items() if len(fs) > 1}
    print(f"\n  SAME-DAY 8-Ks ({len(pairs)} days with more than one filing)")
    for d, fs in sorted(pairs.items()):
        same = len({tuple(sorted(f.sec_items)) for f in fs}) == 1
        print(f"      {d}  " + "  |  ".join(f"{f.accession_number} [{','.join(f.sec_items)}]" for f in fs) + f"   -> {'SAME items' if same else 'different items'}")


if __name__ == "__main__":
    main()
