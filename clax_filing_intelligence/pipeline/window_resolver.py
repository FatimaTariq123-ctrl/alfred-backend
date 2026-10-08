"""
Stage 2: Window Resolver & Selective Retrieval Filter (§3.1, §4.2)

Resolves target analytical windows based on mode (normal=5yr, extended=10yr, forensic=full history)
and trigger flags. Reads policy threshold parameters from PolicyConfig (§3).
Enforces default selective retrieval rules:
- 5 annual 10-Ks (or 10-year expansion)
- 8 quarterly 10-Qs (~2.7 years)
- 24 months of material 8-Ks
- ALWAYS check 10-K/A and 10-Q/A amendments (even outside base window)
- DEF 14A and earnings releases excluded from first-pass window per §1.1 selective option.
"""

import calendar
from typing import List, Dict, Any, Optional
from datetime import date
from pydantic import BaseModel, Field

from config.policy import PolicyConfig, DEFAULT_POLICY
from schema.models import Filing


def _months_before(as_of_date: date, months: int) -> date:
    """Subtracts calendar months from as_of_date and clamps day to the last day of resulting month."""
    year = as_of_date.year
    month = as_of_date.month - months
    while month <= 0:
        month += 12
        year -= 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(as_of_date.day, max_day)
    return date(year, month, day)


class WindowResolverOutput(BaseModel):
    required_filings: List[Filing]
    analysis_mode: str
    years_selected: int
    start_date: date
    end_date: date
    target_fiscal_periods: List[str]
    expansion_reasons: List[str]
    policy_version: str


class WindowResolver:
    def __init__(self, policy: Optional[PolicyConfig] = None):
        self.policy = policy or DEFAULT_POLICY

    def resolve(
        self,
        issuer_id: str,
        market: str,
        as_of_date: date,
        analysis_mode: str = "normal",
        trigger_flags: Optional[List[str]] = None,
        all_filings: Optional[List[Filing]] = None
    ) -> WindowResolverOutput:
        """
        Calculates target analytical window and filters issuer filing inventory.
        Reads history window limits from policy configuration (§3).
        """
        mode_lower = (analysis_mode or "").lower().strip()
        if mode_lower not in {"normal", "extended", "forensic"}:
            raise ValueError(f"Unknown analysis mode: '{analysis_mode}'. Expected one of 'normal', 'extended', 'forensic'.")

        triggers = trigger_flags or []
        expansion_reasons: List[str] = []

        # Read history windows from product policy configuration (§3)
        if mode_lower == "forensic":
            # Forensic mode retrieves full available history (§2.1)
            years = self.policy.forensic_history_years
            expansion_reasons.append("Explicit forensic history analysis mode requested")
        elif mode_lower == "extended" or len(triggers) > 0:
            years = self.policy.extended_financial_history_years  # 10 years from policy config
            for t in triggers:
                expansion_reasons.append(f"Adaptive trigger activated: {t}")
        else:
            years = self.policy.base_financial_history_years  # 5 years from policy config

        # Note: start_date and end_date in WindowResolverOutput are informational metadata.
        # Selection of 10-K and 10-Q filings is count-based per v1.1 §4.2 (latest N 10-Ks and latest M 10-Qs),
        # while 8-K selection is month-based. Do NOT use start_date to filter 10-Ks or 10-Qs.
        start_date = date(as_of_date.year - years, 1, 1)
        end_date = as_of_date
        cutoff_8k = _months_before(as_of_date, self.policy.us_material_event_months)

        filings_pool = all_filings or []
        selected_filings: List[Filing] = []

        # Separate filings by financial form type (§4.2)
        ten_ks = [f for f in filings_pool if f.form_type == "10-K"]
        ten_qs = [f for f in filings_pool if f.form_type == "10-Q"]
        eight_ks = [f for f in filings_pool if f.form_type == "8-K"]
        amendments = [f for f in filings_pool if f.form_type in ["10-K/A", "10-Q/A"]]

        # 1. Select latest N fiscal-year 10-K filings (§4.2 Rule 1)
        sorted_10ks = sorted(ten_ks, key=lambda x: x.report_period, reverse=True)
        selected_10ks = sorted_10ks[:years]
        selected_filings.extend(selected_10ks)

        # 2. Select latest 8 quarters of 10-Q filings (§4.2 Rule 2)
        sorted_10qs = sorted(ten_qs, key=lambda x: x.report_period, reverse=True)
        selected_10qs = sorted_10qs[:self.policy.us_quarter_lookback]
        selected_filings.extend(selected_10qs)

        # 3. Select 8-K filings from material event lookback window (§4.2 Rule 3)
        selected_8ks = [f for f in eight_ks if f.filing_date >= cutoff_8k]
        selected_filings.extend(selected_8ks)

        # 4. Check 10-K/A and 10-Q/A amendments linked to selected base filings (§4.2 Rule 4, §1.1)
        if self.policy.amendments_always_check:
            selected_base_ids = {f.filing_id for f in selected_10ks + selected_10qs}
            selected_base_map = {(f.form_type, f.report_period): f.filing_id for f in selected_10ks + selected_10qs}

            selected_amendments = []
            for a in amendments:
                base_form = "10-K" if a.form_type == "10-K/A" else "10-Q"
                if a.base_filing_id:
                    if a.base_filing_id in selected_base_ids:
                        selected_amendments.append(a)
                else:
                    if (base_form, a.report_period) in selected_base_map:
                        selected_amendments.append(a)

            selected_filings.extend(selected_amendments)

        # Deduplicate while preserving order
        unique_filings_dict: Dict[str, Filing] = {}
        for f in selected_filings:
            unique_filings_dict[f.filing_id] = f

        final_selected = sorted(unique_filings_dict.values(), key=lambda x: x.filing_date, reverse=True)
        target_periods = [f"{f.form_type}:{f.report_period.isoformat()}" for f in final_selected]

        return WindowResolverOutput(
            required_filings=final_selected,
            analysis_mode=mode_lower,
            years_selected=years,
            start_date=start_date,
            end_date=end_date,
            target_fiscal_periods=target_periods,
            expansion_reasons=expansion_reasons,
            policy_version=self.policy.policy_version
        )
