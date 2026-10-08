from datetime import date
from schema.models import Filing
from pipeline.indexer import (
    _is_amendment,
    _base_form,
    _clean_fiscal_year_end,
    _derive_fiscal_year_end,
)


def test_is_amendment():
    assert _is_amendment("10-K/A") is True
    assert _is_amendment("10-Q/A") is True
    assert _is_amendment("8-K/A") is True
    assert _is_amendment("SC 13D/A") is True

    assert _is_amendment("10-K") is False
    assert _is_amendment("DEF 14A") is False
    assert _is_amendment("DEFA14A") is False
    assert _is_amendment("10-KT") is False
    assert _is_amendment("10-K405") is False


def test_base_form():
    assert _base_form("10-K/A") == "10-K"
    assert _base_form("10-Q/A") == "10-Q"
    assert _base_form("DEF 14A") == "DEF 14A"
    assert _base_form("DEFA14A") == "DEFA14A"


def test_clean_fiscal_year_end():
    assert _clean_fiscal_year_end("0926") == "0926"
    assert _clean_fiscal_year_end("1231") == "1231"

    assert _clean_fiscal_year_end("1331") is None
    assert _clean_fiscal_year_end("0230x") is None
    assert _clean_fiscal_year_end("9/26") is None
    assert _clean_fiscal_year_end(None) is None
    assert _clean_fiscal_year_end("") is None


def test_derive_fiscal_year_end():
    filings = [
        Filing(
            filing_id="f1",
            issuer_id="iss1",
            accession_number="001",
            form_type="10-Q",
            filing_date=date(2022, 6, 1),
            report_period=date(2022, 5, 31),
            source_uri="u",
            source_hash="h"
        ),
        Filing(
            filing_id="f2",
            issuer_id="iss1",
            accession_number="002",
            form_type="10-K",
            filing_date=date(2022, 10, 25),
            report_period=date(2022, 9, 30),
            source_uri="u",
            source_hash="h"
        ),
        Filing(
            filing_id="f3",
            issuer_id="iss1",
            accession_number="003",
            form_type="10-K/A",
            filing_date=date(2023, 11, 1),
            report_period=date(2023, 9, 30),
            source_uri="u",
            source_hash="h"
        ),
        Filing(
            filing_id="f4",
            issuer_id="iss1",
            accession_number="004",
            form_type="10-K",
            filing_date=date(2023, 10, 27),
            report_period=date(2023, 9, 30),
            source_uri="u",
            source_hash="h"
        ),
    ]

    # Should pick latest 10-K (f4 with report_period 2023-09-30) -> "0930"
    assert _derive_fiscal_year_end(filings) == "0930"

    # Should return None if no 10-K present
    no_10k_filings = [f for f in filings if f.form_type != "10-K"]
    assert _derive_fiscal_year_end(no_10k_filings) is None
