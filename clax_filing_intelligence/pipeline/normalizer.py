"""
Stage 5: Normalizer & Canonical Fact Key Hashing (§6.1, §8)

Normalizes extracted facts:
1. Computes canonical fact key: hash(issuer_id | concept | period | unit | currency | dimensions)
2. Period labels come from each fact's OWN period dates and the issuer's fiscal-year-end, never from
   edgartools' fiscal_year/fiscal_period fields (those apply one fiscal-year-end day to every period in
   a filing, which mislabels comparative periods for 52/53-week filers).
3. The metric list and tag fallbacks come from policy.required_metrics (config/policy.py) — ONE source
   of truth shared with the parser; nothing here hardcodes a metric's tags.
4. 10-Q cumulative (YTD) duration facts are not dropped: when a metric's single quarter is not reported
   directly (common for cash-flow-statement items), it is derived from the cumulative figures.
5. The window is trimmed by COUNT (latest N fiscal years, latest M quarters), not by calendar cutoff.
6. Outflow metrics (capex, dividends, buybacks) are sign-adjusted only on the normalized_metric row;
   the stored fact_observation keeps the value exactly as the filer reported it (§1.2, §17).
7. Fails closed on ambiguous period/unit mappings -> emits QualityIssue (persisted by the harness, see
   quality/harness.py's external_issues parameter).
"""

import re
import json
import uuid
import hashlib
import logging
import calendar
from collections import Counter, defaultdict
from typing import List, Dict, Any, Tuple, Optional
from datetime import date

from config.policy import PolicyConfig, DEFAULT_POLICY
from schema.models import Issuer, Filing, FactObservation, NormalizedMetric, QualityIssue
from storage.db import DatabaseManager
from common.ids import stable_id

logger = logging.getLogger(__name__)

# Built from policy.required_metrics, "us-gaap:<tag>" -> metric_code, for every metric family policy defines.
# Kept as a module constant because pipeline/version_resolver.py imports it to recognize headline concepts;
# its shape (a flat dict of exact "taxonomy:LocalName" strings) is unchanged, only its coverage is now complete.
CONCEPT_TO_METRIC: Dict[str, str] = {
    f"us-gaap:{tag}": code
    for code, cfg in DEFAULT_POLICY.required_metrics.items()
    for tag in cfg.get("tags", [])
}

_FY_LABEL = re.compile(r"^FY(\d{4})$")
_Q_LABEL = re.compile(r"^Q([1-4])-(\d{4})(?: \(DERIVED\))?$")


