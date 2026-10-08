"""
READ-ONLY inspection of the pipeline tables for one issuer. It changes nothing.

    python scripts\\inspect_run_state.py --ticker CF
    python scripts\\inspect_run_state.py --ticker EXP --no-schema

It answers, from the real database (local or Neon, whatever DATABASE_URL points to):
  1. SCHEMA   which columns the tables have, and which are NOT in this project's migrations (e.g. columns added by another connector)
  2. RUNS     every ingestion_run of the issuer: status, versions, times, and what is attached to it
  3. WAVES    when the fact / chunk / metric / event rows were written, and with which parser version
  4. METRICS  duplicate metric rows (same metric code and period more than once)
  5. HANDOVER how many facts the latest handover points at were written BEFORE that run started
  6. 8-K      filings of the same form on the same day (possible duplicate submissions)

It uses plain psycopg (no pipeline code, no migrations) and a read-only session.
"""
import os
import re
import sys
import argparse
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TABLES = ["issuer", "ingestion_run", "filing", "filing_asset", "fact_observation", "fact_version", "normalized_metric",
          "text_chunk", "material_event", "history_decision", "quality_issue", "fie_company_state"]
NOT_COLS = {"PRIMARY", "UNIQUE", "FOREIGN", "CONSTRAINT", "CHECK", ")", "(", ");"}


def url():
    u = os.environ.get("DATABASE_URL")
    if not u:
        env = PROJECT_ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("DATABASE_URL="):
                    u = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not u:
        sys.exit("DATABASE_URL is not set in this window.")
    return u


def known_columns():
    """Columns this project's own migrations create (parsed from schema/migrations/*.sql)."""
    known = {t: set() for t in TABLES}
    mig = PROJECT_ROOT / "schema" / "migrations"
    for f in sorted(mig.glob("*.sql")):
        sql = re.sub(r"--.*", "", f.read_text(encoding="utf-8", errors="ignore"))
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\)\s*;", sql, re.S | re.I):
            t, body = m.group(1), m.group(2)
            for line in body.split("\n"):
                tok = line.strip().split(" ")[0].strip(",")
                if tok and tok.upper() not in NOT_COLS and t in known:
                    known[t].add(tok.lower())
        for m in re.finditer(r"ALTER TABLE\s+(\w+)\s+ADD COLUMN IF NOT EXISTS\s+(\w+)", sql, re.I):
            if m.group(1) in known:
                known[m.group(1)].add(m.group(2).lower())
    return known


