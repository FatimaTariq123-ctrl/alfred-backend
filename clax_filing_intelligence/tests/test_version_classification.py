"""
Unit Tests: Revision Classification & Version Resolver Refinements (§7)
"""

import sys
from pathlib import Path
from datetime import date, datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schema.models import Filing, FactObservation, NormalizedMetric, FactVersion, MaterialEvent
from pipeline.version_resolver import VersionResolver, classify_revision


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


def test_classify_revision_unit():
    assert classify_revision(100, 100) == "UNCHANGED"
    assert classify_revision(None, 5) == "UNCHANGED"
    assert classify_revision(0, 0) == "UNCHANGED"
    assert classify_revision(-653000000, 653000000) == "SIGN_ONLY"
    assert classify_revision(5, -5) == "SIGN_ONLY"
    assert classify_revision(0, 750000000) == "ZERO_BOUNDARY"
    assert classify_revision(54000000, 0) == "ZERO_BOUNDARY"
    assert classify_revision(100, 95) == "VALUE_CHANGE"
    assert classify_revision(1, -2) == "VALUE_CHANGE"


def test_sign_flip_resolution():
    mock_db = MockDBManager()
    resolver = VersionResolver(db_manager=mock_db)

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-Q", filing_date=date(2025, 8, 1), report_period=date(2025, 6, 30), source_uri="", source_hash="")
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-Q", filing_date=date(2026, 8, 1), report_period=date(2025, 6, 30), source_uri="", source_hash="")

    fact1 = FactObservation(fact_id="fact1", canonical_fact_key="ck1", filing_id="f1", concept="us-gaap:TreasuryStockRetiredCostMethodAmount", value=-653000000.0)
    fact2 = FactObservation(fact_id="fact2", canonical_fact_key="ck1", filing_id="f2", concept="us-gaap:TreasuryStockRetiredCostMethodAmount", value=653000000.0)

    metric = NormalizedMetric(metric_id="m1", issuer_id="i1", metric_code="REVENUE", period="Q2-2025", provenance_fact_ids=["fact1"], comparability_status="COMPARABLE")

    versions, events = resolver.resolve([filing1, filing2], [fact1, fact2], [metric])

    assert len(versions) == 1
    assert versions[0].version_reason == "RECLASSIFIED"
    assert len(events) == 0
    assert metric.comparability_status == "RECLASSIFIED"