def _fye_for_year(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _shift_months(d: date, months_back: int) -> date:
    """d shifted back by months_back whole months, day clamped to the target month's length."""
    total = (d.year * 12 + (d.month - 1)) - months_back
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _quarter_ends_for_year(fye: date) -> Dict[int, date]:
    """Q4 end = the fiscal year end itself; Q3/Q2/Q1 are 3/6/9 months before it."""
    return {4: fye, 3: _shift_months(fye, 3), 2: _shift_months(fye, 6), 1: _shift_months(fye, 9)}


class Normalizer:
    def __init__(self, policy: Optional[PolicyConfig] = None, db_manager: Optional[DatabaseManager] = None):
        self.policy = policy or DEFAULT_POLICY
        self.db = db_manager or DatabaseManager()

    @staticmethod
    def compute_canonical_fact_key(
        issuer_id: str,
        concept: str,
        period_str: str,
        unit: str,
        currency: str,
        dimensions: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Computes canonical fact key per §6.1:
        canonical_fact_key = hash(issuer_id | concept | period | unit | currency | dimensions)
        """
        dim_str = json.dumps(dimensions or {}, sort_keys=True)
        raw_key = f"{issuer_id}|{concept}|{period_str}|{unit}|{currency}|{dim_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ fiscal calendar

    def _fiscal_anchor(self, issuer: Issuer, filings: List[Filing]) -> Tuple[int, int]:
        """
        Issuer's fiscal-year-end as (month, day). From issuer.fiscal_year_end ("MMDD") when valid; otherwise
        the most common 10-K report_period month/day among the filings being normalized; otherwise Dec 31.
        """
        fye = issuer.fiscal_year_end if issuer else None
        if fye and len(fye) == 4 and fye.isdigit():
            month, day = int(fye[:2]), int(fye[2:])
            if 1 <= month <= 12 and 1 <= day <= 31:
                return month, day
        ten_ks = [f for f in filings if f.form_type in ("10-K", "10-K/A") and f.report_period]
        if ten_ks:
            common = Counter((f.report_period.month, f.report_period.day) for f in ten_ks).most_common(1)
            return common[0][0]
        return 12, 31

    def _nearest_fiscal_year_end(self, d: date, month: int, day: int) -> Tuple[date, int]:
        """Of the fiscal-year-end candidates for d.year-1 / d.year / d.year+1, the one nearest to d."""
        candidates = [( _fye_for_year(y, month, day), y) for y in (d.year - 1, d.year, d.year + 1)]
        fye, year = min(candidates, key=lambda c: abs((d - c[0]).days))
        return fye, year

    def _nearest_quarter(self, d: date, month: int, day: int, tolerance: int) -> Optional[Tuple[int, int]]:
        """Nearest (quarter 1-4, fiscal year) to date d, across fiscal years d.year-1..d.year+1, within tolerance."""
        best: Optional[Tuple[int, int, int]] = None  # (distance, quarter, year)
        for y in (d.year - 1, d.year, d.year + 1):
            fye = _fye_for_year(y, month, day)
            for q, q_end in _quarter_ends_for_year(fye).items():
                dist = abs((d - q_end).days)
                if best is None or dist < best[0]:
                    best = (dist, q, y)
        if best and best[0] <= tolerance:
            return best[1], best[2]
        return None

    def _locate_instant(self, fact: FactObservation, month: int, day: int, tolerance: int) -> Optional[str]:
        d = fact.instant_date
        if d is None:
            return None
        fye, year = self._nearest_fiscal_year_end(d, month, day)
        if abs((d - fye).days) <= tolerance:
            return f"FY{year}"
        q = self._nearest_quarter(d, month, day, tolerance)
        if q:
            qn, qy = q
            return f"FY{qy}" if qn == 4 else f"Q{qn}-{qy}"
        return None

    def _locate_duration(
        self, fact: FactObservation, month: int, day: int, tolerance: int
    ) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
        """Returns (label, ytd_marker). label is set for a fiscal year, a standalone quarter, or neither.
        ytd_marker is (2, year) or (3, year) for a 6-month / 9-month cumulative duration, used only to derive
        quarters later; it is never stored as a normalized_metric row by itself."""
        if not (fact.period_start and fact.period_end):
            return None, None
        duration_days = (fact.period_end - fact.period_start).days
        end = fact.period_end

        if 330 <= duration_days <= 400:
            fye, year = self._nearest_fiscal_year_end(end, month, day)
            if abs((end - fye).days) <= tolerance:
                return f"FY{year}", None
            return None, None

        if 75 <= duration_days <= 110:
            q = self._nearest_quarter(end, month, day, tolerance)
            if q:
                qn, qy = q
                return f"Q{qn}-{qy}", None
            return None, None

        if 160 <= duration_days <= 200:
            q = self._nearest_quarter(end, month, day, tolerance)
            if q and q[0] == 2:
                return None, (2, q[1])
            return None, None

        if 250 <= duration_days <= 290:
            q = self._nearest_quarter(end, month, day, tolerance)
            if q and q[0] == 3:
                return None, (3, q[1])
            return None, None

        return None, None

    # ------------------------------------------------------------------ main entry point

    def _flag_duplicate_value_anomalies(
        self,
        facts: List[FactObservation],
        filing_map: Dict[str, Filing],
        quality_issues: List[QualityIssue],
        run_id: str,
        tolerance_days: int
    ) -> int:
        """
        A filer-side XBRL tagging error, not a pipeline bug: within ONE filing, the same concept and
        dimension set sometimes carries two facts with the IDENTICAL value but different periods --
        a stale context accidentally reused from an older filing, still showing the current period's
        number. Left alone, the stale copy collides (same concept/period/dims) with the real historical
        fact from the earlier filing it was copied from, producing a false restatement/revision event.

        Detection is general, not issuer- or concept-specific: for duplicate same-value facts in one
        filing, if exactly one of them has a period matching that filing's own reporting period
        (within tolerance_days of filing.report_period) and the rest do not, the non-matching one(s)
        are flagged excluded_from_versioning (they are still saved exactly as extracted -- nothing is
        deleted or changed -- only skipped when version_resolver groups facts for comparison). When
        zero or more than one fact matches the filing's own period, nothing is flagged: an ambiguous
        case is reported, never guessed.
        """
        by_group: Dict[Tuple[str, str, str], List[FactObservation]] = defaultdict(list)
        for fact in facts:
            if fact.value is None or (fact.period_end is None and fact.instant_date is None):
                continue
            dims_key = json.dumps(fact.dimensions, sort_keys=True) if fact.dimensions else "{}"
            by_group[(fact.filing_id, fact.concept, dims_key)].append(fact)

        flagged = 0
        for (filing_id, concept, _dims_key), group in by_group.items():
            filing = filing_map.get(filing_id)
            if not filing or not filing.report_period or len(group) < 2:
                continue
            by_value: Dict[float, List[FactObservation]] = defaultdict(list)
            for fact in group:
                by_value[fact.value].append(fact)
            for value, same_value_facts in by_value.items():
                if len(same_value_facts) < 2:
                    continue
                if value == 0:
                    # Zero legitimately repeats across many periods in an equity-rollforward table
                    # (e.g. AdditionalPaidInCapitalMember showing $0 for several fiscal years running) --
                    # that is routine, not a sign of a mistagged context. Only a non-zero coincidence is
                    # a meaningful signal here.
                    continue

                def matches_filing_period(fact: FactObservation) -> bool:
                    end = fact.period_end or fact.instant_date
                    return end is not None and abs((filing.report_period - end).days) <= tolerance_days

                current = [f for f in same_value_facts if matches_filing_period(f)]
                stale = [f for f in same_value_facts if not matches_filing_period(f)]
                if len(current) != 1 or not stale:
                    continue  # ambiguous (0 or >1 matches the filing's own period) -- do not guess
                for fact in stale:
                    fact.excluded_from_versioning = True
                    fact.exclusion_reason = "DUPLICATE_VALUE_WRONG_PERIOD"
                    flagged += 1
                    period_label = f"{fact.period_start}..{fact.period_end}" if fact.period_start else str(fact.instant_date)
                    quality_issues.append(QualityIssue(
                        issue_id=f"issue_dupval_{uuid.uuid4().hex[:12]}",
                        run_id=run_id,
                        filing_id=filing_id,
                        fact_id=fact.fact_id,
                        rule_code="DUPLICATE_VALUE_WRONG_PERIOD",
                        severity="WARNING",
                        status="OPEN",
                        details={
                            "concept": concept,
                            "value": value,
                            "excluded_period": period_label,
                            "matching_current_period_fact_id": current[0].fact_id,
                            "reason": f"This filing also carries fact {current[0].fact_id} with the identical "
                                     f"value under this filing's own reporting period ({filing.report_period}). "
                                     f"The copy at {period_label} is very likely a stale/duplicate XBRL context "
                                     f"and was excluded from restatement/revision comparison (not deleted)."
                        }
                    ))
        if flagged:
            logger.warning(f"Normalizer flagged {flagged} fact(s) as duplicate-value-wrong-period anomalies "
                           f"(excluded from version comparison only).")
        return flagged

    def normalize(
        self,
        issuer: Issuer,
        filings: List[Filing],
        facts: List[FactObservation],
        run_id: str,
        history_years: Optional[int] = None
    ) -> Tuple[List[FactObservation], List[NormalizedMetric], List[QualityIssue]]:
        """
        Normalizes source facts, assigns canonical keys, builds normalized_metric series,
        and computes derived quarter metrics. history_years is the window the run actually selected
        (history_decision.years_selected: 5, 10, or 30); it defaults to the policy's base window.
        """
        normalized_facts: List[FactObservation] = []
        quality_issues: List[QualityIssue] = []
        filing_map = {f.filing_id: f for f in filings}
        history_years = history_years or self.policy.base_financial_history_years
        tolerance = self.policy.period_alignment_tolerance_days

        # 0. Flag intra-filing duplicate-value anomalies before anything else, so a stale copy never
        # enters canonical-key assignment and never collides with the real historical fact it was
        # accidentally duplicated from (team head blocker #3).
        self._flag_duplicate_value_anomalies(facts, filing_map, quality_issues, run_id, self.policy.recast_comparative_tolerance_days)

        # 1. Assign canonical fact keys; stored facts are never mutated (no sign change here: §1.2)
        seen_fact_keys = set()
        for fact in facts:
            filing = filing_map.get(fact.filing_id)
            if not filing:
                continue

            period_str = self._format_period_string(fact, filing)
            unit_norm = (fact.unit or "USD").upper()
            currency_norm = (fact.currency or "").upper()  # no silent USD default (§17): empty when truly unknown

            if fact.value is None and ("us-gaap" in fact.concept or "dei" in fact.concept):
                quality_issues.append(QualityIssue(
                    issue_id=f"issue_unit_{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    filing_id=filing.filing_id,
                    fact_id=fact.fact_id,
                    rule_code="UNIT_CONSISTENCY",
                    severity="WARNING",
                    status="OPEN",
                    details={"reason": f"Non-numeric value for concept {fact.concept}", "unit": fact.unit}
                ))

            fact.canonical_fact_key = self.compute_canonical_fact_key(
                issuer_id=issuer.issuer_id,
                concept=fact.concept,
                period_str=period_str,
                unit=unit_norm,
                currency=currency_norm,
                dimensions=fact.dimensions
            )

            dedup_key = (fact.canonical_fact_key, fact.filing_id)
            if dedup_key in seen_fact_keys:
                continue
            seen_fact_keys.add(dedup_key)
            normalized_facts.append(fact)

        self.db.save_fact_observations(normalized_facts)

        # 2. Map facts to (metric_code, label) using policy.required_metrics; collect YTD helpers separately.
        month, day = self._fiscal_anchor(issuer, filings)
        metric_candidates: Dict[str, Dict[str, List[FactObservation]]] = defaultdict(lambda: defaultdict(list))
        ytd_candidates: Dict[str, Dict[Tuple[int, int], List[FactObservation]]] = defaultdict(lambda: defaultdict(list))

        for fact in normalized_facts:
            taxonomy, _, local_name = fact.concept.partition(":")
            if taxonomy != "us-gaap":
                continue
            metric_code, period_type = None, None
            for code, cfg in self.policy.required_metrics.items():
                if local_name in cfg.get("tags", []):
                    metric_code, period_type = code, cfg["period_type"]
                    break
            if not metric_code:
                continue
            filing = filing_map.get(fact.filing_id)
            if not filing:
                continue

            if period_type == "instant":
                label = self._locate_instant(fact, month, day, tolerance)
                if label:
                    metric_candidates[metric_code][label].append(fact)
            else:
                label, ytd_marker = self._locate_duration(fact, month, day, tolerance)
                if label:
                    metric_candidates[metric_code][label].append(fact)
                elif ytd_marker:
                    ytd_candidates[metric_code][ytd_marker].append(fact)

        # 3. One NormalizedMetric per (metric_code, label): consolidated facts only, deterministic tie-break.
        normalized_metrics: List[NormalizedMetric] = []
        for metric_code, by_label in metric_candidates.items():
            tag_list = self.policy.required_metrics[metric_code]["tags"]
            for label, group_facts in by_label.items():
                metric = self._select_metric(issuer, metric_code, label, group_facts, filing_map, tag_list,
                                             quality_issues, run_id)
                if metric:
                    normalized_metrics.append(metric)

        ytd_metrics: Dict[str, Dict[Tuple[int, int], NormalizedMetric]] = defaultdict(dict)
        for metric_code, by_marker in ytd_candidates.items():
            tag_list = self.policy.required_metrics[metric_code]["tags"]
            for marker, group_facts in by_marker.items():
                m = self._select_metric(issuer, metric_code, f"_ytd{marker[0]}_{marker[1]}", group_facts,
                                        filing_map, tag_list, quality_issues, run_id, internal=True)
                if m:
                    ytd_metrics[metric_code][marker] = m

        # 4. Derive Q2/Q3/Q4 for every additive duration metric, only where the standalone quarter is missing.
        normalized_metrics.extend(self._derive_quarters(issuer, normalized_metrics, ytd_metrics))

        # 5. Window by count: keep the latest `history_years` FY labels and `us_quarter_lookback` quarter
        # labels per metric (direct and derived alike), independent of which calendar years they fall in.
        normalized_metrics = self._trim_window(normalized_metrics, history_years)

        # 6. Missing-period check over the metrics every filing is expected to report (policy-driven).
        self._check_missing_periods(issuer, filings, normalized_metrics, quality_issues, run_id, month, day, tolerance)

        self.db.save_normalized_metrics(normalized_metrics)

        logger.info(f"Normalized {len(normalized_facts)} facts into {len(normalized_metrics)} canonical "
                    f"normalized metrics (including derived quarters).")
        return normalized_facts, normalized_metrics, quality_issues

    # ------------------------------------------------------------------ helpers

    def _format_period_string(self, fact: FactObservation, filing: Filing) -> str:
        if fact.instant_date:
            return f"instant:{fact.instant_date.isoformat()}"
        if fact.period_start and fact.period_end:
            return f"{fact.period_start.isoformat()}_{fact.period_end.isoformat()}"
        return f"period:{filing.report_period.isoformat()}"

    @staticmethod
    def _fact_dimensions(fact: FactObservation) -> Optional[Dict[str, str]]:
        """fact.dimensions normalized to a dict, or None if it could not be parsed as one."""
        dims = fact.dimensions
        if not dims:
            return {}
        if isinstance(dims, str):
            try:
                dims = json.loads(dims)
            except Exception:
                return None
        return dims if isinstance(dims, dict) else None

    @classmethod
    def _is_consolidated_fact(cls, fact: FactObservation) -> bool:
        """Returns True if fact represents a consolidated company-wide figure (no dimensions)."""
        dims = cls._fact_dimensions(fact)
        return dims == {} if dims is not None else True

    @classmethod
    def _matches_dimension(cls, fact: FactObservation, target: Dict[str, str]) -> bool:
        """True if fact's dimensions are EXACTLY the given single-key dimension (not a superset, not a subset)."""
        dims = cls._fact_dimensions(fact)
        return dims == target

    def _select_metric(
        self,
        issuer: Issuer,
        metric_code: str,
        label: str,
        group_facts: List[FactObservation],
        filing_map: Dict[str, Filing],
        tag_list: List[str],
        quality_issues: List[QualityIssue],
        run_id: str,
        internal: bool = False
    ) -> Optional[NormalizedMetric]:
        """
        Picks one fact for (metric_code, label) among consolidated (non-dimensioned) candidates: the latest
        filing wins (amendment over base, higher accession last), and the policy tag order breaks ties within
        the same filing. provenance_fact_ids always starts with the chosen fact's id (§C3).
        internal=True builds a YTD helper used only for quarter derivation; it is never persisted or counted
        as a DIMENSION_AMBIGUITY issue on its own (the standalone-quarter/annual pass already reports that).
        """
        # A metric can name one exact dimension combination that still counts as "headline" even though the
        # fact is technically dimensioned (e.g. net income attributable to the parent, tagged under
        # StatementEquityComponentsAxis=ParentMember in the equity-statement rollforward rather than as a
        # plain undimensioned fact). When such a fact exists for this period, it is preferred over an
        # undimensioned fact for the same metric+period, because the undimensioned one is often the TOTAL
        # including noncontrolling interests, not the parent/owners' share this metric is meant to report.
        parent_dim = self.policy.required_metrics.get(metric_code, {}).get("attributable_to_parent_dimension")
        parent_matches = [f for f in group_facts if parent_dim and self._matches_dimension(f, parent_dim)]
        consolidated = parent_matches if parent_matches else [f for f in group_facts if self._is_consolidated_fact(f)]
        if not consolidated:
            if not internal:
                quality_issues.append(QualityIssue(
                    issue_id=f"issue_dim_{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    filing_id=group_facts[0].filing_id,
                    fact_id=group_facts[0].fact_id,
                    rule_code="DIMENSION_AMBIGUITY",
                    severity="WARNING",
                    status="OPEN",
                    details={"reason": f"Only dimensioned facts present for metric {metric_code} period {label}; headline metric omitted."}
                ))
            return None

        non_zero = [f for f in consolidated if f.value is not None and float(f.value) != 0.0]
        eligible = non_zero if non_zero else [f for f in consolidated if f.value is not None]
        if not eligible:
            eligible = consolidated

        def sort_key(f: FactObservation):
            fl = filing_map.get(f.filing_id)
            _, _, local_name = f.concept.partition(":")
            tag_rank = tag_list.index(local_name) if local_name in tag_list else len(tag_list)
            if not fl:
                return (date.min, False, "", -tag_rank)
            return (fl.filing_date, fl.amendment_flag, fl.accession_number, -tag_rank)

        chosen = max(eligible, key=sort_key)
        fact_ids = [chosen.fact_id] + [f.fact_id for f in consolidated if f.fact_id != chosen.fact_id]
        filing_ids = list(dict.fromkeys(f.filing_id for f in consolidated))

        value = chosen.value
        if metric_code in self.policy.outflow_metrics and value is not None:
            value = -abs(value)

        return NormalizedMetric(
            metric_id=stable_id("metric", issuer.issuer_id, metric_code, label, False),
            issuer_id=issuer.issuer_id,
            metric_code=metric_code,
            period=label,
            value=value,
            unit=chosen.unit or "USD",
            provenance_fact_ids=fact_ids,
            provenance_filing_ids=filing_ids,
            comparability_status="COMPARABLE",
            is_derived=False
        )

    def _make_derived(
        self, issuer: Issuer, metric_code: str, label: str, value: float, sources: List[NormalizedMetric]
    ) -> NormalizedMetric:
        """sources' values are already in their final sign convention (outflow sign, if any, was applied when
        each was selected), so the caller's `value` (a sum/difference of those) needs no further sign change."""
        fact_ids, filing_ids = [], []
        for s in sources:
            fact_ids.extend(s.provenance_fact_ids)
            filing_ids.extend(s.provenance_filing_ids)
        return NormalizedMetric(
            metric_id=stable_id("metric", issuer.issuer_id, metric_code, label, True),
            issuer_id=issuer.issuer_id,
            metric_code=metric_code,
            period=label,
            value=value,
            unit=sources[0].unit if sources else "USD",
            provenance_fact_ids=list(dict.fromkeys(fact_ids)),
            provenance_filing_ids=list(dict.fromkeys(filing_ids)),
            comparability_status="COMPARABLE",
            is_derived=True
        )

    def _derive_quarters(
        self,
        issuer: Issuer,
        normalized_metrics: List[NormalizedMetric],
        ytd_metrics: Dict[str, Dict[Tuple[int, int], NormalizedMetric]]
    ) -> List[NormalizedMetric]:
        """
        For every additive duration metric (policy.required_metrics period_type == duration, minus
        policy.non_additive_metrics): derive Q2 = YTD2 - Q1 and Q3 = YTD3 - YTD2 when the standalone quarter
        was not reported directly (the normal case for cash-flow-statement items), then Q4 = FY - (Q1+Q2+Q3)
        using whichever of Q1/Q2/Q3 are available, direct or derived.
        """
        by_metric_label: Dict[str, Dict[str, NormalizedMetric]] = defaultdict(dict)
        for m in normalized_metrics:
            by_metric_label[m.metric_code][m.period] = m

        derived: List[NormalizedMetric] = []
        for metric_code, cfg in self.policy.required_metrics.items():
            if cfg["period_type"] != "duration" or metric_code in self.policy.non_additive_metrics:
                continue
            labels = by_metric_label.get(metric_code, {})
            ytd = ytd_metrics.get(metric_code, {})

            years = {int(m.group(1)) for lbl in labels if (m := _FY_LABEL.match(lbl))}
            years |= {yr for (_, yr) in ytd}
            years |= {int(m.group(2)) for lbl in labels if (m := _Q_LABEL.match(lbl))}

            for yr in years:
                fy = labels.get(f"FY{yr}")
                q1 = labels.get(f"Q1-{yr}")

                q2 = labels.get(f"Q2-{yr}")
                if not q2 and q1 and (2, yr) in ytd:
                    ytd2 = ytd[(2, yr)]
                    if ytd2.value is not None and q1.value is not None:
                        q2 = self._make_derived(issuer, metric_code, f"Q2-{yr} (DERIVED)", ytd2.value - q1.value, [ytd2, q1])
                        derived.append(q2)

                q3 = labels.get(f"Q3-{yr}")
                if not q3 and (3, yr) in ytd:
                    ytd3 = ytd[(3, yr)]
                    ytd2_val, ytd2_sources = None, []
                    if (2, yr) in ytd:
                        ytd2_val, ytd2_sources = ytd[(2, yr)].value, [ytd[(2, yr)]]
                    elif q1 and q2:
                        ytd2_val, ytd2_sources = q1.value + q2.value, [q1, q2]
                    if ytd3.value is not None and ytd2_val is not None:
                        q3 = self._make_derived(issuer, metric_code, f"Q3-{yr} (DERIVED)", ytd3.value - ytd2_val, [ytd3] + ytd2_sources)
                        derived.append(q3)

                if fy and q1 and q2 and q3 and all(x.value is not None for x in (fy, q1, q2, q3)):
                    q4_val = fy.value - (q1.value + q2.value + q3.value)
                    derived.append(self._make_derived(issuer, metric_code, f"Q4-{yr} (DERIVED)", q4_val, [fy, q1, q2, q3]))
        return derived

    def _trim_window(self, metrics: List[NormalizedMetric], history_years: int) -> List[NormalizedMetric]:
        """Keeps, independently per metric_code, the latest `history_years` FY labels and the latest
        `policy.us_quarter_lookback` quarter labels (direct or derived count the same)."""
        by_metric: Dict[str, List[NormalizedMetric]] = defaultdict(list)
        for m in metrics:
            by_metric[m.metric_code].append(m)

        kept: List[NormalizedMetric] = []
        for metric_code, group in by_metric.items():
            fy_labels = sorted({m.period for m in group if _FY_LABEL.match(m.period)},
                               key=lambda p: int(_FY_LABEL.match(p).group(1)), reverse=True)
            q_labels = sorted({m.period for m in group if _Q_LABEL.match(m.period)},
                              key=lambda p: (int(_Q_LABEL.match(p).group(2)), int(_Q_LABEL.match(p).group(1))), reverse=True)
            keep = set(fy_labels[:history_years]) | set(q_labels[: self.policy.us_quarter_lookback])
            kept.extend(m for m in group if m.period in keep)
        return kept

    def _check_missing_periods(
        self,
        issuer: Issuer,
        filings: List[Filing],
        metrics: List[NormalizedMetric],
        quality_issues: List[QualityIssue],
        run_id: str,
        month: int,
        day: int,
        tolerance: int
    ):
        """For every selected 10-K/10-Q, the core metrics policy expects (REVENUE, NET_INCOME, OPERATING_INCOME,
        OPERATING_CASH_FLOW, CAPEX by default) should have a value for that filing's own report period. The
        label is computed straight from filing.report_period with the same fiscal calendar used everywhere
        else, not from "the first fact found for this filing" (which need not be representative)."""
        existing_keys = {(m.metric_code, m.period) for m in metrics}

        for filing in filings:
            if filing.form_type not in ("10-K", "10-K/A", "10-Q", "10-Q/A") or not filing.report_period:
                continue
            is_annual = filing.form_type in ("10-K", "10-K/A")
            fye, year = self._nearest_fiscal_year_end(filing.report_period, month, day)
            if is_annual:
                period_label = f"FY{year}"
            else:
                q = self._nearest_quarter(filing.report_period, month, day, tolerance)
                period_label = f"Q{q[0]}-{q[1]}" if q else f"Q{((filing.report_period.month - 1) // 3) + 1}-{filing.report_period.year}"

            for code in self.policy.core_expected_metrics:
                if (code, period_label) not in existing_keys:
                    quality_issues.append(QualityIssue(
                        issue_id=f"issue_missing_{uuid.uuid4().hex[:12]}",
                        run_id=run_id,
                        filing_id=filing.filing_id,
                        rule_code="MISSING_PERIOD",
                        severity="WARNING",
                        status="OPEN",
                        details={"metric_code": code, "period": period_label, "reason": "No fact found for expected metric and period."}
                    ))
