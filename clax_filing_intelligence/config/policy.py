"""
Configurable Policy Layer (§3, §10.1)

Do not hardcode market windows or policy thresholds inside connector code.
Store them as product policy configuration objects.
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field


DEFAULT_PRIORITY_SECTIONS: Dict[str, List[str]] = {
    "10-K": ["Item 1", "Item 1A", "Item 7", "Item 7A", "Item 8"],
    "10-Q": ["Part I, Item 1", "Part I, Item 2", "Part I, Item 3", "Part II, Item 1A"],
    "8-K": ["*"]
}

DEFAULT_REQUIRED_METRICS: Dict[str, Dict[str, Any]] = {
    "REVENUE": {
        "group": "revenue_trend",
        "period_type": "duration",
        "tags": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
    },
    "COST_OF_SALES": {
        "group": "margin_trend",
        "period_type": "duration",
        "tags": ["CostOfGoodsAndServicesSold", "CostOfRevenue"]
    },
    "GROSS_PROFIT": {
        "group": "margin_trend",
        "period_type": "duration",
        "tags": ["GrossProfit"]
    },
    "OPERATING_INCOME": {
        "group": "margin_trend",
        "period_type": "duration",
        "tags": ["OperatingIncomeLoss"]
    },
    "NET_INCOME": {
        "group": "margin_trend",
        "period_type": "duration",
        "tags": ["NetIncomeLoss", "ProfitLoss"],
        # Some filers report consolidated net income under us-gaap:ProfitLoss with no dimensions at all
        # (equals net income attributable to the parent, the common case with no noncontrolling interest).
        # Others (e.g. a filer with a noncontrolling interest) tag the undimensioned ProfitLoss fact as the
        # TOTAL including NCI, and separately report the owners'/parent share as the same concept dimensioned
        # by StatementEquityComponentsAxis=ParentMember in the equity-statement rollforward. For this metric,
        # that specific dimension combination is the one we want (net income attributable to the parent),
        # and it is preferred over an undimensioned "total" fact when both exist for the same period.
        "attributable_to_parent_dimension": {"us-gaap:StatementEquityComponentsAxis": "us-gaap:ParentMember"}
    },
    "INCOME_TAX": {
        "group": "margin_trend",
        "period_type": "duration",
        "tags": ["IncomeTaxExpenseBenefit"]
    },
    "EPS_DILUTED": {
        "group": "margin_trend",
        "period_type": "duration",
        "tags": ["EarningsPerShareDiluted"]
    },
    "OPERATING_CASH_FLOW": {
        "group": "cash_flow_quality",
        "period_type": "duration",
        "tags": ["NetCashProvidedByUsedInOperatingActivities"]
    },
    "CAPEX": {
        "group": "cash_flow_quality",
        "period_type": "duration",
        "tags": ["PaymentsToAcquirePropertyPlantAndEquipment"]
    },
    "DEPRECIATION_AMORTIZATION": {
        "group": "cash_flow_quality",
        "period_type": "duration",
        "tags": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"]
    },
    "TOTAL_ASSETS": {
        "group": "leverage",
        "period_type": "instant",
        "tags": ["Assets"]
    },
    "TOTAL_LIABILITIES": {
        "group": "leverage",
        "period_type": "instant",
        "tags": ["Liabilities"]
    },
    "EQUITY": {
        "group": "leverage",
        "period_type": "instant",
        "tags": ["StockholdersEquity"]
    },
    "LONG_TERM_DEBT": {
        "group": "leverage",
        "period_type": "instant",
        "tags": ["LongTermDebtNoncurrent", "LongTermDebt"]
    },
    "SHORT_TERM_DEBT": {
        "group": "leverage",
        "period_type": "instant",
        "tags": ["LongTermDebtCurrent", "DebtCurrent"]
    },
    "CASH": {
        "group": "liquidity",
        "period_type": "instant",
        "tags": ["CashAndCashEquivalentsAtCarryingValue"]
    },
    "CURRENT_ASSETS": {
        "group": "liquidity",
        "period_type": "instant",
        "tags": ["AssetsCurrent"]
    },
    "CURRENT_LIABILITIES": {
        "group": "liquidity",
        "period_type": "instant",
        "tags": ["LiabilitiesCurrent"]
    },
    "RECEIVABLES": {
        "group": "working_capital",
        "period_type": "instant",
        "tags": ["AccountsReceivableNetCurrent"]
    },
    "INVENTORY": {
        "group": "working_capital",
        "period_type": "instant",
        "tags": ["InventoryNet"]
    },
    "PAYABLES": {
        "group": "working_capital",
        "period_type": "instant",
        "tags": ["AccountsPayableCurrent"]
    },
    "DILUTED_SHARES": {
        "group": "dilution",
        "period_type": "duration",
        "tags": ["WeightedAverageNumberOfDilutedSharesOutstanding"]
    },
    "SHARE_BASED_COMPENSATION": {
        "group": "dilution",
        "period_type": "duration",
        "tags": ["ShareBasedCompensation"]
    },
    "DIVIDENDS_PAID": {
        "group": "capital_allocation",
        "period_type": "duration",
        "tags": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]
    },
    "SHARE_BUYBACKS": {
        "group": "capital_allocation",
        "period_type": "duration",
        "tags": ["PaymentsForRepurchaseOfCommonStock"]
    },
    "IMPAIRMENT": {
        "group": "accounting_quality",
        "period_type": "duration",
        "tags": ["GoodwillImpairmentLoss", "AssetImpairmentCharges"]
    }
}


class PolicyConfig(BaseModel):
    policy_version: str = Field(default="v1.1", description="Policy specification version")
    base_financial_history_years: int = Field(default=5, description="Default 5-year analytical baseline window")
    extended_financial_history_years: int = Field(default=10, description="Adaptive 10-year deep history window")
    forensic_history_years: int = Field(default=30, description="Forensic history analytical window years")
    us_quarter_lookback: int = Field(default=8, description="Number of 10-Q quarters to look back")
    us_material_event_months: int = Field(default=24, description="Months of 8-K material events to retrieve")
    hk_recent_interim_years: int = Field(default=3, description="HK interim/quarterly reporting lookback years")
    hk_material_event_months: int = Field(default=24, description="HK material event lookback months")
    forensic_history_mode: str = Field(default="on_demand", description="Forensic history mode trigger policy")
    amendments_always_check: bool = Field(default=True, description="Always check 10-K/A and 10-Q/A amendments")
    cycle_sensitive_tickers: List[str] = Field(
        default_factory=lambda: ["XOM", "CVX", "CAT", "DE", "FCX", "RIO"],
        description="Cycle-sensitive tickers trigger list"
    )
    
    # Priority sections for narrative extraction (§6)
    priority_sections: Dict[str, List[str]] = Field(
        default_factory=lambda: dict(DEFAULT_PRIORITY_SECTIONS),
        description="Priority narrative sections by form type"
    )

    # Fact scope & required metrics (§4.3)
    fact_scope: str = Field(
        default="all_numeric",
        description="Extraction fact scope: all_numeric, required_company_wide, required_all_dims"
    )
    required_metrics: Dict[str, Dict[str, Any]] = Field(
        default_factory=lambda: dict(DEFAULT_REQUIRED_METRICS),
        description="Required analytical metrics and ordered tag fallbacks"
    )

    # Normalizer: sign convention, non-additive metrics, period-matching tolerance, and which metrics must
    # always be present in every filing (used by the MISSING_PERIOD check). All policy-driven (§3, §10.1):
    # no metric code, ticker, or threshold is hardcoded in pipeline/normalizer.py itself.
    outflow_metrics: List[str] = Field(
        default_factory=lambda: ["CAPEX", "DIVIDENDS_PAID", "SHARE_BUYBACKS"],
        description="Metric codes whose normalized value is a cash outflow and must be stored as negative, "
                    "regardless of the sign the filer reported the underlying XBRL fact with"
    )
    non_additive_metrics: List[str] = Field(
        default_factory=lambda: ["EPS_DILUTED", "DILUTED_SHARES"],
        description="Metric codes that cannot be derived by addition/subtraction across quarters (per-share "
                    "and weighted-average-share figures are not additive)"
    )
    core_expected_metrics: List[str] = Field(
        default_factory=lambda: ["REVENUE", "NET_INCOME", "OPERATING_INCOME", "OPERATING_CASH_FLOW", "CAPEX"],
        description="Metric codes expected in every selected filing; a missing one raises a MISSING_PERIOD issue"
    )
    period_alignment_tolerance_days: int = Field(
        default=15,
        description="Max distance, in days, between a fact's period end and a fiscal year/quarter end candidate "
                    "for the fact to be labeled as that period"
    )
    recast_comparative_tolerance_days: int = Field(
        default=120,
        description="Max distance, in days, between a VALUE_CHANGE fact's own period end and the filing date "
                    "that carries it, for the fact to still count as that filing's own current-period data. "
                    "Must comfortably exceed the normal 10-K/10-Q filing lag (SEC gives large accelerated "
                    "filers up to 60 days for a 10-K and 40 for a 10-Q; smaller filers more) so a filing's own "
                    "primary-period figure is never mistaken for a stale comparative reported from years back."
    )

    # Batch processing configuration
    max_companies: int = Field(default=5, description="Maximum companies limit for batch universe runner")
    
    # Validation rules severity thresholds
    parser_version: str = Field(default="1.2.0", description="Parser version for provenance")
    normalizer_version: str = Field(default="1.1.0", description="Normalizer version for provenance")


    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# Default singleton policy configuration instance
DEFAULT_POLICY = PolicyConfig()
