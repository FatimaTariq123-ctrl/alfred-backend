"""
Unit Tests: Version Resolver & Multi-Filing Restatement Resolution (§7, Prompt Correction 1 & 6)

Tests the real restatement path: same fiscal period showing up in multiple filings
with different values (a later 10-K presenting restated prior-year columns).
Pure-logic test using lightweight unit-test DB double.
"""

import sys
from pathlib import Path
from datetime import date, datetime, timezone

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schema.models import Filing, FactObservation, NormalizedMetric, FactVersion, MaterialEvent
from pipeline.version_resolver import VersionResolver
from pipeline.normalizer import Normalizer


class MockDBManager:
    """Lightweight unit-test double for pure-logic testing without database connection."""
    def __init__(self):
        self.fact_versions = {}
        self.material_events = {}
        self.normalized_metrics = {}

    def save_fact_version(self, version: FactVersion):
        self.fact_versions[version.canonical_key] = version

    def save_material_event(self, event: MaterialEvent):
        self.material_events[event.event_id] = event

    def save_normalized_metric(self, metric: NormalizedMetric):
        self.normalized_metrics[metric.metric_id] = metric

    # Batch stubs (called by VersionResolver after the main loop)
    def save_fact_versions(self, versions):
        for v in versions:
            self.save_fact_version(v)

    def save_material_events(self, events):
        for e in events:
            self.save_material_event(e)


def test_multi_filing_same_period_restatement_resolution():
    mock_db = MockDBManager()
    version_resolver = VersionResolver(db_manager=mock_db)

    issuer_id = "issuer_US_GE"
    concept = "us-gaap:Revenues"
    period_str = "period:2022-12-31"
    unit = "USD"
    currency = "USD"

    canonical_key = Normalizer.compute_canonical_fact_key(
        issuer_id=issuer_id,
        concept=concept,
        period_str=period_str,
        unit=unit,
        currency=currency
    )

    # 1. Base 10-K filed in 2023 reporting 2022 Revenue = $100 Billion
    filing_2023 = Filing(
        filing_id="filing_ge_10k_2023",
        issuer_id=issuer_id,
        accession_number="0000040545-23-000010",
        form_type="10-K",
        filing_date=date(2023, 2, 10),
        report_period=date(2022, 12, 31),
        source_uri="http://example.com/2023.htm",
        source_hash="hash1"
    )

    fact_original = FactObservation(
        fact_id="fact_ge_2022_orig",
        canonical_fact_key=canonical_key,
        filing_id=filing_2023.filing_id,
        concept=concept,
        value=100000000000.0,
        unit=unit,
        currency=currency,
        period_end=date(2022, 12, 31)
    )

    # 2. Later 10-K filed in 2024 presenting restated 2022 Revenue = $95 Billion
    filing_2024 = Filing(
        filing_id="filing_ge_10k_2024",
        issuer_id=issuer_id,
        accession_number="0000040545-24-000015",
        form_type="10-K",
        filing_date=date(2024, 2, 12),
        report_period=date(2023, 12, 31),
        source_uri="http://example.com/2024.htm",
        source_hash="hash2"
    )

    fact_restated = FactObservation(
        fact_id="fact_ge_2022_restated",
        canonical_fact_key=canonical_key,
        filing_id=filing_2024.filing_id,
        concept=concept,
        value=95000000000.0,
        unit=unit,
        currency=currency,
        period_end=date(2022, 12, 31)
    )

    filings = [filing_2023, filing_2024]
    facts = [fact_original, fact_restated]
    metrics = [
        NormalizedMetric(
            metric_id="metric_1",
            issuer_id=issuer_id,
            metric_code="REVENUE",
            period="FY2022",
            value=100000000000.0,
            unit="USD",
            provenance_fact_ids=[fact_original.fact_id],
            provenance_filing_ids=[filing_2023.filing_id],
            comparability_status="COMPARABLE"
        )
    ]

    # Execute version resolution
    versions, events = version_resolver.resolve(filings, facts, metrics)

    assert len(versions) == 1, "Should resolve 1 fact version lineage for canonical key"
    v = versions[0]
    assert v.original_fact_id == fact_original.fact_id, "Original fact ID must match earliest observation"
    assert v.preferred_fact_id == fact_restated.fact_id, "Preferred fact ID must point to latest restated observation"
    assert v.version_reason == "RESTATED", "Version reason must be RESTATED"

    # Verify RESTATEMENT_OR_REVISION event emission
    assert len(events) == 1, "Must emit RESTATEMENT_OR_REVISION event when preferred != original"
    e = events[0]
    assert e.event_type == "RESTATEMENT_OR_REVISION", "Event type must be RESTATEMENT_OR_REVISION"
    assert e.details["original_value"] == 100000000000.0
    assert e.details["preferred_value"] == 95000000000.0

    print("Multi-filing same-period restatement unit test passed successfully!")


if __name__ == "__main__":
    test_multi_filing_same_period_restatement_resolution()
