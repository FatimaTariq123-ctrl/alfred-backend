"""
Read-only database check for the latest pipeline run of one issuer.

Usage (from the project folder, venv active):
    python scripts\\db_check_run.py --ticker EXP
    python scripts\\db_check_run.py --ticker EXP --run_id run_EXP_c80b16dd

Part A = hard integrity checks (PASS / FAIL).
Part B = content checks (INFO): they show what the data looks like, they do not judge it.
It changes nothing in the database. It uses DatabaseManager, so it refuses a non-local database
unless your .env explicitly allows it (same guard as the pipeline).
"""
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager  # noqa: E402

SPEC_20_8_KEYS = [
    "issuer", "analysis_date", "history_window", "history_expanded", "history_expansion_reasons",
    "financial_state", "material_changes", "accounting_quality", "material_events", "data_quality",
    "confidence", "handover_status", "handover_blockers",
]


def main():
    ap = argparse.ArgumentParser(description="Read-only DB check for the latest run of an issuer")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--run_id", default=None)
    args = ap.parse_args()
    issuer_id = f"issuer_US_{args.ticker.upper()}"

    db = DatabaseManager()          # prints "[DatabaseManager] Target DB: host=..." -> must say localhost
    conn = db.get_connection()
    try:
        conn.rollback()
        conn.read_only = True       # the session cannot write
    except Exception:
        pass
    cur = conn.cursor()

    def rows(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchall()

    def scalar(sql, params=()):
        cur.execute(sql, params)
        r = cur.fetchone()
        return list(r.values())[0] if r else None

    tally = {"PASS": 0, "FAIL": 0}

    def check(name, ok, detail=""):
        tally["PASS" if ok else "FAIL"] += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))

    # ---------------------------------------------------------------- run
    if args.run_id:
        run = rows("SELECT * FROM ingestion_run WHERE run_id = %s", (args.run_id,))
    else:
        run = rows("SELECT * FROM ingestion_run WHERE issuer_id = %s ORDER BY started_at DESC LIMIT 1", (issuer_id,))
    if not run:
        print(f"No ingestion_run found for {issuer_id}. Nothing to check.")
        sys.exit(1)
    run = run[0]
    run_id = run["run_id"]
    print(f"\n=== RUN {run_id} | issuer {issuer_id} | status {run['status']} | as_of {run['as_of_date']} ===")
    print(f"    versions: policy={run['policy_version']} edgartools={run['edgartools_version']} "
          f"parser={run['parser_version']} normalizer={run['normalizer_version']} | source_snapshot={'set' if run['source_snapshot'] else 'EMPTY'}")

    # ---------------------------------------------------------------- counts
    print("\n--- ROW COUNTS (this issuer) ---")
    q = {
        "filing rows (all forms indexed)": "SELECT COUNT(*) FROM filing WHERE issuer_id = %s",
        "filing_asset rows": "SELECT COUNT(*) FROM filing_asset a JOIN filing f USING (filing_id) WHERE f.issuer_id = %s",
        "fact_observation rows": "SELECT COUNT(*) FROM fact_observation x JOIN filing f USING (filing_id) WHERE f.issuer_id = %s",
        "  filings that have facts": "SELECT COUNT(DISTINCT x.filing_id) FROM fact_observation x JOIN filing f USING (filing_id) WHERE f.issuer_id = %s",
        "text_chunk rows": "SELECT COUNT(*) FROM text_chunk t JOIN filing f USING (filing_id) WHERE f.issuer_id = %s",
        "  filings that have chunks": "SELECT COUNT(DISTINCT t.filing_id) FROM text_chunk t JOIN filing f USING (filing_id) WHERE f.issuer_id = %s",
        "normalized_metric rows": "SELECT COUNT(*) FROM normalized_metric WHERE issuer_id = %s",
        "material_event rows": "SELECT COUNT(*) FROM material_event WHERE issuer_id = %s",
        "fact_version rows": "SELECT COUNT(*) FROM fact_version v JOIN fact_observation x ON x.fact_id = v.preferred_fact_id JOIN filing f ON f.filing_id = x.filing_id WHERE f.issuer_id = %s",
        "history_decision rows": "SELECT COUNT(*) FROM history_decision WHERE issuer_id = %s",
        "fie_company_state rows": "SELECT COUNT(*) FROM fie_company_state WHERE issuer_id = %s",
    }
    counts = {}
    for label, sql in q.items():
        counts[label] = scalar(sql, (issuer_id,))
        print(f"    {label:38} {counts[label]}")
    print("    quality_issue rows of this run by rule / severity:")
    for r in rows("SELECT rule_code, severity, COUNT(*) AS n FROM quality_issue WHERE run_id = %s GROUP BY 1,2 ORDER BY 3 DESC", (run_id,)):
        print(f"        {r['rule_code']:28} {r['severity']:8} {r['n']}")
    print("    material_event by type / severity:")
    for r in rows("SELECT event_type, severity, COUNT(*) AS n FROM material_event WHERE issuer_id = %s GROUP BY 1,2 ORDER BY 3 DESC", (issuer_id,)):
        print(f"        {r['event_type']:28} {r['severity']:8} {r['n']}")

    # ---------------------------------------------------------------- A: hard checks
    print("\n=== PART A: HARD INTEGRITY CHECKS ===")
    check("run status is COMPLETED", run["status"] == "COMPLETED", f"status={run['status']}")
    check("edgartools_version is a real version (not the old hardcoded 3.0.0)",
          run["edgartools_version"] not in (None, "", "3.0.0"), f"value={run['edgartools_version']}")

    n = scalar("SELECT COUNT(*) FROM fact_observation x JOIN filing f USING (filing_id) WHERE f.issuer_id = %s AND x.value IS NULL", (issuer_id,))
    check("no fact has an empty value (numeric facts only)", n == 0, f"{n} rows")
    n = scalar("SELECT COUNT(*) FROM fact_observation x JOIN filing f USING (filing_id) WHERE f.issuer_id = %s AND x.parser_version IS NULL", (issuer_id,))
    check("every fact has parser_version", n == 0, f"{n} rows without")
    n = scalar("SELECT COUNT(*) FROM fact_observation x JOIN filing f USING (filing_id) WHERE f.issuer_id = %s AND x.context_ref IS NULL", (issuer_id,))
    check("every fact has context_ref", n == 0, f"{n} rows without")
    n = scalar("SELECT COUNT(*) FROM text_chunk t JOIN filing f USING (filing_id) WHERE f.issuer_id = %s AND t.parser_version IS NULL", (issuer_id,))
    check("every text chunk has parser_version", n == 0, f"{n} rows without")
    n = scalar("SELECT COUNT(*) FROM text_chunk t JOIN filing f USING (filing_id) WHERE f.issuer_id = %s AND t.section LIKE 'Item Part%%'", (issuer_id,))
    check("no garbled 10-Q section names ('Item Part...')", n == 0, f"{n} chunks")

    bad = rows("""SELECT f.form_type, f.accession_number FROM filing f JOIN filing_asset a ON a.filing_id = f.filing_id
                  LEFT JOIN text_chunk t ON t.filing_id = f.filing_id
                  WHERE f.issuer_id = %s GROUP BY f.filing_id, f.form_type, f.accession_number HAVING COUNT(t.chunk_id) = 0""", (issuer_id,))
    check("every retrieved filing has text chunks", not bad, "; ".join(f"{b['form_type']} {b['accession_number']}" for b in bad[:6]))
    bad = rows("""SELECT f.form_type, f.accession_number FROM filing f JOIN filing_asset a ON a.filing_id = f.filing_id
                  LEFT JOIN fact_observation x ON x.filing_id = f.filing_id
                  WHERE f.issuer_id = %s AND f.form_type IN ('10-K','10-Q','10-K/A','10-Q/A')
                  GROUP BY f.filing_id, f.form_type, f.accession_number HAVING COUNT(x.fact_id) = 0""", (issuer_id,))
    check("every retrieved 10-K / 10-Q has facts", not bad, "; ".join(f"{b['form_type']} {b['accession_number']}" for b in bad[:6]))

    n = scalar("""SELECT COUNT(*) FROM normalized_metric m CROSS JOIN LATERAL unnest(m.provenance_fact_ids) AS pid
                  LEFT JOIN fact_observation x ON x.fact_id = pid WHERE m.issuer_id = %s AND x.fact_id IS NULL""", (issuer_id,))
    check("every metric provenance fact id exists in fact_observation", n == 0, f"{n} dangling ids")
    n = scalar("""SELECT COUNT(*) FROM normalized_metric m CROSS JOIN LATERAL unnest(m.provenance_filing_ids) AS fid
                  LEFT JOIN filing f ON f.filing_id = fid WHERE m.issuer_id = %s AND f.filing_id IS NULL""", (issuer_id,))
    check("every metric provenance filing id exists in filing", n == 0, f"{n} dangling ids")
    bad = rows("""SELECT m.metric_code, m.period, m.value AS metric_value, x.value AS first_fact_value
                  FROM normalized_metric m JOIN fact_observation x ON x.fact_id = m.provenance_fact_ids[1]
                  WHERE m.issuer_id = %s AND NOT m.is_derived AND ABS(m.value) <> ABS(x.value)""", (issuer_id,))
    check("first provenance fact carries the metric value (the chosen fact is first)", not bad,
          "; ".join(f"{b['metric_code']} {b['period']}: metric {b['metric_value']} vs fact {b['first_fact_value']}" for b in bad[:4]))

    st = rows("SELECT handover_status, confidence, history_window_years, jsonb_typeof(payload) AS t, payload FROM fie_company_state WHERE run_id = %s", (run_id,))
    check("handover row exists for this run", len(st) == 1)
    if st:
        st = st[0]
        payload = st["payload"]
        check("handover payload is a JSON object", st["t"] == "object", f"type={st['t']}")
        check("handover has all spec section 20.8 keys", all(k in payload for k in SPEC_20_8_KEYS),
              "missing: " + ", ".join(k for k in SPEC_20_8_KEYS if k not in payload))
        check("status column equals status inside payload", payload.get("handover_status") == st["handover_status"],
              f"column={st['handover_status']} payload={payload.get('handover_status')}")
        ms = (payload.get("financial_state") or {}).get("metrics_summary") or {}
        db_m = {f"{r['metric_code']}_{r['period']}": r for r in rows(
            "SELECT metric_code, period, value, is_derived FROM normalized_metric WHERE issuer_id = %s", (issuer_id,))}
        only_payload = sorted(set(ms) - set(db_m))
        only_db = sorted(set(db_m) - set(ms))
        check("handover metrics and normalized_metric table have the same keys", not only_payload and not only_db,
              f"only in payload: {only_payload[:3]} ({len(only_payload)}); only in DB: {only_db[:3]} ({len(only_db)})")
        diff = [k for k in set(ms) & set(db_m)
                if ms[k].get("value") is not None and db_m[k]["value"] is not None and abs(float(ms[k]["value"]) - float(db_m[k]["value"])) > 0.5]
        check("handover metric values equal the DB values", not diff, f"{len(diff)} differ: {diff[:3]}")
        ev = payload.get("material_events") or []
        n_ev = counts["material_event rows"]
        check("handover material_events count equals material_event rows", len(ev) == n_ev, f"payload={len(ev)} db={n_ev}")

    # ---------------------------------------------------------------- B: content
    print("\n=== PART B: CONTENT CHECKS (INFO, read them yourself) ===")
    print("\n  Filings that produced facts, by form:")
    for r in rows("""SELECT f.form_type, COUNT(DISTINCT f.filing_id) AS filings FROM fact_observation x JOIN filing f USING (filing_id)
                     WHERE f.issuer_id = %s GROUP BY 1 ORDER BY 1""", (issuer_id,)):
        print(f"      {r['form_type']:8} {r['filings']} filings")

    print("\n  Metric coverage (FY labels / quarter labels / derived rows):")
    for r in rows("""SELECT metric_code,
                            COUNT(*) FILTER (WHERE period LIKE 'FY%%') AS fy,
                            COUNT(*) FILTER (WHERE period LIKE 'Q%%' AND NOT is_derived) AS q,
                            COUNT(*) FILTER (WHERE is_derived) AS derived
                     FROM normalized_metric WHERE issuer_id = %s GROUP BY 1 ORDER BY 1""", (issuer_id,)):
        print(f"      {r['metric_code']:22} FY={r['fy']}  Q={r['q']}  derived={r['derived']}")

    print("\n  OperatingIncomeLoss facts per filing (company-wide vs dimensioned) - explains a missing OPERATING_INCOME:")
    for r in rows("""SELECT f.form_type, f.report_period,
                            COUNT(*) FILTER (WHERE x.dimensions IS NULL) AS company_wide,
                            COUNT(*) FILTER (WHERE x.dimensions IS NOT NULL) AS dimensioned
                     FROM fact_observation x JOIN filing f USING (filing_id)
                     WHERE f.issuer_id = %s AND x.concept = 'us-gaap:OperatingIncomeLoss'
                     GROUP BY 1,2 ORDER BY 2 DESC LIMIT 14""", (issuer_id,)):
        print(f"      {r['form_type']:6} {r['report_period']}  company-wide={r['company_wide']}  dimensioned={r['dimensioned']}")

    n_cfo = scalar("""SELECT COUNT(DISTINCT x.filing_id) FROM fact_observation x JOIN filing f USING (filing_id)
                      WHERE f.issuer_id = %s AND x.dimensions IS NULL AND x.concept = 'us-gaap:NetCashProvidedByUsedInOperatingActivities'""", (issuer_id,))
    n_cfo_metric = scalar("SELECT COUNT(*) FROM normalized_metric WHERE issuer_id = %s AND metric_code = 'OPERATING_CASH_FLOW'", (issuer_id,))
    print(f"\n  Operating cash flow: company-wide facts exist in {n_cfo} filings, but OPERATING_CASH_FLOW metric rows = {n_cfo_metric}")

    r = rows("""SELECT COUNT(*) FILTER (WHERE x.value < 0) AS negative, COUNT(*) AS total FROM fact_observation x JOIN filing f USING (filing_id)
                WHERE f.issuer_id = %s AND x.dimensions IS NULL AND x.concept LIKE '%%:PaymentsToAcquirePropertyPlantAndEquipment'""", (issuer_id,))[0]
    print(f"  Capex facts stored with a NEGATIVE value: {r['negative']} of {r['total']} "
          f"(filings report this concept as a positive payment, so a negative value means the source value was changed)")

    print("\n  Sections per 10-Q (a low number can mean the section split failed):")
    for r in rows("""SELECT f.accession_number, f.report_period, COUNT(DISTINCT t.section) AS sections, COUNT(*) AS chunks
                     FROM text_chunk t JOIN filing f USING (filing_id)
                     WHERE f.issuer_id = %s AND f.form_type = '10-Q' GROUP BY 1,2 ORDER BY 2 DESC""", (issuer_id,)):
        print(f"      {r['accession_number']}  {r['report_period']}  sections={r['sections']}  chunks={r['chunks']}")
    odd = rows("""SELECT DISTINCT t.section FROM text_chunk t JOIN filing f USING (filing_id)
                  WHERE f.issuer_id = %s AND f.form_type = '10-Q' AND t.section NOT LIKE 'Part I%%' AND t.section NOT LIKE 'Part II%%'""", (issuer_id,))
    unexpected = rows("""SELECT DISTINCT t.section FROM text_chunk t JOIN filing f USING (filing_id)
                         WHERE f.issuer_id = %s AND f.form_type = '10-Q' AND t.section LIKE 'Part I, Item 7%%'""", (issuer_id,))
    if odd or unexpected:
        print(f"      10-Q sections outside the normal pattern: {[o['section'] for o in odd + unexpected][:6]}")

    print("\n  HIGH severity events (look at each by hand):")
    for r in rows("""SELECT event_type, details->>'concept' AS concept, details->>'original_value' AS original_value,
                            details->>'preferred_value' AS preferred_value, details->>'original_accession' AS original_acc,
                            details->>'preferred_accession' AS preferred_acc
                     FROM material_event WHERE issuer_id = %s AND severity = 'HIGH'""", (issuer_id,)):
        print(f"      {r['event_type']} {r['concept']}: {r['original_value']} ({r['original_acc']}) -> {r['preferred_value']} ({r['preferred_acc']})")

    print("\n  Handover flags (check them against the numbers above):")
    if st:
        dq = payload.get("data_quality") or {}
        print(f"      completeness={dq.get('completeness')}  reconciliation={dq.get('reconciliation_status')}  "
              f"missing_periods={dq.get('missing_periods')}  warnings={dq.get('warnings')}")
        print(f"      handover_status={payload.get('handover_status')}  confidence={payload.get('confidence')}  blockers={payload.get('handover_blockers')}")

    conn.rollback()
    print(f"\n=== PART A RESULT: {tally['PASS']} PASS, {tally['FAIL']} FAIL ===")


if __name__ == "__main__":
    main()
