"""
Shows exactly what is saved in the handover table (fie_company_state) for one issuer. READ-ONLY.

    python scripts\\show_handover.py --ticker EXP
    python scripts\\show_handover.py --ticker EXP --run_id run_EXP_3d48d291
    python scripts\\show_handover.py --ticker EXP --save-json handover_EXP_from_db.json

It uses DATABASE_URL from the environment (or .env) and connects with plain psycopg, so it does NOT run
the pipeline's migrations and cannot change anything (the session is read-only).
"""
import os
import sys
import json
import argparse
from collections import Counter
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_KEYS = [
    "issuer", "analysis_date", "history_window", "history_expanded", "history_expansion_reasons",
    "financial_state", "material_changes", "accounting_quality", "material_events", "data_quality",
    "confidence", "handover_status", "handover_blockers",
]


def _url():
    url = os.environ.get("DATABASE_URL")
    if not url:                                   # fall back to the project's .env without importing the pipeline
        env = PROJECT_ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        sys.exit("DATABASE_URL is not set in this window.")
    return url


def short(v, n=70):
    s = json.dumps(v, default=str) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 3] + "..."


def main():
    ap = argparse.ArgumentParser(description="Show what is saved in fie_company_state (read-only)")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--run_id", default=None)
    ap.add_argument("--save-json", default=None, help="also write the full saved payload to this file")
    args = ap.parse_args()
    issuer_id = f"issuer_US_{args.ticker.upper()}"

    conn = psycopg.connect(_url(), row_factory=dict_row, connect_timeout=15)
    conn.read_only = True
    print(f"Connected to host: {conn.info.host} | database: {conn.info.dbname} (read-only)")

    rows = conn.execute("SELECT run_id, created_at FROM fie_company_state WHERE issuer_id = %s ORDER BY created_at DESC",
                        (issuer_id,)).fetchall()
    print(f"\nRows in fie_company_state for {issuer_id}: {len(rows)}")
    for r in rows:
        print(f"    {r['run_id']}   saved at {r['created_at']}")
    if not rows:
        sys.exit("Nothing saved for this issuer.")
    run_id = args.run_id or rows[0]["run_id"]

    row = conn.execute("SELECT *, pg_column_size(payload) AS payload_bytes FROM fie_company_state WHERE run_id = %s", (run_id,)).fetchone()
    if not row:
        sys.exit(f"No handover row for run_id {run_id}")
    payload = row["payload"]

    print(f"\n=== HANDOVER ROW  run_id = {run_id} ===")
    for col in ["run_id", "issuer_id", "as_of_date", "handover_status", "confidence", "history_window_years",
                "policy_version", "schema_version", "created_at", "payload_bytes"]:
        print(f"    {col:22} {row[col]}")

    print("\n=== PAYLOAD (JSONB) TOP-LEVEL KEYS ===")
    for k in SPEC_KEYS:
        if k not in payload:
            print(f"    {k:28} MISSING")
            continue
        v = payload[k]
        size = f"{len(v)} items" if isinstance(v, (list, dict)) else short(v, 40)
        print(f"    {k:28} {type(v).__name__:6} {size}")
    extra = [k for k in payload if k not in SPEC_KEYS]
    if extra:
        print(f"    (extra keys not in the spec list: {extra})")

    fs = payload.get("financial_state") or {}
    ms = fs.get("metrics_summary") or {}
    print(f"\n=== financial_state: {len(ms)} metric rows | other keys: "
          f"{ {k: fs[k] for k in fs if k != 'metrics_summary'} } ===")
    print(f"    {'metric_period':34} {'value':>18} {'derived':8} {'status':12} sources")
    for key in sorted(ms):
        m = ms[key]
        val = m.get("value")
        vtxt = f"{val:,.0f}" if isinstance(val, (int, float)) else str(val)
        print(f"    {key:34} {vtxt:>18} {str(m.get('is_derived')):8} {str(m.get('comparability_status')):12} {len(m.get('provenance_fact_ids') or [])}")

    mc = payload.get("material_changes") or []
    print(f"\n=== material_changes: {len(mc)} item(s) ===")
    for c in mc:
        ev = c.get("supporting_evidence") or []
        print(f"    change={c.get('change')!r} direction={c.get('direction')!r} supporting_evidence={len(ev)} entries "
              f"(first: {short(ev[0], 40) if ev else '-'})")

    print("\n=== accounting_quality ===")
    for k, v in (payload.get("accounting_quality") or {}).items():
        print(f"    {k:28} {short(v)}")

    evs = payload.get("material_events") or []
    cnt = Counter((e.get("event_type"), e.get("severity")) for e in evs)
    dates = sorted(str(e.get("event_date")) for e in evs if e.get("event_date"))
    print(f"\n=== material_events: {len(evs)} total | dates {dates[0] if dates else '-'} .. {dates[-1] if dates else '-'} ===")
    for (t, s), n in cnt.most_common():
        print(f"    {str(t):26} {str(s):8} {n}")

    print("\n=== data_quality / status ===")
    for k, v in (payload.get("data_quality") or {}).items():
        print(f"    data_quality.{k:22} {short(v)}")
    for k in ["confidence", "handover_status", "handover_blockers", "history_window", "history_expanded", "history_expansion_reasons"]:
        print(f"    {k:28} {short(payload.get(k))}")

    n_db = conn.execute("SELECT COUNT(*) AS n FROM normalized_metric WHERE issuer_id = %s", (issuer_id,)).fetchone()["n"]
    print(f"\nCross-check: metrics in payload = {len(ms)} | rows in normalized_metric table for this issuer = {n_db}")

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"\nFull payload written to {args.save_json}")
    conn.rollback()


if __name__ == "__main__":
    main()