def main():
    ap = argparse.ArgumentParser(description="Read-only inspection of runs, row ages and schema for one issuer")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--no-schema", action="store_true", help="skip the schema section (shorter output)")
    args = ap.parse_args()
    iss = f"issuer_US_{args.ticker.upper()}"

    conn = psycopg.connect(url(), row_factory=dict_row, connect_timeout=15)
    conn.read_only = True
    print(f"Connected to host: {conn.info.host} | database: {conn.info.dbname} (read-only) | issuer: {iss}")

    def q(sql, params=()):
        try:
            rows = conn.execute(sql, params).fetchall()
            conn.rollback()
            return rows
        except Exception as e:
            conn.rollback()
            print(f"    (query not possible here: {type(e).__name__}: {str(e).splitlines()[0]})")
            return None

    # ---------------------------------------------------------------- 1 schema
    if not args.no_schema:
        print("\n=== 1. SCHEMA: columns that are NOT in this project's migrations ===")
        known = known_columns()
        any_extra = False
        for t in TABLES:
            cols = q("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                     "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position", (t,))
            if cols is None:
                continue
            if not cols:
                print(f"    {t:20} TABLE DOES NOT EXIST")
                continue
            extra = [c for c in cols if c["column_name"].lower() not in known[t]]
            missing = sorted(known[t] - {c["column_name"].lower() for c in cols})
            print(f"    {t:20} {len(cols):2} columns" + (f" | {len(extra)} EXTRA" if extra else "") + (f" | MISSING from DB: {missing}" if missing else ""))
            for c in extra:
                any_extra = True
                d = (c["column_default"] or "none")[:40]
                print(f"        EXTRA  {c['column_name']:30} {c['data_type']:22} nullable={c['is_nullable']:3} default={d}")
        if not any_extra:
            print("    no extra columns: the tables match this project's migrations")
        print("\n    Unique indexes (they decide what counts as 'the same row'):")
        idx = q("SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY(%s) "
                "AND indexdef ILIKE '%%UNIQUE%%' ORDER BY tablename", (TABLES,))
        for r in idx or []:
            print(f"        {r['tablename']:20} {re.sub(r'^CREATE UNIQUE INDEX ', '', r['indexdef'])[:120]}")

    # ---------------------------------------------------------------- 2 runs
    print("\n=== 2. RUNS of this issuer ===")
    runs = q("SELECT run_id, status, as_of_date, parser_version, normalizer_version, started_at, completed_at "
             "FROM ingestion_run WHERE issuer_id = %s ORDER BY started_at", (iss,))
    latest = q("SELECT run_id, created_at, handover_status, confidence FROM fie_company_state WHERE issuer_id = %s ORDER BY created_at DESC LIMIT 1", (iss,))
    latest_run = latest[0]["run_id"] if latest else None
    if runs:
        by_status = {}
        for r in runs:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        print(f"    {len(runs)} runs: {by_status}")
        print(f"    {'run_id':26} {'status':10} {'as_of':11} {'parser':7} {'normalizer':10} {'started':17} {'completed':17} issues  hist  handover")
        for r in runs:
            qi = q("SELECT COUNT(*) AS n FROM quality_issue WHERE run_id = %s", (r["run_id"],))
            hd = q("SELECT COUNT(*) AS n FROM history_decision WHERE run_id = %s", (r["run_id"],))
            ho = q("SELECT handover_status FROM fie_company_state WHERE run_id = %s", (r["run_id"],))
            st = r["started_at"].strftime("%Y-%m-%d %H:%M") if r["started_at"] else "-"
            en = r["completed_at"].strftime("%Y-%m-%d %H:%M") if r["completed_at"] else "-"
            print(f"    {r['run_id']:26} {str(r['status']):10} {str(r['as_of_date']):11} {str(r['parser_version']):7} {str(r['normalizer_version']):10} "
                  f"{st:17} {en:17} {(qi or [{'n': '?'}])[0]['n']:>5} {(hd or [{'n': '?'}])[0]['n']:>5}  "
                  f"{(ho[0]['handover_status'] if ho else '-')}{'  <- LATEST HANDOVER' if r['run_id'] == latest_run else ''}")
    print("    (facts, chunks, metrics and events carry no run id in this schema; section 3 shows when they were written)")

    # ---------------------------------------------------------------- 3 waves
    print("\n=== 3. WAVES: when were the rows written (UTC date) and by which parser version ===")
    waves = {
        "fact_observation": ("SELECT x.created_at::date AS d, COALESCE(x.parser_version, '(none)') AS v, COUNT(*) AS n FROM fact_observation x "
                             "JOIN filing f USING (filing_id) WHERE f.issuer_id = %s GROUP BY 1, 2 ORDER BY 1, 2"),
        "text_chunk": ("SELECT t.created_at::date AS d, COALESCE(t.parser_version, '(none)') AS v, COUNT(*) AS n FROM text_chunk t "
                       "JOIN filing f USING (filing_id) WHERE f.issuer_id = %s GROUP BY 1, 2 ORDER BY 1, 2"),
        "normalized_metric": "SELECT created_at::date AS d, '' AS v, COUNT(*) AS n FROM normalized_metric WHERE issuer_id = %s GROUP BY 1 ORDER BY 1",
        "material_event": "SELECT created_at::date AS d, '' AS v, COUNT(*) AS n FROM material_event WHERE issuer_id = %s GROUP BY 1 ORDER BY 1",
        "filing_asset": ("SELECT a.retrieved_at::date AS d, '' AS v, COUNT(*) AS n FROM filing_asset a JOIN filing f USING (filing_id) "
                         "WHERE f.issuer_id = %s GROUP BY 1 ORDER BY 1"),
    }
    for t, sql in waves.items():
        rows = q(sql, (iss,))
        if rows is None:
            continue
        total = sum(r["n"] for r in rows)
        print(f"    {t:18} total {total:>7}: " + "; ".join(f"{r['d']} {r['v']} = {r['n']}".replace("  ", " ") for r in rows[:12]))

    # ---------------------------------------------------------------- 4 duplicate metrics
    print("\n=== 4. METRICS: copies of the same metric and period ===")
    tot = q("SELECT COUNT(*) AS n, COUNT(DISTINCT (metric_code, period, is_derived)) AS d FROM normalized_metric WHERE issuer_id = %s", (iss,))
    if tot:
        print(f"    rows = {tot[0]['n']} | distinct (metric_code, period, is_derived) = {tot[0]['d']}")
        dup = q("SELECT metric_code, period, COUNT(*) AS n, COUNT(DISTINCT value) AS values_seen FROM normalized_metric WHERE issuer_id = %s "
                "GROUP BY 1, 2, is_derived HAVING COUNT(*) > 1 ORDER BY n DESC, 1, 2 LIMIT 12", (iss,))
        if dup:
            print("    metric / period present more than once (first 12):")
            for r in dup:
                print(f"        {r['metric_code']:18} {r['period']:22} x{r['n']}  ({r['values_seen']} different values)")
        else:
            print("    no metric/period appears twice")

    # ---------------------------------------------------------------- 5 handover provenance
    print("\n=== 5. LATEST HANDOVER: were its source facts written before the run started? ===")
    if latest_run:
        ids_sql = ("WITH h AS (SELECT payload FROM fie_company_state WHERE run_id = %s), "
                   "ids AS (SELECT DISTINCT jsonb_array_elements_text(m.value->'provenance_fact_ids') AS fact_id "
                   "FROM h, jsonb_each(h.payload->'financial_state'->'metrics_summary') AS m) ")
        tot = q(ids_sql + "SELECT COUNT(*) AS referenced, COUNT(x.fact_id) AS found FROM ids LEFT JOIN fact_observation x ON x.fact_id = ids.fact_id", (latest_run,))
        run_start = next((r["started_at"] for r in runs or [] if r["run_id"] == latest_run), None)
        if tot:
            print(f"    handover of run {latest_run}: {tot[0]['referenced']} distinct source facts referenced, {tot[0]['found']} found in fact_observation")
        if run_start:
            old = q(ids_sql + "SELECT x.created_at::date AS d, COALESCE(x.parser_version, '(none)') AS v, COUNT(*) AS n, "
                    "COUNT(*) FILTER (WHERE x.created_at < %s) AS before_run FROM ids JOIN fact_observation x ON x.fact_id = ids.fact_id "
                    "GROUP BY 1, 2 ORDER BY 1, 2", (latest_run, run_start))
            if old:
                b = sum(r["before_run"] for r in old)
                n = sum(r["n"] for r in old)
                print(f"    run started {run_start:%Y-%m-%d %H:%M}; {b} of {n} referenced facts were written BEFORE that run started")
                for r in old:
                    print(f"        written {r['d']} parser {r['v']:8} {r['n']:>6} facts ({r['before_run']} before the run)")
    else:
        print("    no handover row for this issuer")

    # ---------------------------------------------------------------- 6 same-day 8-K
    print("\n=== 6. FILINGS of the same form on the same day (8-K pairs) ===")
    pairs = q("SELECT filing_date, form_type, COUNT(*) AS n, string_agg(accession_number, '  |  ' ORDER BY accession_number) AS accessions FROM filing "
              "WHERE issuer_id = %s AND form_type = '8-K' AND filing_date >= (CURRENT_DATE - INTERVAL '5 years') "
              "GROUP BY 1, 2 HAVING COUNT(*) > 1 ORDER BY 1 DESC LIMIT 20", (iss,))
    if pairs is not None:
        print(f"    {len(pairs)} days with more than one 8-K (last 5 years, first 20 shown)")
        for r in pairs:
            print(f"        {r['filing_date']}  x{r['n']}  {r['accessions']}")
    conn.rollback()


if __name__ == "__main__":
    main()
