import pytest
import pandas as pd
from datetime import date
from schema.models import Filing
from pipeline.parser import FilingParser
from config.policy import PolicyConfig


def make_filing(form_type="10-K", filing_id="f_test_100"):
    return Filing(
        filing_id=filing_id,
        issuer_id="issuer_US_TEST",
        accession_number="0000000000-24-000001",
        form_type=form_type,
        filing_date=date(2024, 3, 15),
        report_period=date(2023, 12, 31),
        source_uri="s3://bucket/filing.htm",
        source_hash="hash123"
    )


def test_numeric_rows_kept_and_text_rows_skipped():
    policy = PolicyConfig(fact_scope="all_numeric")
    parser = FilingParser(policy=policy)
    filing = make_filing()

    df = pd.DataFrame([
        {"concept": "us-gaap:Revenues", "value": 1000.0, "currency": "USD", "period_instant": "2023-12-31"},
        {"concept": "dei:EntityRegistrantName", "value": "Test Inc", "currency": None, "period_instant": "2023-12-31"},
        {"concept": "us-gaap:Assets", "value": 5000.0, "currency": "USD", "period_instant": "2023-12-31"},
    ])

    facts, skipped, req_found, req_missing = parser._facts_and_stats_from_dataframe(df, filing)
    assert len(facts) == 2
    assert skipped == 1
    assert all(f.value is not None for f in facts)


def test_scope_switches():
    df = pd.DataFrame([
        {"concept": "us-gaap:Revenues", "value": 1000.0, "currency": "USD", "period_instant": "2023-12-31"},  # required, company-wide
        {"concept": "us-gaap:Revenues", "value": 400.0, "currency": "USD", "period_instant": "2023-12-31", "dim_Segment": "NorthAmerica"},  # required, dimensioned
        {"concept": "us-gaap:OtherNonRequiredConcept", "value": 50.0, "currency": "USD", "period_instant": "2023-12-31"},  # non-required, company-wide
    ])
    filing = make_filing()

    # 1. all_numeric
    p_all = PolicyConfig(fact_scope="all_numeric")
    facts_all, _, _, _ = FilingParser(policy=p_all)._facts_and_stats_from_dataframe(df, filing)
    assert len(facts_all) == 3

    # 2. required_company_wide
    p_req_cw = PolicyConfig(fact_scope="required_company_wide")
    facts_req_cw, _, _, _ = FilingParser(policy=p_req_cw)._facts_and_stats_from_dataframe(df, filing)
    assert len(facts_req_cw) == 1
    assert facts_req_cw[0].concept == "us-gaap:Revenues"
    assert facts_req_cw[0].dimensions is None

    # 3. required_all_dims
    p_req_dims = PolicyConfig(fact_scope="required_all_dims")
    facts_req_dims, _, _, _ = FilingParser(policy=p_req_dims)._facts_and_stats_from_dataframe(df, filing)
    assert len(facts_req_dims) == 2
    assert all(f.concept == "us-gaap:Revenues" for f in facts_req_dims)


def test_required_found_and_missing():
    df = pd.DataFrame([
        {"concept": "us-gaap:Revenues", "value": 1000.0, "currency": "USD", "period_instant": "2023-12-31"},
        {"concept": "us-gaap:Assets", "value": 5000.0, "currency": "USD", "period_instant": "2023-12-31"},
    ])
    filing = make_filing()
    parser = FilingParser(policy=PolicyConfig())
    _, _, req_found, req_missing = parser._facts_and_stats_from_dataframe(df, filing)

    assert "REVENUE" in req_found
    assert "TOTAL_ASSETS" in req_found
    assert "NET_INCOME" in req_missing


def test_currency_formatting_and_na_safety():
    policy = PolicyConfig()
    parser = FilingParser(policy=policy)
    filing = make_filing()

    df = pd.DataFrame([
        {"concept": "us-gaap:Revenues", "value": 100.0, "currency": "USD", "period_instant": "2023-12-31"},
        {"concept": "us-gaap:Customers", "value": 50.0, "currency": "numberofcustomers", "period_instant": "2023-12-31"},
        {"concept": "us-gaap:Shares", "value": 10.0, "currency": pd.NA, "unit_ref": "shares", "period_instant": "2023-12-31"},
    ])

    facts, _, _, _ = parser._facts_and_stats_from_dataframe(df, filing)
    assert facts[0].currency == "USD"
    assert facts[0].unit == "USD"

    # "numberofcustomers" is not 3 uppercase letters => currency is None, unit is "numberofcustomers"
    assert facts[1].currency is None
    assert facts[1].unit == "numberofcustomers"

    # pd.NA handled safely => currency is None, unit is "shares"
    assert facts[2].currency is None
    assert facts[2].unit == "shares"


def test_8k_skips_xbrl_facts(monkeypatch):
    called = False

    def mock_extract_xbrl_facts(self, filing, raw_bytes, edgar_f=None):
        nonlocal called
        called = True
        return [], 0, {}, [], []

    monkeypatch.setattr(FilingParser, "_extract_xbrl_facts", mock_extract_xbrl_facts)

    parser = FilingParser()
    filing = make_filing(form_type="8-K")
    
    # Mock store and lookup
    monkeypatch.setattr(parser.store, "fetch_asset", lambda uri: b"<html>8K</html>")
    monkeypatch.setattr(parser, "_lookup_filing", lambda f: (None, []))
    monkeypatch.setattr(parser.db, "save_text_chunks", lambda chunks: None)

    facts, chunks = parser.extract([filing], [type("Asset", (), {"filing_id": filing.filing_id, "storage_uri": "uri"})()])
    assert called is False
    assert len(facts) == 0
