"""
READ-ONLY check of the three claims in "US SEC CF + EXP - Additional Ingestion Fixes":
  1. Handover gate fields (reconciliation_status, storage_verified, authoritative_for_fie,
     financial_filings) contradict the payload, for BOTH CF and EXP.
  2. CF's NET_INCOME metric is missing entirely.
  3. EXP's HIGH-severity NetIncomeLoss restatement is caused by a wrong period on the 2024-07-30
     10-Q fact (should be Apr-Jun 2024, claimed to show Apr-Jun 2022).

    python scripts\\diagnose_team_concerns.py --ticker CF
    python scripts\\diagnose_team_concerns.py --ticker EXP

Nothing is written. Uses DatabaseManager (same local/remote guard as the rest of the pipeline).
"""
import sys
import json
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Check the 3 claims in the team head's PDF (read-only)")
    ap.add_argument("--ticker", required=True)
    args = ap.parse_args()
    issuer_id = f"issuer_US_{args.ticker.upper()}"

    db = DatabaseManager()
    conn = db.get_connection()
    conn.rollback()
    cur = conn.cursor()

    # ------------------------------------------------------------------ Claim 1: handover gate fields
    print("\n=== CLAIM 1: handover gate fields vs payload ===")
    row = cur.execute(
        "SELECT run_id, handover_status, reconciliation_status, storage_verified, authoritative_for_fie, "
        "financial_filings, financial_filings_parsed_ok, blocker_count, warning_count, payload "
        "FROM fie_company_state WHERE issuer_id = %s ORDER BY created_at DESC LIMIT 1",
        (issuer_id,)
    ).fetchone()
    if not row:
        print("  no handover row found")
    else:
        payload = row["payload"]
        dq = payload.get("data_quality", {})
        print(f"  run_id                              {row['run_id']}")
        print(f"  COLUMN handover_status               {row['handover_status']}")
        print(f"  COLUMN reconciliation_status         {row['reconciliation_status']}   <- typed column (extra, HK-added)")
        print(f"  COLUMN storage_verified              {row['storage_verified']}   <- typed column (extra, HK-added)")
        print(f"  COLUMN authoritative_for_fie          {row['authoritative_for_fie']}   <- typed column (extra, HK-added)")
        print(f"  COLUMN financial_filings             {row['financial_filings']}   <- typed column (extra, HK-added)")
        print(f"  COLUMN financial_filings_parsed_ok   {row['financial_filings_parsed_ok']}")
        print(f"  COLUMN blocker_count                 {row['blocker_count']}")
        print(f"  COLUMN warning_count                 {row['warning_count']}")
        print(f"  PAYLOAD data_quality.reconciliation_status  {dq.get('reconciliation_status')}")
        print(f"  PAYLOAD data_quality.completeness           {dq.get('completeness')}")
        print(f"  PAYLOAD handover_blockers                   {payload.get('handover_blockers')}")
        print(f"  PAYLOAD provenance_filings_count            {payload.get('financial_state', {}).get('provenance_filings_count')}")
        mismatch = (row["reconciliation_status"] != dq.get("reconciliation_status")) or (row["financial_filings"] == 0 and payload.get('financial_state', {}).get('provenance_filings_count', 0) > 0)
        print(f"  VERDICT: {'CONTRADICTION CONFIRMED' if mismatch else 'no contradiction found'}")

    # ------------------------------------------------------------------ Claim 2 (CF only): NET_INCOME missing
    if args.ticker.upper() == "CF":
        print("\n=== CLAIM 2 (CF): is NET_INCOME present, and why / why not ===")
        have = cur.execute(
            "SELECT period, value FROM normalized_metric WHERE issuer_id = %s AND metric_code = 'NET_INCOME' ORDER BY period",
            (issuer_id,)
        ).fetchall()
        print(f"  normalized_metric rows for NET_INCOME: {len(have)}")
        for r in have:
            print(f"      {r['period']}  {r['value']}")

        print("\n  raw us-gaap:NetIncomeLoss and us-gaap:ProfitLoss facts (last 5 fiscal years), with dimensions:")
        facts = cur.execute(
            "SELECT fo.fact_id, fo.filing_id, f.form_type, f.report_period, fo.concept, fo.value, "
            "fo.period_start, fo.period_end, fo.dimensions "
            "FROM fact_observation fo JOIN filing f USING (filing_id) "
            "WHERE f.issuer_id = %s AND fo.concept IN ('us-gaap:NetIncomeLoss', 'us-gaap:ProfitLoss') "
            "AND f.form_type IN ('10-K','10-K/A') ORDER BY f.report_period DESC, fo.concept",
            (issuer_id,)
        ).fetchall()
        for r in facts:
            dims = r["dimensions"] if r["dimensions"] else {}
            filing_label = f"{r['form_type']} {r['report_period']}"
            print(f"      {r['concept']:20} filing={filing_label:20} value={r['value']:>15}  "
                  f"period={r['period_start']}..{r['period_end']}  dims={json.dumps(dims)}")

    # ------------------------------------------------------------------ Claim 3 (EXP only): false restatement period
    if args.ticker.upper() == "EXP":
        print("\n=== CLAIM 3 (EXP): the 105.0m -> 133.8m NetIncomeLoss event ===")
        accs = ["0000950170-24-007463", "0000950170-24-087945"]
        for acc in accs:
            frow = cur.execute("SELECT filing_id, form_type, filing_date, report_period FROM filing WHERE accession_number = %s", (acc,)).fetchone()
            if not frow:
                print(f"  {acc}: filing not found locally")
                continue
            print(f"\n  filing {acc}: {frow['form_type']}  filing_date={frow['filing_date']}  report_period={frow['report_period']}")
            facts = cur.execute(
                "SELECT fact_id, concept, value, period_start, period_end, instant_date, dimensions, context_ref "
                "FROM fact_observation WHERE filing_id = %s AND concept = 'us-gaap:NetIncomeLoss' ORDER BY period_end",
                (frow["filing_id"],)
            ).fetchall()
            print(f"  {len(facts)} us-gaap:NetIncomeLoss fact(s) in this filing:")
            for r in facts:
                dims = r["dimensions"] if r["dimensions"] else {}
                print(f"      fact={r['fact_id']:16} value={r['value']:>15}  period={r['period_start']}..{r['period_end']}  "
                      f"instant={r['instant_date']}  dims={json.dumps(dims)}  context_ref={r['context_ref']}")

        print("\n  the HIGH event's canonical_fact_key, and every fact under it:")
        ev = cur.execute(
            "SELECT event_id, details FROM material_event WHERE issuer_id = %s AND event_type = 'RESTATEMENT_OR_REVISION' "
            "AND severity = 'HIGH' AND details->>'concept' = 'us-gaap:NetIncomeLoss'", (issuer_id,)
        ).fetchall()
        for e in ev:
            ckey = e["details"].get("canonical_fact_key")
            print(f"  event {e['event_id']}  canonical_fact_key={ckey}")
            rows = cur.execute(
                "SELECT fo.fact_id, fo.filing_id, f.accession_number, f.form_type, f.filing_date, f.report_period, "
                "fo.value, fo.period_start, fo.period_end, fo.instant_date "
                "FROM fact_observation fo JOIN filing f USING (filing_id) WHERE fo.canonical_fact_key = %s ORDER BY f.filing_date",
                (ckey,)
            ).fetchall()
            for r in rows:
                print(f"      fact={r['fact_id']:16} filing={r['accession_number']} ({r['form_type']}, filed {r['filing_date']}, "
                      f"report_period={r['report_period']})  value={r['value']}  period={r['period_start']}..{r['period_end']}  instant={r['instant_date']}")

    conn.rollback()


if __name__ == "__main__":
    main()
