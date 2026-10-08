"""
Team head's blocker #2: CF reports net income only under us-gaap:ProfitLoss, never NetIncomeLoss.
The plain, undimensioned ProfitLoss fact is the TOTAL including noncontrolling interests; the owners'/
parent share is reported separately, dimensioned by StatementEquityComponentsAxis=ParentMember in the
equity-statement rollforward, alongside irrelevant equity-component breakdowns (CommonStockMember etc.,
all 0) and the NCI-only share (NoncontrollingInterestMember). NET_INCOME must equal the parent share,
never the undimensioned total, whenever both exist for the same period -- reproduced here with CF's own
real FY2022-FY2025 figures.
"""
import datetime as dt
import pytest

from pipeline.normalizer import Normalizer
from schema.models import Issuer, Filing, FactObservation


ISSUER = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF", ticker="CF", cik="1324404", fiscal_year_end="1231")


class FakeDB:
    def __init__(self):
        self.saved_facts = []
        self.saved_metrics = []

    def save_fact_observations(self, facts):
        self.saved_facts.extend(facts)
        return facts

    def save_normalized_metrics(self, metrics):
        self.saved_metrics.extend(metrics)


def filing(acc, report_period):
    return Filing(filing_id=f"filing_{acc}", issuer_id=ISSUER.issuer_id, accession_number=acc, form_type="10-K",
                 filing_date=dt.date(report_period.year + 1, 2, 20), report_period=report_period, source_uri="u", source_hash="h")


def fact(fid, filing_id, value, start, end, dims=None):
    return FactObservation(fact_id=fid, canonical_fact_key=f"k_{fid}", filing_id=filing_id, concept="us-gaap:ProfitLoss",
                           value=value, unit="USD", currency="USD", period_start=start, period_end=end, dimensions=dims)


