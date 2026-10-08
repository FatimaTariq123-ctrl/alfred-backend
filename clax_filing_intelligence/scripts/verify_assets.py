import os
import sys
import hashlib
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db import DatabaseManager

def main():
    print("=== Running Asset Integrity Verification (scripts/verify_assets.py) ===")
    db = DatabaseManager()
    conn = db.get_connection()

    with conn.cursor() as cur:
        cur.execute("SELECT asset_id, filing_id, asset_type, storage_uri, hash FROM filing_asset;")
        assets = cur.fetchall()

    if not assets:
        print("No filing assets found in database.")
        sys.exit(0)

    matched = 0
    mismatched = 0
    missing = 0

    for a in assets:
        asset_id = a["asset_id"]
        uri = a["storage_uri"]
        expected_hash = a["hash"]
        
        # Strip file:// prefix if present
        clean_path = uri[7:] if uri.startswith("file://") else uri
        p = Path(clean_path)

        if not p.exists():
            missing += 1
            print(f"ERROR: Asset file missing at storage_uri: {uri}")
            continue

        file_bytes = p.read_bytes()
        actual_hash = hashlib.sha256(file_bytes).hexdigest()

        if actual_hash != expected_hash:
            mismatched += 1
            print(f"ERROR: Hash mismatch for asset {asset_id} at {uri}: expected {expected_hash}, got {actual_hash}")
        else:
            matched += 1

    print(f"\n--- Asset Check Results ---")
    print(f"  Total Assets Verified: {len(assets)}")
    print(f"  Hash Matched: {matched}")
    print(f"  Mismatched: {mismatched}")
    print(f"  Missing Files: {missing}")

    if mismatched > 0 or missing > 0:
        print("ASSET VERIFICATION FAILED")
        sys.exit(1)
    else:
        print("ASSET VERIFICATION PASSED (OK)")
        sys.exit(0)

if __name__ == "__main__":
    main()
