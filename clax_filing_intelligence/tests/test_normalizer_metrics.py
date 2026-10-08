"""
Step 4c/4d/4e (normalizer rewrite): the full metric list comes from policy.required_metrics (not a hand-typed
4-entry dict), 10-Q cumulative cash-flow facts are turned into derived quarters instead of being dropped,
operating cash flow is matched on its correct tag, and an outflow metric's sign is changed only on the
normalized_metric row -- never on the stored fact_observation. Uses a fake DB (no real Postgres needed).
"""
import datetime as dt
import pytest

from pipeline.normalizer import Normalizer, CONCEPT_TO_METRIC
from schema.models import Issuer, Filing, FactObservation


class FakeDB:
    def __init__(self):
        self.saved_facts = []
        self.saved_metrics = []

    def save_fact_observations(self, facts):
        self.saved_facts.extend(facts)
        return facts

    def save_normalized_metrics(self, metrics):
        self.saved_metrics.extend(metrics)


ISSUER = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF", ticker="CF", cik="1324404", fiscal_year_end="1231")


def filing(acc, form, report_period):
    return Filing(filing_id=f"filing_{acc}", issuer_id=ISSUER.issuer_id, accession_number=acc, form_type=form,
                 filing_date=report_period, report_period=report_period, source_uri="u", source_hash="h")


def fact(fid, filing_id, concept, value, start=None, end=None, instant=None, dims=None):
    return FactObservation(fact_id=fid, canonical_fact_key=f"k_{fid}", filing_id=filing_id, concept=concept, value=value,
                           unit="USD", currency="USD", period_start=start, period_end=end, instant_date=instant, dimensions=dims)


def run(filings, facts, history_years=5):
    db = FakeDB()
    n = Normalizer(db_manager=db)
    normalized_facts, metrics, issues = n.normalize(issuer=ISSUER, filings=filings, facts=facts, run_id="r1", history_years=history_years)
    return normalized_facts, metrics, issues, db


# ---------------------------------------------------------------- the metric list comes from policy, not a 4-entry dict
def test_concept_to_metric_covers_the_full_policy_list():
    from config.policy import DEFAULT_POLICY
    assert len(CONCEPT_TO_METRIC) >= 25
    assert CONCEPT_TO_METRIC["us-gaap:NetCashProvidedByUsedInOperatingActivities"] == "OPERATING_CASH_FLOW"
    assert set(DEFAULT_POLICY.required_metrics) <= {CONCEPT_TO_METRIC[k] for k in CONCEPT_TO_METRIC}


