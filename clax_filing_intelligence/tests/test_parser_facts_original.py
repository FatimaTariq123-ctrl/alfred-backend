import numpy as np
import pandas as pd
import pytest
from datetime import date
from unittest.mock import MagicMock

from schema.models import Filing, FactObservation
from pipeline.parser import (
    FilingParser,
    _axis_from_column,
    _is_missing,
    _is_true,
)
from pipeline.normalizer import Normalizer


def make_parser() -> FilingParser:
    return FilingParser(object_store=MagicMock(), db_manager=MagicMock())


def make_filing() -> Filing:
    return Filing(
        filing_id="filing_123",
        issuer_id="issuer_123",
        accession_number="0000320193-23-000106",
        form_type="10-K",
        filing_date=date(2023, 10, 27),
        report_period=date(2023, 9, 30),
        storage_uri="s3://test/asset.hdr",
        source_uri="https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm",
        source_hash="sha256_mock_hash",
    )


def test_axis_from_column():
    assert _axis_from_column("dim_us-gaap_StatementBusinessSegmentsAxis") == "us-gaap:StatementBusinessSegmentsAxis"
    assert _axis_from_column("dim_srt_ProductOrServiceAxis") == "srt:ProductOrServiceAxis"
    assert _axis_from_column("dim_us-gaap_FairValueByFairValueHierarchyLevelAxis") == "us-gaap:FairValueByFairValueHierarchyLevelAxis"
    assert _axis_from_column("dim_us-gaap_DebtInstrumentAxis") == "us-gaap:DebtInstrumentAxis"
    assert _axis_from_column("dim_SomeAxis") == "SomeAxis"
    assert _axis_from_column("SomeAxis") == "SomeAxis"


def test_two_populated_dim_columns():
    parser = make_parser()
    df = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 100.0,
        "dim_us-gaap_StatementBusinessSegmentsAxis": "us-gaap:iPhoneMember",
        "dim_srt_ProductOrServiceAxis": "srt:ProductsMember",
        "dim_us-gaap_DebtInstrumentAxis": np.nan,
        "period_start": "2023-01-01",
        "period_end": "2023-09-30",
    }])
    filing = make_filing()
    facts = parser._facts_from_dataframe(df, filing)
    assert len(facts) == 1
    assert facts[0].dimensions == {
        "us-gaap:StatementBusinessSegmentsAxis": "us-gaap:iPhoneMember",
        "srt:ProductOrServiceAxis": "srt:ProductsMember",
    }


def test_no_dimensions_not_dimensioned():
    parser = make_parser()
    df = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 100.0,
        "is_dimensioned": False,
        "period_start": "2023-01-01",
        "period_end": "2023-09-30",
    }])
    filing = make_filing()
    facts = parser._facts_from_dataframe(df, filing)
    assert facts[0].dimensions is None


def test_legacy_dimension_member_fallback():
    parser = make_parser()
    df = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 100.0,
        "dimension": "us-gaap:SegmentAxis",
        "member": "us-gaap:SegmentMember",
        "period_start": "2023-01-01",
        "period_end": "2023-09-30",
    }])
    filing = make_filing()
    facts = parser._facts_from_dataframe(df, filing)
    assert facts[0].dimensions == {
        "us-gaap:SegmentAxis": "us-gaap:SegmentMember",
        "_partial_dimensions": "true",
    }


def test_is_dimensioned_true_unparsed_fallback():
    parser = make_parser()
    df = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 100.0,
        "is_dimensioned": True,
        "period_start": "2023-01-01",
        "period_end": "2023-09-30",
    }])
    filing = make_filing()
    facts = parser._facts_from_dataframe(df, filing)
    assert facts[0].dimensions == {"_unparsed_dimension": "true"}


def test_instant_row_dates():
    parser = make_parser()
    df = pd.DataFrame([{
        "concept": "us-gaap:Assets",
        "numeric_value": 500.0,
        "period_instant": "2023-09-30",
        "period_start": np.nan,
        "period_end": np.nan,
    }])
    filing = make_filing()
    facts = parser._facts_from_dataframe(df, filing)
    fact = facts[0]
    assert fact.instant_date == date(2023, 9, 30)
    assert fact.period_start is None
    assert fact.period_end is None


def test_duration_row_dates():
    parser = make_parser()
    df = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 1000.0,
        "period_start": "2022-10-01",
        "period_end": "2023-09-30",
        "period_instant": np.nan,
    }])
    filing = make_filing()
    facts = parser._facts_from_dataframe(df, filing)
    fact = facts[0]
    assert fact.period_start == date(2022, 10, 1)
    assert fact.period_end == date(2023, 9, 30)
    assert fact.instant_date is None


def test_no_period_fields_no_fallback():
    parser = make_parser()
    df = pd.DataFrame([{
        "concept": "us-gaap:SharesAuthorized",
        "numeric_value": 100000.0,
    }])
    filing = make_filing()
    facts = parser._facts_from_dataframe(df, filing)
    fact = facts[0]
    assert fact.period_start is None
    assert fact.period_end is None
    assert fact.instant_date is None
    assert fact.period_end != filing.report_period


