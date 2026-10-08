import os
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse
import psycopg
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schema.models import Filing, FactObservation, FactVersion, MaterialEvent
from pipeline.version_resolver import VersionResolver, CONCEPT_TO_METRIC


class StubDBManager:
    """In-memory stub database manager for zero-write replay."""
    def save_fact_version(self, version: FactVersion):
        pass

    def save_material_event(self, event: MaterialEvent):
        pass

    def save_normalized_metric(self, metric):
        pass


def main():
    replay_url = os.environ.get("REPLAY_DATABASE_URL", "").strip()
    if not replay_url:
        print("replay skipped: REPLAY_DATABASE_URL not set")
        sys.exit(0)

    parsed = urlparse(replay_url)
    host = parsed.hostname or "localhost"
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if host not in local_hosts:
        print(f"Refusing replay connection: host '{host}' is not local.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Replay VersionResolver classification on existing DB facts")
    parser.add_argument("--ticker", type=str, default="CF", help="Ticker symbol to replay (default: CF)")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    issuer_id = f"issuer_US_{ticker}"

    conn = psycopg.connect(replay_url, row_factory=dict_row)
    conn.read_only = True

    with conn.cursor() as cur:
        # Load filings
        cur.execute("""
            SELECT filing_id, issuer_id, accession_number, form_type, filing_date, report_period, amendment_flag, source_uri, source_hash
            FROM filing WHERE issuer_id = %s;
        """, (issuer_id,))
        filing_rows = cur.fetchall()

        filings = [
            Filing(
                filing_id=r["filing_id"],
                issuer_id=r["issuer_id"],
                accession_number=r["accession_number"],
                form_type=r["form_type"],
                filing_date=r["filing_date"],
                report_period=r["report_period"],
                amendment_flag=r["amendment_flag"],
                source_uri=r["source_uri"],
                source_hash=r["source_hash"]
            )
            for r in filing_rows
        ]

        # Load fact observations
        cur.execute("""
            SELECT fo.fact_id, fo.canonical_fact_key, fo.filing_id, fo.concept, fo.value, fo.unit, fo.currency, fo.period_start, fo.period_end, fo.instant_date, fo.dimensions
            FROM fact_observation fo
            JOIN filing f ON f.filing_id = fo.filing_id
            WHERE f.issuer_id = %s;
        """, (issuer_id,))
        fact_rows = cur.fetchall()

        facts = [
            FactObservation(
                fact_id=r["fact_id"],
                canonical_fact_key=r["canonical_fact_key"],
                filing_id=r["filing_id"],
                concept=r["concept"],
                value=float(r["value"]) if r["value"] is not None else None,
                unit=r["unit"],
                currency=r["currency"],
                period_start=r["period_start"],
                period_end=r["period_end"],
                instant_date=r["instant_date"],
                dimensions=r["dimensions"]
            )
            for r in fact_rows
        ]

    conn.close()

    stub_db = StubDBManager()
    resolver = VersionResolver(db_manager=stub_db)
    versions, events = resolver.resolve(filings, facts, [])

    summary = resolver.last_summary
    print(f"=== Replay Results for {ticker} ({issuer_id}) ===")
    print(f"  Filings: {len(filings)}")
    print(f"  Facts: {len(facts)}")
    print(f"  Classification Counts:")
    print(f"    UNCHANGED:     {summary['UNCHANGED']}")
    print(f"    SIGN_ONLY:     {summary['SIGN_ONLY']} (RECLASSIFIED)")
    print(f"    ZERO_BOUNDARY: {summary['ZERO_BOUNDARY']} (UNRESOLVED)")
    print(f"    VALUE_CHANGE:  {summary['VALUE_CHANGE']} (RESTATED)")
    print(f"  Events:")
    print(f"    HIGH severity: {summary['events_high']}")
    print(f"    LOW severity:  {summary['events_low']}")
    print()

    # Table of RESTATED rows on headline concepts
    headline_restatements = [
        e for e in events 
        if e.severity == "HIGH"
    ]

    print(f"=== Headline Concept RESTATED Table ({len(headline_restatements)} rows) ===")
    print(f"{'Concept':<55} | {'Orig Value':<15} | {'Pref Value':<15} | {'Orig Acc':<20} | {'Pref Acc':<20}")
    print("-" * 135)

    for e in headline_restatements:
        d = e.details
        concept = d.get("concept", "")
        orig_val = str(d.get("original_value"))
        pref_val = str(d.get("preferred_value"))
        orig_acc = d.get("original_accession", "")
        pref_acc = d.get("preferred_accession", "")
        print(f"{concept:<55} | {orig_val:<15} | {pref_val:<15} | {orig_acc:<20} | {pref_acc:<20}")

if __name__ == "__main__":
    main()
