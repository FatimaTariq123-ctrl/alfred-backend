"""
READ-ONLY investigation of same-day 8-K pairs (for example CF's 8 pairs of Item 2.02 filings).

    python scripts\\investigate_same_day_8k.py --ticker CF
    python scripts\\investigate_same_day_8k.py --ticker CF --max-pairs 2

It reads from SEC EDGAR only (edgartools). No database is used, nothing is written anywhere.
For every day on which the company filed more than one 8-K with the same items it shows, side by side:
  accession, EDGAR acceptance time, filer entities (name, CIK, file number), the documents of each filing
  (type, size, content hash), and whether the documents are identical.
Then it runs the pipeline's own duplicate rule on the same data and prints what the pipeline would record.
"""
import sys
import hashlib
import argparse
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schema.models import Issuer, Filing, TextChunk  # noqa: E402
from pipeline.events import MaterialEventEmitter, normalize_text  # noqa: E402
from pipeline.indexer import parse_sec_items, _coerce_datetime  # noqa: E402

import re  # noqa: E402

_ITEM_NUM = re.compile(r"(\d{1,2}\.\d{2})")


class NullDB:
    def save_material_events(self, events):
        return None


def content_hash(text):
    t = normalize_text(text or "")
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16] if t else None


def compare_documents(a, b):
    """
    a, b: {'primary': hash or None, 'exhibits': [(type, hash), ...], 'filers': [(name, cik, file_number), ...]}
    Pure function (unit-tested). Returns the verdict and the reasons in words.
    """
    same_primary = a["primary"] is not None and a["primary"] == b["primary"]
    same_exhibits = sorted(a["exhibits"]) == sorted(b["exhibits"])
    same_filers = sorted(a["filers"]) == sorted(b["filers"])
    if same_primary and same_exhibits:
        verdict = "IDENTICAL_CONTENT"
    elif same_exhibits and a["exhibits"]:
        verdict = "SAME_EXHIBITS_DIFFERENT_MAIN_DOCUMENT"
    elif same_primary:
        verdict = "SAME_MAIN_DOCUMENT_DIFFERENT_EXHIBITS"
    else:
        verdict = "DIFFERENT_CONTENT"
    return {"verdict": verdict, "same_main_document": same_primary, "same_exhibits": same_exhibits, "same_filers": same_filers}


def describe_edgar_filing(ef):
    """Reads one edgartools Filing. Every access is guarded: a missing field is reported as such, not guessed."""
    out = {"accession": str(ef.accession_number), "accepted": None, "filers": [], "documents": [], "primary": None, "exhibits": [], "errors": []}
    try:
        hdr = ef.header
        out["accepted"] = getattr(hdr, "acceptance_datetime", None)
        for fl in getattr(hdr, "filers", None) or []:
            ci, fi = getattr(fl, "company_information", None), getattr(fl, "filing_information", None)
            out["filers"].append((str(getattr(ci, "name", "?")), str(getattr(ci, "cik", "?")), str(getattr(fi, "file_number", "?"))))
    except Exception as e:
        out["errors"].append(f"header: {type(e).__name__}: {e}")
    try:
        for att in ef.attachments:
            ext = str(getattr(att, "extension", "") or "").lower().lstrip(".")
            doc = str(getattr(att, "document", ""))
            dtype = str(getattr(att, "document_type", ""))
            h = None
            if ext in ("htm", "html", "txt"):
                try:
                    h = content_hash(att.text())
                except Exception as e:
                    out["errors"].append(f"{doc}: {type(e).__name__}")
            out["documents"].append({"type": dtype, "document": doc, "size": getattr(att, "size", None), "hash": h})
        prim = next((d for d in out["documents"] if d["type"].upper() in ("8-K", "8-K/A")), None)
        out["primary"] = prim["hash"] if prim else None
        out["exhibits"] = [(d["type"], d["hash"]) for d in out["documents"] if d["type"].upper().startswith("EX-") and d["hash"]]
    except Exception as e:
        out["errors"].append(f"attachments: {type(e).__name__}: {e}")
    return out


def chunks_like_the_parser(ef, filing_id):
    """The item text the pipeline parser would store, built the same way (filing.obj().items)."""
    chunks = []
    obj = ef.obj()
    for key in list(getattr(obj, "items", None) or []):
        m = _ITEM_NUM.search(str(key))
        text = str(obj[key]) if obj[key] is not None else ""
        if text.strip():
            chunks.append(TextChunk(chunk_id=f"{filing_id}_{key}", filing_id=filing_id, section=f"Item {m.group(1)}" if m else str(key), text=text))
    return chunks


