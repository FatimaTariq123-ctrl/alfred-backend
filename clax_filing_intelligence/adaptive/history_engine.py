"""
Adaptive History Decision Engine (§3.2, §10)

Evaluates expansion triggers and determines whether the analytical window
should remain at the standard 5-year baseline or expand to 10 years or forensic mode.
Persists HistoryDecision records with explainable, reproducible trigger reasons.
"""

import uuid
import logging
from typing import List, Tuple, Optional
from datetime import date

from config.policy import PolicyConfig, DEFAULT_POLICY
from schema.models import Issuer, Filing, MaterialEvent, HistoryDecision
from storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class AdaptiveHistoryEngine:
    def __init__(self, policy: Optional[PolicyConfig] = None, db_manager: Optional[DatabaseManager] = None):
        self.policy = policy or DEFAULT_POLICY
        self.db = db_manager or DatabaseManager()

    def evaluate_and_persist(
        self,
        issuer: Issuer,
        run_id: str,
        requested_mode: str = "normal",
        explicit_triggers: Optional[List[str]] = None,
        events: Optional[List[MaterialEvent]] = None
    ) -> HistoryDecision:
        """
        Evaluates triggers and records explainable expansion decision (§10).
        """
        mode_lower = (requested_mode or "").lower().strip()
        if mode_lower not in {"normal", "extended", "forensic"}:
            raise ValueError(f"Unknown analysis mode: '{requested_mode}'. Expected one of 'normal', 'extended', 'forensic'.")

        triggers: List[str] = list(explicit_triggers or [])
        events_list = events or []

        # Automatic trigger evaluation based on material events (§3.2)
        restatement_events = [e for e in events_list if e.event_type in ["RESTATEMENT_OR_REVISION", "ACCOUNTING_POLICY_CHANGE"]]
        if restatement_events:
            triggers.append("Accounting comparability trigger: Material restatement or accounting policy change detected")

        cyclical = [t.upper() for t in (self.policy.cycle_sensitive_tickers or [])]
        if issuer.ticker.upper() in cyclical:
            triggers.append("Cycle sensitivity trigger: Issuer identified as cyclical commodity/capital-goods company")

        # Determine target window years (§10 pseudocode)
        if mode_lower == "forensic":
            selected_mode = "FORENSIC"
            years = self.policy.forensic_history_years
        elif mode_lower == "extended" or len(triggers) > 0:
            selected_mode = "EXTENDED"
            years = self.policy.extended_financial_history_years  # 10 years
        else:
            selected_mode = "NORMAL"
            years = self.policy.base_financial_history_years  # 5 years

        decision = HistoryDecision(
            decision_id=f"dec_{uuid.uuid4().hex[:12]}",
            issuer_id=issuer.issuer_id,
            run_id=run_id,
            mode=selected_mode,
            years_selected=years,
            triggers=triggers,
            policy_version=self.policy.policy_version
        )

        self.db.save_history_decision(decision)
        logger.info(f"Adaptive history decision for {issuer.ticker}: Mode={selected_mode}, Years={years}, Triggers={triggers}")
        return decision
