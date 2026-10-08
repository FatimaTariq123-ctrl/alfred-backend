import sys
import argparse
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from handover.contract import FIECompanyState
from storage.db import DatabaseManager

SPEC_20_8_KEYS = [
    "issuer", "analysis_date", "history_window", "history_expanded",
    "history_expansion_reasons", "financial_state", "material_changes",
    "accounting_quality", "material_events", "data_quality",
    "confidence", "handover_status", "handover_blockers"
]

def main():
    parser = argparse.ArgumentParser(description="FIE Reader Check Script")
    parser.add_argument("--ticker", type=str, default="MSFT", help="Equity ticker symbol (default: MSFT)")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    issuer_id = f"issuer_US_{ticker}"

    print(f"=== Running FIE Read Check for {ticker} ({issuer_id}) ===")

    db = DatabaseManager()
    conn = db.get_connection()

    with conn.cursor() as cur:
        # Check raw JSONB database properties
        cur.execute("""
            SELECT 
                run_id, issuer_id, handover_status, confidence, history_window_years,
                jsonb_typeof(payload) as payload_type,
                payload->>'handover_status' as payload_status,
                payload
            FROM fie_company_state_latest
            WHERE issuer_id = %s;
        """, (issuer_id,))
        row = cur.fetchone()

    if not row:
        print(f"ERROR: No handover state found in fie_company_state_latest for issuer {issuer_id}")
        sys.exit(1)

    run_id = row["run_id"]
    db_status = row["handover_status"]
    confidence = row["confidence"]
    history_window = row["history_window_years"]
    payload_type = row["payload_type"]
    payload_status = row["payload_status"]
    payload = row["payload"]

    print(f"Latest Run ID: {run_id}")
    print(f"DB Status Column: {db_status}")
    print(f"Payload JSONB Type: {payload_type}")
    print(f"Payload Handover Status: {payload_status}")

    # Check 1: jsonb_typeof(payload) = 'object'
    if payload_type != "object":
        print(f"ERROR: JSONB payload type is '{payload_type}', expected 'object'")
        sys.exit(1)

    # Check 2: payload status matches DB column status
    if payload_status != db_status:
        print(f"ERROR: Status mismatch between column ({db_status}) and payload ({payload_status})")
        sys.exit(1)

    # Check 3: Pydantic schema validation
    try:
        validated_state = FIECompanyState.model_validate(payload)
        print("Pydantic Schema Validation: OK")
    except Exception as e:
        print(f"ERROR: Schema validation failed: {e}")
        sys.exit(1)

    # Check 4: §20.8 top-level keys presence
    missing_keys = [k for k in SPEC_20_8_KEYS if k not in payload]
    if missing_keys:
        print(f"ERROR: Missing §20.8 top-level keys in payload: {missing_keys}")
        sys.exit(1)
    else:
        print("§20.8 Top-Level Keys Check: OK (All 13 required keys present)")

    # Print summary metrics
    financial_state = payload.get("financial_state", {})
    metrics_summary = financial_state.get("metrics_summary", {})
    material_changes = payload.get("material_changes", [])
    material_events = payload.get("material_events", [])

    print("\n--- Handover Summary ---")
    print(f"  Issuer: {validated_state.issuer}")
    print(f"  Status: {validated_state.handover_status}")
    print(f"  Confidence: {validated_state.confidence}")
    print(f"  History Window: {validated_state.history_window} years")
    print(f"  Material Changes Count: {len(material_changes)}")
    print(f"  Material Events Count: {len(material_events)}")
    print(f"  Metric Entries Count: {len(metrics_summary)}")

    print("\nFIE READ CHECK PASSED SUCCESSFULLY (OK)")
    sys.exit(0)

if __name__ == "__main__":
    main()