def main():
    ap = argparse.ArgumentParser(description="Investigate same-day 8-K pairs (read-only, SEC only)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--as_of", default=date.today().isoformat())
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--max-pairs", type=int, default=8)
    args = ap.parse_args()
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    from config.settings import init_edgar_identity
    init_edgar_identity()
    from edgar import Company, get_by_accession_number
    from common.rate_limiter import SEC_LIMITER

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from verify_8k_items import months_back
    cutoff = months_back(as_of, args.months)

    records = [r for r in Company(args.ticker).get_filings(form="8-K")
               if cutoff <= (r.filing_date if isinstance(r.filing_date, date) else datetime.strptime(str(r.filing_date)[:10], "%Y-%m-%d").date()) <= as_of]
    groups = defaultdict(list)
    for r in records:
        d = r.filing_date if isinstance(r.filing_date, date) else datetime.strptime(str(r.filing_date)[:10], "%Y-%m-%d").date()
        key = (d, tuple(sorted(i for i in parse_sec_items(getattr(r, "items", None)) if i != "9.01")))
        groups[key].append(r)
    pairs = sorted(((k, v) for k, v in groups.items() if len(v) > 1), key=lambda kv: kv[0][0])
    print(f"\n{args.ticker.upper()}: {len(records)} 8-Ks in the window, {len(pairs)} same-day groups with the same items\n")

    issuer = Issuer(issuer_id=f"issuer_US_{args.ticker.upper()}", market="US", legal_name=args.ticker.upper(), ticker=args.ticker.upper())
    totals = defaultdict(int)
    for (day, items), recs in pairs[: args.max_pairs]:
        print(f"=== {day}  items {list(items)}  ({len(recs)} filings) ===")
        descs, filings, chunks = [], [], []
        for r in sorted(recs, key=lambda x: str(x.accession_number)):
            SEC_LIMITER.acquire(tag=f"investigate:{r.accession_number}")
            ef = get_by_accession_number(str(r.accession_number))
            d = describe_edgar_filing(ef)
            descs.append(d)
            acc = str(r.accession_number)
            f = Filing(filing_id=f"filing_{acc.replace('-', '_')}", issuer_id=issuer.issuer_id, accession_number=acc, form_type="8-K",
                       filing_date=day, report_period=day, source_uri="", source_hash="",
                       sec_items=parse_sec_items(getattr(r, "items", None)), accepted_at=_coerce_datetime(getattr(r, "acceptance_datetime", None)))
            filings.append(f)
            try:
                chunks.extend(chunks_like_the_parser(ef, f.filing_id))
            except Exception as e:
                d["errors"].append(f"item text: {type(e).__name__}: {e}")
            print(f"  {acc}  accepted {d['accepted']}")
            for name, cik, fnum in d["filers"]:
                print(f"      filer: {name} | CIK {cik} | file number {fnum}")
            for doc in d["documents"]:
                if doc["hash"]:
                    print(f"      doc: {doc['type']:10} {doc['document'][:34]:34} {str(doc['size']):>8} bytes  hash {doc['hash']}")
            for err in d["errors"]:
                print(f"      (could not read: {err})")
        cmp = compare_documents(descs[0], descs[1]) if len(descs) >= 2 else {"verdict": "n/a"}
        print(f"  documents: {cmp['verdict']}  (same filers: {cmp.get('same_filers')}, same exhibits: {cmp.get('same_exhibits')})")
        em = MaterialEventEmitter(db_manager=NullDB())
        events = em.emit_events(issuer, filings, chunks)
        rel = {e.details["accession"]: e.details.get("relationship", "-") for e in events}
        counted = [e.details["accession"] for e in MaterialEventEmitter.economic_events(events)]
        print(f"  pipeline rule: {rel}")
        print(f"  counted as an economic event: {counted}\n")
        totals[cmp["verdict"]] += 1
        totals["pipeline:" + ("counted once" if len(set(counted)) < len(recs) else "counted separately")] += 1

    print("SUMMARY")
    for k, v in sorted(totals.items()):
        print(f"   {k:55} {v}")


if __name__ == "__main__":
    main()