def test_missing_values_pandas_na_safety():
    parser = make_parser()
    df = pd.DataFrame({
        "concept": ["us-gaap:Cash", "us-gaap:Debt"],
        "numeric_value": pd.Series([pd.NA, float("nan")], dtype="object"),
        "value": pd.Series([None, np.nan], dtype="object"),
        "period_instant": pd.Series([pd.NA, "<NA>"], dtype="object"),
        "dim_us-gaap_SegmentAxis": pd.Series([pd.NA, "None"], dtype="object"),
        "is_dimensioned": pd.Series([pd.NA, False], dtype="object"),
    })
    filing = make_filing()
    # Non-numeric rows are skipped under the numeric-only policy, while ensuring pandas NA values cause no exceptions.
    facts = parser._facts_from_dataframe(df, filing)
    assert len(facts) == 0
    _, skipped_non_numeric_count, _, _ = parser._facts_and_stats_from_dataframe(df, filing)
    assert skipped_non_numeric_count == 2


def test_dimension_determinism_and_canonical_keys():
    parser = make_parser()
    filing = make_filing()

    df1 = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 100.0,
        "dim_us-gaap_StatementBusinessSegmentsAxis": "us-gaap:iPhoneMember",
        "dim_srt_ProductOrServiceAxis": "srt:ProductsMember",
        "period_start": "2023-01-01",
        "period_end": "2023-09-30",
    }])

    df2 = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 100.0,
        "dim_srt_ProductOrServiceAxis": "srt:ProductsMember",
        "dim_us-gaap_StatementBusinessSegmentsAxis": "us-gaap:iPhoneMember",
        "period_start": "2023-01-01",
        "period_end": "2023-09-30",
    }])

    df3 = pd.DataFrame([{
        "concept": "us-gaap:Revenues",
        "numeric_value": 100.0,
        "dim_us-gaap_StatementBusinessSegmentsAxis": "us-gaap:iPhoneMember",
        "dim_srt_ProductOrServiceAxis": "srt:ProductsMember",
        "dim_us-gaap_FairValueByFairValueHierarchyLevelAxis": "us-gaap:FairValueInputsLevel1Member",
        "period_start": "2023-01-01",
        "period_end": "2023-09-30",
    }])

    f1 = parser._facts_from_dataframe(df1, filing)[0]
    f2 = parser._facts_from_dataframe(df2, filing)[0]
    f3 = parser._facts_from_dataframe(df3, filing)[0]

    assert f1.dimensions == f2.dimensions
    key1 = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_123", concept=f1.concept, period_str="2023-01-01_2023-09-30", unit=f1.unit, currency=f1.currency, dimensions=f1.dimensions
    )
    key2 = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_123", concept=f2.concept, period_str="2023-01-01_2023-09-30", unit=f2.unit, currency=f2.currency, dimensions=f2.dimensions
    )
    key3 = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_123", concept=f3.concept, period_str="2023-01-01_2023-09-30", unit=f3.unit, currency=f3.currency, dimensions=f3.dimensions
    )

    assert key1 == key2
    assert key1 != key3


def test_is_consolidated_fact_behavior():
    def make_fact(dims):
        return FactObservation(
            fact_id="fact_123",
            canonical_fact_key="key",
            filing_id="filing_123",
            concept="us-gaap:Revenues",
            value=100.0,
            dimensions=dims,
        )

    # None -> True (consolidated)
    assert Normalizer._is_consolidated_fact(make_fact(None)) is True
    
    # Empty dict -> True (consolidated)
    assert Normalizer._is_consolidated_fact(make_fact({})) is True

    # Real axes dict -> False (dimensioned)
    axes = {"us-gaap:StatementBusinessSegmentsAxis": "us-gaap:iPhoneMember"}
    assert Normalizer._is_consolidated_fact(make_fact(axes)) is False

    # Partial dimensions marker -> False (dimensioned)
    partial_dims = {"us-gaap:SegmentAxis": "us-gaap:SegmentMember", "_partial_dimensions": "true"}
    assert Normalizer._is_consolidated_fact(make_fact(partial_dims)) is False

    # Unparsed dimension marker -> False (dimensioned)
    unparsed_dims = {"_unparsed_dimension": "true"}
    assert Normalizer._is_consolidated_fact(make_fact(unparsed_dims)) is False


def test_facts_from_dataframe_no_period_warning(caplog):
    parser = make_parser()
    filing = make_filing()

    df = pd.DataFrame([
        {
            "concept": "us-gaap:Revenues",
            "numeric_value": 100.0,
            "period_start": "2023-01-01",
            "period_end": "2023-09-30",
        },
        {
            "concept": "us-gaap:Revenues",
            "numeric_value": 50.0,
            "dim_us-gaap_StatementBusinessSegmentsAxis": "us-gaap:iPhoneMember",
            "dim_srt_ProductOrServiceAxis": "srt:ProductsMember",
            "period_start": "2023-01-01",
            "period_end": "2023-09-30",
        },
        {
            "concept": "us-gaap:NoPeriodConcept",
            "numeric_value": 42.0,
            "context_ref": "c-12345",
        },
    ])

    with caplog.at_level("WARNING"):
        facts = parser._facts_from_dataframe(df, filing)

    assert len(facts) == 3
    warning_logs = [rec for rec in caplog.records if "contained 1 facts with no period information" in rec.message]
    assert len(warning_logs) == 1
    assert "concept=us-gaap:NoPeriodConcept" in warning_logs[0].message
    assert "context_ref=c-12345" in warning_logs[0].message
