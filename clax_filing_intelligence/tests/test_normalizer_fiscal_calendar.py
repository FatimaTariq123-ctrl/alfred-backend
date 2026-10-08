"""
Step 4a/4b (normalizer rewrite): period labels come from each fact's OWN dates and the issuer's fiscal
calendar, never from edgartools' fiscal_year/fiscal_period fields, and the window is trimmed by COUNT,
not by a calendar-year cutoff. Pure logic, no database.
"""
import datetime as dt
import pytest

from pipeline.normalizer import Normalizer, _shift_months, _quarter_ends_for_year, _fye_for_year
from schema.models import Issuer, Filing, FactObservation


def norm():
    return Normalizer.__new__(Normalizer)  # avoid DatabaseManager() in __init__; only pure helpers are used


def test_shift_months_clamps_to_month_length():
    assert _shift_months(dt.date(2026, 3, 31), 1) == dt.date(2026, 2, 28)   # Feb has no 31st
    assert _shift_months(dt.date(2026, 3, 31), 3) == dt.date(2025, 12, 31)
    assert _shift_months(dt.date(2024, 2, 29), 12) == dt.date(2023, 2, 28)  # leap day, non-leap target year


def test_quarter_ends_for_december_fiscal_year():
    ends = _quarter_ends_for_year(dt.date(2024, 12, 31))
    assert ends == {4: dt.date(2024, 12, 31), 3: dt.date(2024, 9, 30), 2: dt.date(2024, 6, 30), 1: dt.date(2024, 3, 31)}


def test_quarter_ends_for_march_fiscal_year():
    ends = _quarter_ends_for_year(dt.date(2026, 3, 31))
    assert ends == {4: dt.date(2026, 3, 31), 3: dt.date(2025, 12, 31), 2: dt.date(2025, 9, 30), 1: dt.date(2025, 6, 30)}


# ---------------------------------------------------------------- fiscal anchor
def test_fiscal_anchor_from_issuer_field():
    n = norm()
    iss = Issuer(issuer_id="i", market="US", legal_name="x", ticker="X", fiscal_year_end="0331")
    assert n._fiscal_anchor(iss, []) == (3, 31)


def test_fiscal_anchor_falls_back_to_most_common_10k_report_period():
    n = norm()
    iss = Issuer(issuer_id="i", market="US", legal_name="x", ticker="X")  # no fiscal_year_end
    filings = [Filing(filing_id=f"f{i}", issuer_id="i", accession_number=f"a{i}", form_type="10-K",
                      filing_date=dt.date(2024, 2, 1), report_period=dt.date(2023, 12, 31), source_uri="u", source_hash="h")
               for i in range(3)]
    assert n._fiscal_anchor(iss, filings) == (12, 31)


def test_fiscal_anchor_default_december():
    n = norm()
    iss = Issuer(issuer_id="i", market="US", legal_name="x", ticker="X")
    assert n._fiscal_anchor(iss, []) == (12, 31)


# ---------------------------------------------------------------- date-based labeling, EXP-like (March FYE)
EXP_ANCHOR = (3, 31)
TOL = 15


def test_march_fye_instant_at_year_end_is_fy():
    n = norm()
    label = n._locate_instant(FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c",
                                              instant_date=dt.date(2026, 3, 31)), *EXP_ANCHOR, TOL)
    assert label == "FY2026"


def test_march_fye_quarter_instants():
    n = norm()
    cases = {dt.date(2025, 6, 28): "Q1-2026", dt.date(2025, 9, 27): "Q2-2026", dt.date(2025, 12, 28): "Q3-2026"}
    for d, expected in cases.items():
        label = n._locate_instant(FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c", instant_date=d), *EXP_ANCHOR, TOL)
        assert label == expected, f"{d} -> {label}, expected {expected}"


def test_march_fye_far_from_any_boundary_is_unlabeled():
    n = norm()
    label = n._locate_instant(FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c",
                                              instant_date=dt.date(2026, 2, 10)), *EXP_ANCHOR, TOL)
    assert label is None


def test_march_fye_annual_duration():
    n = norm()
    f = FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c",
                        period_start=dt.date(2025, 4, 1), period_end=dt.date(2026, 3, 31))
    label, ytd = n._locate_duration(f, *EXP_ANCHOR, TOL)
    assert label == "FY2026" and ytd is None


def test_march_fye_single_quarter_duration():
    n = norm()
    f = FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c",
                        period_start=dt.date(2026, 1, 1), period_end=dt.date(2026, 3, 31))
    label, ytd = n._locate_duration(f, *EXP_ANCHOR, TOL)
    assert label == "Q4-2026" and ytd is None


def test_march_fye_h1_and_9m_cumulative_are_ytd_markers_not_labels():
    n = norm()
    h1 = FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c",
                         period_start=dt.date(2025, 4, 1), period_end=dt.date(2025, 9, 27))
    label, ytd = n._locate_duration(h1, *EXP_ANCHOR, TOL)
    assert label is None and ytd == (2, 2026)
    nm = FactObservation(fact_id="y", canonical_fact_key="k2", filing_id="f", concept="c",
                         period_start=dt.date(2025, 4, 1), period_end=dt.date(2025, 12, 28))
    label2, ytd2 = n._locate_duration(nm, *EXP_ANCHOR, TOL)
    assert label2 is None and ytd2 == (3, 2026)


# ---------------------------------------------------------------- CF-like (December FYE)
CF_ANCHOR = (12, 31)


def test_december_fye_annual_and_quarters():
    n = norm()
    fy = FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c", instant_date=dt.date(2024, 12, 31))
    assert n._locate_instant(fy, *CF_ANCHOR, TOL) == "FY2024"
    q3 = FactObservation(fact_id="y", canonical_fact_key="k2", filing_id="f", concept="c", instant_date=dt.date(2024, 9, 30))
    assert n._locate_instant(q3, *CF_ANCHOR, TOL) == "Q3-2024"