def run_cf_year(total, parent, nci, year):
    """Reproduces one CF fiscal year's real-shape ProfitLoss facts: total (undimensioned) + the equity
    rollforward's 5 components (3 zero, RetainedEarnings == Parent value, Parent, NCI)."""
    f = filing(f"a{year}", dt.date(year, 12, 31))
    start, end = dt.date(year, 1, 1), dt.date(year, 12, 31)
    facts = [
        fact(f"total{year}", f.filing_id, total, start, end),  # dims=None -> {}
        fact(f"common{year}", f.filing_id, 0.0, start, end, dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:CommonStockMember"}),
        fact(f"treasury{year}", f.filing_id, 0.0, start, end, dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:TreasuryStockCommonMember"}),
        fact(f"apic{year}", f.filing_id, 0.0, start, end, dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:AdditionalPaidInCapitalMember"}),
        fact(f"retained{year}", f.filing_id, parent, start, end, dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:RetainedEarningsMember"}),
        fact(f"aoci{year}", f.filing_id, 0.0, start, end, dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:AccumulatedOtherComprehensiveIncomeMember"}),
        fact(f"parent{year}", f.filing_id, parent, start, end, dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:ParentMember"}),
        fact(f"nci{year}", f.filing_id, nci, start, end, dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:NoncontrollingInterestMember"}),
    ]
    return f, facts


def test_cf_real_figures_all_five_years():
    """CF's actual reported numbers: NET_INCOME must equal the parent-attributable figure, not the total."""
    years = {2021: (1260, 917, 343), 2022: (3937, 3346, 591), 2023: (1838, 1525, 313), 2024: (1477, 1218, 259), 2025: (1798, 1455, 343)}
    filings, facts = [], []
    for year, (total, parent, nci) in years.items():
        f, fs = run_cf_year(total * 1_000_000.0, parent * 1_000_000.0, nci * 1_000_000.0, year)
        filings.append(f)
        facts.extend(fs)

    n = Normalizer(db_manager=FakeDB())
    _, metrics, issues = n.normalize(issuer=ISSUER, filings=filings, facts=facts, run_id="r1", history_years=5)

    net_income = {m.period: m.value for m in metrics if m.metric_code == "NET_INCOME"}
    for year, (total, parent, nci) in years.items():
        assert net_income[f"FY{year}"] == parent * 1_000_000.0, f"FY{year}: expected parent {parent}m, got {net_income[f'FY{year}']}"
        assert net_income[f"FY{year}"] != total * 1_000_000.0, f"FY{year}: must not equal the NCI-inclusive total {total}m"

    # no DIMENSION_AMBIGUITY for NET_INCOME: a qualifying fact was found for every period
    assert not any(i.rule_code == "DIMENSION_AMBIGUITY" and "NET_INCOME" in str(i.details) for i in issues)


def test_filer_with_no_nci_still_uses_the_plain_total():
    """A normal filer with no noncontrolling interest never has a ParentMember-dimensioned fact at all;
    the plain undimensioned total must still work exactly as before (no regression for the common case)."""
    f = filing("a1", dt.date(2025, 12, 31))
    facts = [fact("x1", f.filing_id, 500_000_000.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]  # dims=None
    n = Normalizer(db_manager=FakeDB())
    _, metrics, _ = n.normalize(issuer=ISSUER, filings=[f], facts=facts, run_id="r1", history_years=1)
    net_income = {m.period: m.value for m in metrics if m.metric_code == "NET_INCOME"}
    assert net_income["FY2025"] == 500_000_000.0


def test_net_income_loss_tag_still_works_unchanged():
    """A filer using the original us-gaap:NetIncomeLoss tag (EXP's shape) is unaffected by this change."""
    f = filing("a1", dt.date(2025, 12, 31))
    fct = FactObservation(fact_id="x1", canonical_fact_key="k1", filing_id=f.filing_id, concept="us-gaap:NetIncomeLoss",
                          value=463_416_000.0, unit="USD", currency="USD", period_start=dt.date(2025, 1, 1), period_end=dt.date(2025, 12, 31))
    n = Normalizer(db_manager=FakeDB())
    _, metrics, _ = n.normalize(issuer=ISSUER, filings=[f], facts=[fct], run_id="r1", history_years=1)
    net_income = {m.period: m.value for m in metrics if m.metric_code == "NET_INCOME"}
    assert net_income["FY2025"] == 463_416_000.0


def test_other_metrics_are_not_affected_by_the_parent_dimension_rule():
    """A dimensioned fact for a DIFFERENT metric (no attributable_to_parent_dimension configured) is still
    correctly rejected as before, never silently accepted."""
    f = filing("a1", dt.date(2025, 12, 31))
    fct = FactObservation(fact_id="x1", canonical_fact_key="k1", filing_id=f.filing_id, concept="us-gaap:Revenues",
                          value=100.0, unit="USD", currency="USD", period_start=dt.date(2025, 1, 1), period_end=dt.date(2025, 12, 31),
                          dimensions={"us-gaap:StatementEquityComponentsAxis": "us-gaap:ParentMember"})
    n = Normalizer(db_manager=FakeDB())
    _, metrics, issues = n.normalize(issuer=ISSUER, filings=[f], facts=[fct], run_id="r1", history_years=1)
    assert [m for m in metrics if m.metric_code == "REVENUE"] == []
    assert any(i.rule_code == "DIMENSION_AMBIGUITY" for i in issues)


def test_parent_dimension_must_match_exactly_not_as_a_subset():
    """A fact dimensioned by ParentMember PLUS another axis (e.g. a segment breakdown of the parent's own
    share) is a more specific figure, not the headline parent-attributable total; it must not qualify."""
    f = filing("a1", dt.date(2025, 12, 31))
    total = fact("total", f.filing_id, 1_798_000_000.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    extra_dim = fact("extra", f.filing_id, 999_000_000.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31),
                     dims={"us-gaap:StatementEquityComponentsAxis": "us-gaap:ParentMember", "us-gaap:StatementScenarioAxis": "us-gaap:ScenarioForecastMember"})
    n = Normalizer(db_manager=FakeDB())
    _, metrics, _ = n.normalize(issuer=ISSUER, filings=[f], facts=[total, extra_dim], run_id="r1", history_years=1)
    net_income = {m.period: m.value for m in metrics if m.metric_code == "NET_INCOME"}
    assert net_income["FY2025"] == 1_798_000_000.0   # falls back to the plain total; the over-dimensioned fact never qualifies
