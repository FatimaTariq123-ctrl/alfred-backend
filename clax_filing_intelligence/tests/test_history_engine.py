from datetime import date
import pytest

from config.policy import PolicyConfig, DEFAULT_POLICY
from schema.models import Issuer
from adaptive.history_engine import AdaptiveHistoryEngine
from pipeline.window_resolver import WindowResolver


class FakeDB:
    def __init__(self):
        self.decisions = []
    def save_history_decision(self, decision):
        self.decisions.append(decision)


def make_issuer(ticker: str) -> Issuer:
    return Issuer(
        issuer_id=f"issuer_US_{ticker.upper()}",
        market="US",
        legal_name=f"{ticker} Corp",
        ticker=ticker,
        cik="0000123456",
        fiscal_year_end="1231"
    )


def test_history_engine_scenarios_and_resolver_agreement():
    fake_db = FakeDB()

    # Scenario 1: No triggers -> NORMAL / 5
    policy = PolicyConfig()
    engine = AdaptiveHistoryEngine(policy, fake_db)
    issuer = make_issuer("AAPL")
    dec1 = engine.evaluate_and_persist(issuer, "run_1", requested_mode="normal")
    assert dec1.mode == "NORMAL"
    assert dec1.years_selected == 5

    res1 = WindowResolver(policy).resolve(issuer.issuer_id, "US", date(2023, 1, 1), analysis_mode=dec1.mode.lower(), trigger_flags=dec1.triggers)
    assert res1.years_selected == dec1.years_selected

    # Scenario 2: Explicit trigger -> EXTENDED / 10
    dec2 = engine.evaluate_and_persist(issuer, "run_2", requested_mode="normal", explicit_triggers=["RESTATEMENT_DETECTED"])
    assert dec2.mode == "EXTENDED"
    assert dec2.years_selected == 10

    res2 = WindowResolver(policy).resolve(issuer.issuer_id, "US", date(2023, 1, 1), analysis_mode=dec2.mode.lower(), trigger_flags=dec2.triggers)
    assert res2.years_selected == dec2.years_selected

    # Scenario 3: Ticker in policy.cycle_sensitive_tickers (case insensitive) -> EXTENDED / 10
    issuer_cyclical = make_issuer("cat")  # lowercase "cat"
    dec3 = engine.evaluate_and_persist(issuer_cyclical, "run_3", requested_mode="normal")
    assert dec3.mode == "EXTENDED"
    assert dec3.years_selected == 10

    res3 = WindowResolver(policy).resolve(issuer_cyclical.issuer_id, "US", date(2023, 1, 1), analysis_mode=dec3.mode.lower(), trigger_flags=dec3.triggers)
    assert res3.years_selected == dec3.years_selected

    # Changing policy list changes result
    policy_custom = PolicyConfig(cycle_sensitive_tickers=["CUSTOM"])
    engine_custom = AdaptiveHistoryEngine(policy_custom, fake_db)
    dec_custom_cat = engine_custom.evaluate_and_persist(make_issuer("CAT"), "run_custom", requested_mode="normal")
    assert dec_custom_cat.mode == "NORMAL"  # CAT not in custom list!

    dec_custom_val = engine_custom.evaluate_and_persist(make_issuer("custom"), "run_custom2", requested_mode="normal")
    assert dec_custom_val.mode == "EXTENDED"  # custom in list!

    # Scenario 4: Forensic mode -> years == policy.forensic_history_years
    policy_forensic = PolicyConfig(forensic_history_years=35)
    engine_forensic = AdaptiveHistoryEngine(policy_forensic, fake_db)
    dec4 = engine_forensic.evaluate_and_persist(issuer, "run_4", requested_mode="forensic")
    assert dec4.mode == "FORENSIC"
    assert dec4.years_selected == 35

    res4 = WindowResolver(policy_forensic).resolve(issuer.issuer_id, "US", date(2023, 1, 1), analysis_mode=dec4.mode.lower(), trigger_flags=dec4.triggers)
    assert res4.years_selected == dec4.years_selected


def test_history_engine_unknown_mode_raises_value_error():
    engine = AdaptiveHistoryEngine(DEFAULT_POLICY, FakeDB())
    issuer = make_issuer("AAPL")
    with pytest.raises(ValueError) as exc_info:
        engine.evaluate_and_persist(issuer, "run_bad", requested_mode="unknown_mode")
    assert "unknown_mode" in str(exc_info.value)