def test_gross_profit_and_income_tax_are_normalized_without_any_extra_wiring():
    """These were never in the old hand-typed CONCEPT_TO_METRIC at all."""
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:GrossProfit", 500.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
          fact("x2", fl[0].filing_id, "us-gaap:IncomeTaxExpenseBenefit", 50.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    codes = {m.metric_code for m in metrics}
    assert {"GROSS_PROFIT", "INCOME_TAX"} <= codes


# ---------------------------------------------------------------- operating cash flow tag fix
def test_operating_cash_flow_matches_the_real_xbrl_tag():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:NetCashProvidedByUsedInOperatingActivities", 900.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    ocf = [m for m in metrics if m.metric_code == "OPERATING_CASH_FLOW"]
    assert len(ocf) == 1 and ocf[0].value == 900.0


def test_the_old_wrong_tag_matches_nothing():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:OperatingCashFlows", 900.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    assert [m for m in metrics if m.metric_code == "OPERATING_CASH_FLOW"] == []


# ---------------------------------------------------------------- 10-Q cumulative cash flow -> derived quarters
def test_capex_q2_and_q3_are_derived_from_cumulative_10q_cash_flow():
    """CF's exact real-world shape: a 10-K (FY) + four 10-Qs where capex is reported cumulative (3mo for Q1,
    6mo for Q2's filing, 9mo for Q3's filing) -- never as a standalone Q2 or Q3 duration."""
    fl = [
        filing("fy", "10-K", dt.date(2025, 12, 31)),
        filing("q1", "10-Q", dt.date(2025, 3, 31)),
        filing("q2", "10-Q", dt.date(2025, 6, 30)),
        filing("q3", "10-Q", dt.date(2025, 9, 30)),
    ]
    tag = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
    fs = [
        fact("fy", fl[0].filing_id, tag, 950.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
        fact("q1", fl[1].filing_id, tag, 223.0, dt.date(2025, 1, 1), dt.date(2025, 3, 31)),        # standalone Q1 (3mo)
        fact("h1", fl[2].filing_id, tag, 400.0, dt.date(2025, 1, 1), dt.date(2025, 6, 30)),         # cumulative 6mo
        fact("9m", fl[3].filing_id, tag, 700.0, dt.date(2025, 1, 1), dt.date(2025, 9, 30)),         # cumulative 9mo
    ]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    by_period = {m.period: m for m in metrics if m.metric_code == "CAPEX"}
    assert by_period["Q1-2025"].value == -223.0
    assert "Q2-2025 (DERIVED)" in by_period and by_period["Q2-2025 (DERIVED)"].value == -(400.0 - 223.0)
    assert "Q3-2025 (DERIVED)" in by_period and by_period["Q3-2025 (DERIVED)"].value == -(700.0 - 400.0)
    assert "Q4-2025 (DERIVED)" in by_period
    q4 = by_period["Q4-2025 (DERIVED)"].value
    assert q4 == pytest.approx(-(950.0 - (223.0 + (400.0 - 223.0) + (700.0 - 400.0))))


def test_directly_reported_quarter_is_preferred_over_a_derived_one():
    fl = [filing("fy", "10-K", dt.date(2025, 12, 31)), filing("q1", "10-Q", dt.date(2025, 3, 31)),
         filing("q2", "10-Q", dt.date(2025, 6, 30))]
    tag = "us-gaap:NetIncomeLoss"
    fs = [fact("fy", fl[0].filing_id, tag, 1000.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
         fact("q1", fl[1].filing_id, tag, 200.0, dt.date(2025, 1, 1), dt.date(2025, 3, 31)),
         fact("q2std", fl[2].filing_id, tag, 210.0, dt.date(2025, 4, 1), dt.date(2025, 6, 30)),   # standalone 3mo Q2, reported directly
         fact("h1", fl[2].filing_id, tag, 410.0, dt.date(2025, 1, 1), dt.date(2025, 6, 30))]      # cumulative 6mo, same filing
    _, metrics, _, _ = run(fl, fs, history_years=1)
    q2 = {m.period: m for m in metrics if m.metric_code == "NET_INCOME"}["Q2-2025"]
    assert q2.value == 210.0 and not q2.is_derived   # the direct one wins; no "(DERIVED)" row exists alongside it
    assert "Q2-2025 (DERIVED)" not in {m.period for m in metrics if m.metric_code == "NET_INCOME"}


def test_eps_diluted_is_never_derived_across_quarters():
    fl = [filing("fy", "10-K", dt.date(2025, 12, 31)), filing("q1", "10-Q", dt.date(2025, 3, 31)),
         filing("q2", "10-Q", dt.date(2025, 6, 30))]
    tag = "us-gaap:EarningsPerShareDiluted"
    fs = [fact("fy", fl[0].filing_id, tag, 4.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
         fact("q1", fl[1].filing_id, tag, 1.0, dt.date(2025, 1, 1), dt.date(2025, 3, 31)),
         fact("h1", fl[2].filing_id, tag, 2.1, dt.date(2025, 1, 1), dt.date(2025, 6, 30))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    periods = {m.period for m in metrics if m.metric_code == "EPS_DILUTED"}
    assert not any("DERIVED" in p for p in periods)


# ---------------------------------------------------------------- outflow sign: metric only, never the stored fact
def test_capex_sign_is_flipped_on_the_metric_but_the_stored_fact_keeps_the_filers_sign():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 416739000.0,
              dt.date(2025, 1, 1), dt.date(2025, 12, 31))]   # filer reports capex as a positive payment
    normalized_facts, metrics, _, db = run(fl, fs, history_years=1)
    stored = next(f for f in db.saved_facts if f.fact_id == "x1")
    assert stored.value == 416739000.0                       # unchanged: still positive, exactly as reported
    capex = next(m for m in metrics if m.metric_code == "CAPEX")
    assert capex.value == -416739000.0                       # negative only on the metric


def test_dividends_and_buybacks_are_also_outflow_signed():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:PaymentsOfDividends", 100.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
         fact("x2", fl[0].filing_id, "us-gaap:PaymentsForRepurchaseOfCommonStock", 50.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, db = run(fl, fs, history_years=1)
    assert next(m for m in metrics if m.metric_code == "DIVIDENDS_PAID").value == -100.0
    assert next(m for m in metrics if m.metric_code == "SHARE_BUYBACKS").value == -50.0
    assert all(f.value > 0 for f in db.saved_facts)           # every stored fact is untouched / still positive


def test_revenue_is_never_sign_flipped():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:Revenues", 2308658000.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    assert next(m for m in metrics if m.metric_code == "REVENUE").value == 2308658000.0


# ---------------------------------------------------------------- substring-match bug is gone
def test_net_income_attributable_to_noncontrolling_interest_is_not_picked_as_net_income():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:NetIncomeLoss", 1455000000.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
         fact("x2", fl[0].filing_id, "us-gaap:NetIncomeLossAttributableToNoncontrollingInterest", 5000000.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    ni = [m for m in metrics if m.metric_code == "NET_INCOME"]
    assert len(ni) == 1 and ni[0].value == 1455000000.0     # only the exact tag is picked, not the noncontrolling-interest one


def test_substring_match_does_not_classify_an_unrelated_concept_in_isolation():
    """Isolates the substring-match bug with NO competing exact-tag fact present, so a tie-break on filing
    recency or tag priority cannot accidentally mask a wrong classification: under the old
    `key_concept in fact.concept` substring check, "NetIncomeLoss" is a substring of
    "NetIncomeLossAttributableToNoncontrollingInterest", so this ALONE would be wrongly picked as NET_INCOME."""
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:NetIncomeLossAttributableToNoncontrollingInterest", 5000000.0,
              dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    assert [m for m in metrics if m.metric_code == "NET_INCOME"] == []


def test_custom_taxonomy_concept_with_a_matching_local_name_is_not_picked():
    """Only us-gaap:<tag> counts; a company-extension concept that happens to share a local name must not match."""
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "cf:Revenues", 999.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    assert [m for m in metrics if m.metric_code == "REVENUE"] == []


# ---------------------------------------------------------------- deterministic selection + correct provenance
def test_chosen_fact_is_first_in_provenance_and_tag_order_breaks_same_filing_ties():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:Revenues", 100.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
         fact("x2", fl[0].filing_id, "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 101.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    rev = next(m for m in metrics if m.metric_code == "REVENUE")
    assert rev.provenance_fact_ids[0] == "x2"    # RevenueFromContract... is earlier in policy's tag list than Revenues
    assert rev.value == 101.0
    assert set(rev.provenance_fact_ids) == {"x1", "x2"}


def test_later_filing_wins_over_tag_priority():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31)), filing("a2", "10-K/A", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 100.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
         fact("x2", fl[1].filing_id, "us-gaap:Revenues", 150.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, metrics, _, _ = run(fl, fs, history_years=1)
    rev = next(m for m in metrics if m.metric_code == "REVENUE")
    assert rev.provenance_fact_ids[0] == "x2" and rev.value == 150.0  # the amendment (later filing) wins


def test_dimensioned_only_metric_raises_dimension_ambiguity_not_a_guessed_value():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:Revenues", 50.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31), dims={"seg": "A"})]
    _, metrics, issues, _ = run(fl, fs, history_years=1)
    assert [m for m in metrics if m.metric_code == "REVENUE"] == []
    assert any(i.rule_code == "DIMENSION_AMBIGUITY" for i in issues)


# ---------------------------------------------------------------- canonical key: no silent USD default
def test_canonical_key_differs_for_missing_vs_usd_currency():
    key_usd = Normalizer.compute_canonical_fact_key("i", "c", "p", "USD", "USD")
    key_none = Normalizer.compute_canonical_fact_key("i", "c", "p", "USD", "")
    assert key_usd != key_none


# ---------------------------------------------------------------- determinism / rerun safety
def test_rerun_with_identical_input_gives_identical_metric_ids_and_values():
    fl = [filing("a1", "10-K", dt.date(2025, 12, 31))]
    fs = [fact("x1", fl[0].filing_id, "us-gaap:Revenues", 100.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31))]
    _, m1, _, _ = run(fl, fs, history_years=1)
    _, m2, _, _ = run(fl, fs, history_years=1)
    assert [(m.metric_id, m.value) for m in m1] == [(m.metric_id, m.value) for m in m2]
