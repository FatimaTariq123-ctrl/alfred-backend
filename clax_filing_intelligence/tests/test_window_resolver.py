from datetime import date
import pytest

from config.policy import PolicyConfig
from schema.models import Filing
from pipeline.window_resolver import WindowResolver, _months_before


def make_filing(filing_id: str, form_type: str, f_date: date, r_period: date, base_id: str = None) -> Filing:
    return Filing(
        filing_id=filing_id,
        issuer_id="issuer_TEST",
        accession_number=f"acc_{filing_id}",
        form_type=form_type,
        filing_date=f_date,
        report_period=r_period,
        amendment_flag=form_type.endswith("/A"),
        base_filing_id=base_id,
        source_uri="http://test/uri",
        source_hash="hash123"
    )


def test_months_before_helper():
    assert _months_before(date(2026, 9, 30), 24) == date(2024, 9, 30)
    assert _months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert _months_before(date(2024, 3, 31), 1) == date(2024, 2, 29)


def test_10k_selection_counts():
    resolver = WindowResolver()
    filings = [
        make_filing(f"k_{yr}", "10-K", date(yr, 10, 15), date(yr, 9, 30))
        for yr in range(2010, 2022)  # 12 10-Ks
    ]
    out_normal = resolver.resolve("issuer_TEST", "US", date(2022, 10, 15), analysis_mode="normal", all_filings=filings)
    ks_normal = [f for f in out_normal.required_filings if f.form_type == "10-K"]
    assert len(ks_normal) == 5

    out_ext = resolver.resolve("issuer_TEST", "US", date(2022, 10, 15), analysis_mode="extended", all_filings=filings)
    ks_ext = [f for f in out_ext.required_filings if f.form_type == "10-K"]
    assert len(ks_ext) == 10


def test_10q_selection_counts():
    resolver = WindowResolver()
    filings = []
    idx = 1
    for yr in range(2020, 2024):
        for q_month, q_day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            filings.append(make_filing(f"q_{idx}", "10-Q", date(yr, q_month, 15), date(yr, q_month, q_day)))
            idx += 1
    # 16 10-Qs total
    assert len(filings) == 16

    out = resolver.resolve("issuer_TEST", "US", date(2023, 12, 31), analysis_mode="normal", all_filings=filings)
    qs = [f for f in out.required_filings if f.form_type == "10-Q"]
    assert len(qs) == 8


def test_8k_window_config():
    filings = [
        make_filing("8k_recent", "8-K", date(2026, 6, 1), date(2026, 6, 1)),
        make_filing("8k_mid", "8-K", date(2025, 3, 1), date(2025, 3, 1)),
        make_filing("8k_old", "8-K", date(2024, 7, 1), date(2024, 7, 1)),
    ]
    as_of = date(2026, 9, 30)

    res_default = WindowResolver(PolicyConfig(us_material_event_months=24))
    out_default = res_default.resolve("issuer_TEST", "US", as_of, all_filings=filings)
    count_24m = len([f for f in out_default.required_filings if f.form_type == "8-K"])

    res_12m = WindowResolver(PolicyConfig(us_material_event_months=12))
    out_12m = res_12m.resolve("issuer_TEST", "US", as_of, all_filings=filings)
    count_12m = len([f for f in out_12m.required_filings if f.form_type == "8-K"])

    assert count_12m < count_24m
    assert count_12m == 1  # only 2026-06-01 is >= 2025-09-30


def test_amendment_selection_rules():
    # Setup N 10-Ks: 2018 to 2022
    k_2022 = make_filing("k_2022", "10-K", date(2022, 10, 1), date(2022, 9, 30))
    k_2021 = make_filing("k_2021", "10-K", date(2021, 10, 1), date(2021, 9, 30))
    k_2020 = make_filing("k_2020", "10-K", date(2020, 10, 1), date(2020, 9, 30))
    k_2019 = make_filing("k_2019", "10-K", date(2019, 10, 1), date(2019, 9, 30))
    k_2018 = make_filing("k_2018", "10-K", date(2018, 10, 1), date(2018, 9, 30))
    # Unselected 10-K from 2010
    k_2010 = make_filing("k_2010", "10-K", date(2010, 10, 1), date(2010, 9, 30))

    # Amendment linked to selected base (k_2022)
    amd_linked_selected = make_filing("amd_linked_sel", "10-K/A", date(2023, 1, 1), date(2022, 9, 30), base_id="k_2022")
    # Amendment linked to unselected base (k_2010)
    amd_linked_unselected = make_filing("amd_linked_unsel", "10-K/A", date(2015, 1, 1), date(2010, 9, 30), base_id="k_2010")
    # Amendment without base_filing_id but matching selected 10-K (k_2021)
    amd_nobase_selected = make_filing("amd_nobase_sel", "10-K/A", date(2022, 5, 1), date(2021, 9, 30), base_id=None)
    # Amendment without base_filing_id matching unselected 10-K (k_2010)
    amd_nobase_unselected = make_filing("amd_nobase_unsel", "10-K/A", date(2012, 5, 1), date(2010, 9, 30), base_id=None)

    pool = [k_2022, k_2021, k_2020, k_2019, k_2018, k_2010, amd_linked_selected, amd_linked_unselected, amd_nobase_selected, amd_nobase_unselected]

    resolver = WindowResolver(PolicyConfig(amendments_always_check=True))
    out = resolver.resolve("issuer_TEST", "US", date(2022, 10, 1), analysis_mode="normal", all_filings=pool)

    req_ids = {f.filing_id for f in out.required_filings}
    assert "amd_linked_sel" in req_ids
    assert "amd_nobase_sel" in req_ids
    assert "amd_linked_unsel" not in req_ids
    assert "amd_nobase_unsel" not in req_ids

    # Policy amendments_always_check=False -> no amendments selected
    resolver_no_amd = WindowResolver(PolicyConfig(amendments_always_check=False))
    out_no_amd = resolver_no_amd.resolve("issuer_TEST", "US", date(2022, 10, 1), analysis_mode="normal", all_filings=pool)
    amds_out = [f for f in out_no_amd.required_filings if f.form_type.endswith("/A")]
    assert len(amds_out) == 0


def test_unknown_mode_raises_value_error():
    resolver = WindowResolver()
    with pytest.raises(ValueError) as exc_info:
        resolver.resolve("issuer_TEST", "US", date(2022, 10, 1), analysis_mode="invalid_mode")
    assert "invalid_mode" in str(exc_info.value)


def test_forensic_mode_uses_policy_years():
    policy = PolicyConfig(forensic_history_years=25)
    resolver = WindowResolver(policy)
    out = resolver.resolve("issuer_TEST", "US", date(2022, 10, 1), analysis_mode="forensic")
    assert out.years_selected == 25