def test_december_fye_does_not_mislabel_52_53_week_prior_year_like_edgartools_fiscal_year_field_would():
    """The old bug: edgartools applies one fiscal-year-end day to every period in a filing's facts, so a
    prior-year comparative fact can carry fact.fiscal_year of the CURRENT filing year. The new code never
    reads fact.fiscal_year at all, so it cannot inherit that mistake: the label always comes from the fact's
    own period_end, which is what correctly identifies the comparative year here."""
    n = norm()
    prior_year_comparative = FactObservation(fact_id="x", canonical_fact_key="k", filing_id="f", concept="c",
                                             period_start=dt.date(2022, 1, 1), period_end=dt.date(2022, 12, 31),
                                             fiscal_year="2023", fiscal_period="FY")  # edgartools' (wrong) labels
    label, _ = n._locate_duration(prior_year_comparative, *CF_ANCHOR, TOL)
    assert label == "FY2022"   # the date wins, not fiscal_year=2023


# ---------------------------------------------------------------- window by count (not calendar cutoff)
def make_filing(acc, form, report_period, filing_date=None):
    return Filing(filing_id=f"filing_{acc}", issuer_id="issuer_US_CF", accession_number=acc, form_type=form,
                 filing_date=filing_date or report_period, report_period=report_period, source_uri="u", source_hash="h")


def make_fact(fid, filing_id, concept, value, start=None, end=None, instant=None):
    return FactObservation(fact_id=fid, canonical_fact_key=f"k_{fid}", filing_id=filing_id, concept=concept, value=value,
                           unit="USD", currency="USD", period_start=start, period_end=end, instant_date=instant)


class FakeDB:
    def save_fact_observations(self, facts):
        return facts

    def save_normalized_metrics(self, metrics):
        return None


ISSUER_CF = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF", ticker="CF", cik="1324404", fiscal_year_end="1231")


def test_window_keeps_latest_n_fiscal_years_by_count_not_calendar_cutoff():
    """Five 10-Ks for FY2021..FY2025 (CF's real situation: FY2021 should NOT be dropped just because it is
    the oldest of exactly 5 years; this is the specific bug CF showed: only 4 of 5 years were delivered)."""
    n = Normalizer(db_manager=FakeDB())
    filings, facts = [], []
    for i, yr in enumerate([2021, 2022, 2023, 2024, 2025]):
        f = make_filing(f"a{i}", "10-K", dt.date(yr, 12, 31))
        filings.append(f)
        facts.append(make_fact(f"rev{i}", f.filing_id, "us-gaap:Revenues", 1000.0 + yr, start=dt.date(yr, 1, 1), end=dt.date(yr, 12, 31)))
    _, metrics, _ = n.normalize(issuer=ISSUER_CF, filings=filings, facts=facts, run_id="r1", history_years=5)
    fy_periods = sorted(m.period for m in metrics if m.metric_code == "REVENUE")
    assert fy_periods == ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]


def test_window_trims_to_exactly_n_when_more_are_available():
    n = Normalizer(db_manager=FakeDB())
    filings, facts = [], []
    for i, yr in enumerate(range(2018, 2026)):  # 8 years of data
        f = make_filing(f"a{i}", "10-K", dt.date(yr, 12, 31))
        filings.append(f)
        facts.append(make_fact(f"rev{i}", f.filing_id, "us-gaap:Revenues", 1000.0, start=dt.date(yr, 1, 1), end=dt.date(yr, 12, 31)))
    _, metrics, _ = n.normalize(issuer=ISSUER_CF, filings=filings, facts=facts, run_id="r1", history_years=5)
    fy_periods = sorted(m.period for m in metrics if m.metric_code == "REVENUE")
    assert fy_periods == ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]  # latest 5, not the oldest or a calendar slice


def test_history_years_defaults_to_policy_when_not_given():
    n = Normalizer(db_manager=FakeDB())
    filings, facts = [], []
    for i, yr in enumerate(range(2015, 2026)):
        f = make_filing(f"a{i}", "10-K", dt.date(yr, 12, 31))
        filings.append(f)
        facts.append(make_fact(f"rev{i}", f.filing_id, "us-gaap:Revenues", 1000.0, start=dt.date(yr, 1, 1), end=dt.date(yr, 12, 31)))
    _, metrics, _ = n.normalize(issuer=ISSUER_CF, filings=filings, facts=facts, run_id="r1")  # no history_years kwarg
    fy_periods = {m.period for m in metrics if m.metric_code == "REVENUE"}
    assert len(fy_periods) == n.policy.base_financial_history_years


def test_window_keeps_latest_m_quarters_by_count():
    n = Normalizer(db_manager=FakeDB())
    filings, facts = [], []
    quarters = [(dt.date(yr, m, 1), dt.date(yr, m, 1).replace(day=28)) for yr in (2024, 2025) for m in (3, 6, 9, 12)]
    for i, (qs, qe) in enumerate(quarters):
        f = make_filing(f"q{i}", "10-Q", qe, filing_date=qe)
        filings.append(f)
        facts.append(make_fact(f"rev{i}", f.filing_id, "us-gaap:Revenues", 100.0 + i, start=qs, end=qe))
    _, metrics, _ = n.normalize(issuer=ISSUER_CF, filings=filings, facts=facts, run_id="r1", history_years=5)
    q_periods = [m.period for m in metrics if m.metric_code == "REVENUE" and "Q" in m.period]
    assert len(q_periods) <= n.policy.us_quarter_lookback