def test_zero_boundary_resolution():
    mock_db = MockDBManager()
    resolver = VersionResolver(db_manager=mock_db)

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-K", filing_date=date(2024, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-K", filing_date=date(2025, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")

    fact1 = FactObservation(fact_id="fact1", canonical_fact_key="ck1", filing_id="f1", concept="us-gaap:OtherAssets", value=0.0)
    fact2 = FactObservation(fact_id="fact2", canonical_fact_key="ck1", filing_id="f2", concept="us-gaap:OtherAssets", value=750000000.0)

    metric = NormalizedMetric(metric_id="m1", issuer_id="i1", metric_code="DEBT", period="FY2023", provenance_fact_ids=["fact1"], comparability_status="COMPARABLE")

    versions, events = resolver.resolve([filing1, filing2], [fact1, fact2], [metric])

    assert versions[0].version_reason == "UNRESOLVED"
    assert len(events) == 0
    assert metric.comparability_status == "NON_COMPARABLE"
    assert resolver.last_summary["ZERO_BOUNDARY"] == 1


def test_value_change_headline_concept_high_event():
    mock_db = MockDBManager()
    resolver = VersionResolver(db_manager=mock_db)

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-K", filing_date=date(2024, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-K", filing_date=date(2025, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")

    fact1 = FactObservation(fact_id="fact1", canonical_fact_key="ck1", filing_id="f1", concept="us-gaap:Revenues", value=100.0)
    fact2 = FactObservation(fact_id="fact2", canonical_fact_key="ck1", filing_id="f2", concept="us-gaap:Revenues", value=95.0)

    versions, events = resolver.resolve([filing1, filing2], [fact1, fact2], [])

    assert versions[0].version_reason == "RESTATED"
    assert len(events) == 1
    assert events[0].severity == "HIGH"
    assert events[0].details["variance"] == -5.0


def test_value_change_low_events():
    mock_db = MockDBManager()
    resolver = VersionResolver(db_manager=mock_db)

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-K", filing_date=date(2024, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-K", filing_date=date(2025, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")

    # Non-headline concept
    fact1 = FactObservation(fact_id="f1_1", canonical_fact_key="ck1", filing_id="f1", concept="us-gaap:DefinedBenefitPlanFairValueOfPlanAssets", value=10.0)
    fact2 = FactObservation(fact_id="f1_2", canonical_fact_key="ck1", filing_id="f2", concept="us-gaap:DefinedBenefitPlanFairValueOfPlanAssets", value=12.0)

    # Headline concept WITH dimensions
    fact3 = FactObservation(fact_id="f2_1", canonical_fact_key="ck2", filing_id="f1", concept="us-gaap:Revenues", value=50.0, dimensions={"segment": "Cloud"})
    fact4 = FactObservation(fact_id="f2_2", canonical_fact_key="ck2", filing_id="f2", concept="us-gaap:Revenues", value=55.0, dimensions={"segment": "Cloud"})

    versions, events = resolver.resolve([filing1, filing2], [fact1, fact2, fact3, fact4], [])

    assert len(events) == 2
    assert events[0].severity == "LOW"
    assert events[1].severity == "LOW"


def test_deterministic_event_id():
    mock_db1 = MockDBManager()
    mock_db2 = MockDBManager()
    resolver1 = VersionResolver(db_manager=mock_db1)
    resolver2 = VersionResolver(db_manager=mock_db2)

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-K", filing_date=date(2024, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-K", filing_date=date(2025, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")

    fact1_a = FactObservation(fact_id="random_id_1a", canonical_fact_key="ck_same", filing_id="f1", concept="us-gaap:Revenues", value=100.0)
    fact1_b = FactObservation(fact_id="random_id_1b", canonical_fact_key="ck_same", filing_id="f2", concept="us-gaap:Revenues", value=95.0)

    fact2_a = FactObservation(fact_id="random_id_2a", canonical_fact_key="ck_same", filing_id="f1", concept="us-gaap:Revenues", value=100.0)
    fact2_b = FactObservation(fact_id="random_id_2b", canonical_fact_key="ck_same", filing_id="f2", concept="us-gaap:Revenues", value=95.0)

    _, events1 = resolver1.resolve([filing1, filing2], [fact1_a, fact1_b], [])
    _, events2 = resolver2.resolve([filing1, filing2], [fact2_a, fact2_b], [])

    assert events1[0].event_id == events2[0].event_id


def test_effective_from_timezone_utc():
    mock_db = MockDBManager()
    resolver = VersionResolver(db_manager=mock_db)

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-K", filing_date=date(2024, 2, 15), report_period=date(2023, 12, 31), source_uri="", source_hash="")
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-K", filing_date=date(2025, 2, 20), report_period=date(2023, 12, 31), source_uri="", source_hash="")

    fact1 = FactObservation(fact_id="f1", canonical_fact_key="ck1", filing_id="f1", concept="us-gaap:Revenues", value=100.0)
    fact2 = FactObservation(fact_id="f2", canonical_fact_key="ck1", filing_id="f2", concept="us-gaap:Revenues", value=95.0)

    versions, _ = resolver.resolve([filing1, filing2], [fact1, fact2], [])

    expected_effective = datetime(2025, 2, 20, 0, 0, 0, tzinfo=timezone.utc)
    assert versions[0].effective_from == expected_effective


def test_metric_comparability_order_independence():
    mock_db = MockDBManager()

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-K", filing_date=date(2024, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-K", filing_date=date(2025, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="")

    # Key 1: Sign flip (SIGN_ONLY -> RECLASSIFIED)
    fact1_a = FactObservation(fact_id="f1_a", canonical_fact_key="ck1", filing_id="f1", concept="c1", value=-10.0)
    fact1_b = FactObservation(fact_id="f1_b", canonical_fact_key="ck1", filing_id="f2", concept="c1", value=10.0)

    # Key 2: Value change (VALUE_CHANGE -> RESTATED)
    fact2_a = FactObservation(fact_id="f2_a", canonical_fact_key="ck2", filing_id="f1", concept="c2", value=100.0)
    fact2_b = FactObservation(fact_id="f2_b", canonical_fact_key="ck2", filing_id="f2", concept="c2", value=90.0)

    metric = NormalizedMetric(
        metric_id="m1", issuer_id="i1", metric_code="REVENUE", period="FY2023",
        provenance_fact_ids=["f1_a", "f2_a"], comparability_status="COMPARABLE"
    )

    # Resolve order 1: [fact1_a, fact1_b, fact2_a, fact2_b]
    r1 = VersionResolver(db_manager=mock_db)
    r1.resolve([filing1, filing2], [fact1_a, fact1_b, fact2_a, fact2_b], [metric])
    status1 = metric.comparability_status

    # Reset metric
    metric.comparability_status = "COMPARABLE"

    # Resolve order 2: [fact2_a, fact2_b, fact1_a, fact1_b]
    r2 = VersionResolver(db_manager=mock_db)
    r2.resolve([filing1, filing2], [fact2_a, fact2_b, fact1_a, fact1_b], [metric])
    status2 = metric.comparability_status

    assert status1 == "RESTATED"
    assert status2 == "RESTATED"


def test_equal_values_amended_and_original():
    mock_db = MockDBManager()
    resolver = VersionResolver(db_manager=mock_db)

    filing1 = Filing(filing_id="f1", issuer_id="i1", accession_number="acc1", form_type="10-K", filing_date=date(2024, 2, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="", amendment_flag=False)
    filing2 = Filing(filing_id="f2", issuer_id="i1", accession_number="acc2", form_type="10-K/A", filing_date=date(2024, 3, 1), report_period=date(2023, 12, 31), source_uri="", source_hash="", amendment_flag=True)

    fact1 = FactObservation(fact_id="fact1", canonical_fact_key="ck1", filing_id="f1", concept="us-gaap:Revenues", value=100.0)
    fact2 = FactObservation(fact_id="fact2", canonical_fact_key="ck1", filing_id="f2", concept="us-gaap:Revenues", value=100.0)

    # 1. Preferred is amended filing
    versions, _ = resolver.resolve([filing1, filing2], [fact1, fact2], [])
    assert versions[0].version_reason == "AMENDED"

    # 2. Single observation
    versions_single, _ = resolver.resolve([filing1], [fact1], [])
    assert versions_single[0].version_reason == "ORIGINAL"
