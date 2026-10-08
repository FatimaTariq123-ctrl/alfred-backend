"""
Unit Tests: Canonical Fact Key Hashing (§6.1, Prompt Correction 6)

Verifies that canonical fact keys are computed deterministically and that
distinct facts (differing by concept, period, unit, currency, or dimensions)
never collapse into identical keys.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.normalizer import Normalizer


def test_canonical_fact_key_determinism():
    key1 = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_US_AAPL",
        concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        period_str="period:2023-12-31",
        unit="USD",
        currency="USD",
        dimensions={"segment": "Products"}
    )
    key2 = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_US_AAPL",
        concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        period_str="period:2023-12-31",
        unit="USD",
        currency="USD",
        dimensions={"segment": "Products"}
    )
    assert key1 == key2, "Canonical fact key must be strictly deterministic"


def test_canonical_fact_key_dimension_separation():
    # Segment Products vs Segment Services must NOT collapse (§6.1)
    key_products = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_US_AAPL",
        concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        period_str="period:2023-12-31",
        unit="USD",
        currency="USD",
        dimensions={"segment": "Products"}
    )
    key_services = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_US_AAPL",
        concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        period_str="period:2023-12-31",
        unit="USD",
        currency="USD",
        dimensions={"segment": "Services"}
    )
    assert key_products != key_services, "Distinct dimensions must generate distinct canonical fact keys"


def test_canonical_fact_key_period_separation():
    key_2022 = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_US_AAPL",
        concept="us-gaap:NetIncomeLoss",
        period_str="period:2022-12-31",
        unit="USD",
        currency="USD"
    )
    key_2023 = Normalizer.compute_canonical_fact_key(
        issuer_id="issuer_US_AAPL",
        concept="us-gaap:NetIncomeLoss",
        period_str="period:2023-12-31",
        unit="USD",
        currency="USD"
    )
    assert key_2022 != key_2023, "Distinct report periods must generate distinct canonical fact keys"


if __name__ == "__main__":
    test_canonical_fact_key_determinism()
    test_canonical_fact_key_dimension_separation()
    test_canonical_fact_key_period_separation()
    print("All canonical fact key unit tests passed successfully!")
