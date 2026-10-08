"""
Stage 8: FIE Handover Output Contract Generator (§20, §20.8)

Generates the authoritative FIE_COMPANY_STATE machine-readable JSON structure.
Strictly enforces honest handover boundaries:
- Fills proved metrics, events, accounting quality, data quality, and provenance.
- Excludes subjective investment thesis judgments (leaving trend interpretation to downstream FIE).
- Maintains strict distinction between NO MATERIAL CHANGE vs INSUFFICIENT EVIDENCE (§20.2).
- Emits handover status taxonomy: PASS | PASS WITH FLAGS | INSUFFICIENT DATA | FAIL.
"""

from typing import List, Dict, Any, Optional
from datetime import date
from pydantic import BaseModel, Field

from schema.models import Issuer, Filing, FactVersion, NormalizedMetric, MaterialEvent, HistoryDecision
from quality.harness import QualityReport


def _issue_text(issue) -> str:
    """
    Human-readable text for one QualityIssue. Different producers use different detail keys today
    (the harness's own 10 rules write details["message"]; the normalizer's issues write details["reason"]),
    so a single quality_report.issues list mixes both shapes. Falling back ensures the handover never
    carries a silent None placeholder for an issue that genuinely has a description, just under a
    different key; rule_code + issue_id is the last resort so an entry is never blank even then.
    """
    details = issue.details or {}
    return details.get("message") or details.get("reason") or f"{issue.rule_code} ({issue.issue_id})"


class FIECompanyState(BaseModel):
    issuer: str
    analysis_date: str
    history_window: int
    history_expanded: bool
    history_expansion_reasons: List[str] = Field(default_factory=list)

    financial_state: Dict[str, Any] = Field(default_factory=dict)
    material_changes: List[Dict[str, Any]] = Field(default_factory=list)
    accounting_quality: Dict[str, Any] = Field(default_factory=dict)
    material_events: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality: Dict[str, Any] = Field(default_factory=dict)

    confidence: str  # HIGH, MEDIUM, LOW
    handover_status: str  # PASS, PASS WITH FLAGS, INSUFFICIENT DATA, FAIL
    handover_blockers: List[str] = Field(default_factory=list)


class HandoverContractGenerator:
    def generate_contract(
        self,
        issuer: Issuer,
        as_of_date: date,
        history_decision: HistoryDecision,
        filings: List[Filing],
        metrics: List[NormalizedMetric],
        versions: List[FactVersion],
        events: List[MaterialEvent],
        quality_report: QualityReport
    ) -> FIECompanyState:
        """
        Constructs §20.8 FIE_COMPANY_STATE handover package.
        """
        # Determine Handover Status (§20.3)
        blockers = [i for i in quality_report.issues if i.severity == "BLOCKER"]
        warnings = [i for i in quality_report.issues if i.severity == "WARNING"]

        if blockers:
            status = "FAIL"
            confidence = "LOW"
            blocker_msgs = [b.details.get("message", b.rule_code) for b in blockers]
        elif quality_report.total_facts_evaluated == 0:
            status = "INSUFFICIENT DATA"
            confidence = "LOW"
            blocker_msgs = ["No authoritative quantitative facts extracted for evaluation window."]
        elif warnings:
            status = "PASS WITH FLAGS"
            confidence = "MEDIUM"
            blocker_msgs = []
        else:
            status = "PASS"
            confidence = "HIGH"
            blocker_msgs = []

        # Summarize proven financial metrics (FIE substrate)
        recent_metrics = {}
        for m in metrics:
            recent_metrics[f"{m.metric_code}_{m.period}"] = {
                "value": m.value,
                "unit": m.unit,
                "provenance_fact_ids": m.provenance_fact_ids,
                "comparability_status": m.comparability_status,
                "is_derived": m.is_derived
            }

        # financial_filings_selected: how many of THIS RUN'S selected filings (the window, not the
        # issuer's whole historical index) can carry financial statements at all -- 10-K/10-Q, not 8-K.
        # Used by the handover's filings_quarantined/financial_filings gate columns (team head's "Final
        # Ingestion Fix" blocker): those must count against the run's actual window, never the issuer's
        # full filing history, or an issuer with decades of 10-Ks on file would show a wildly inflated
        # count that has nothing to do with this run.
        _FINANCIAL_FORM_TYPES = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
        financial_filings_selected = sum(1 for f in filings if f.form_type in _FINANCIAL_FORM_TYPES)

        financial_state = {
            "metrics_summary": recent_metrics,
            "provenance_filings_count": len(filings),
            "financial_filings_selected": financial_filings_selected,
            "historical_baseline_years": history_decision.years_selected
        }

        # Restatement & Accounting Quality
        # Only version_reason == "RESTATED" means the VALUE actually changed between the original and the
        # preferred observation. "AMENDED" is set by the resolver when a later, amended filing reports the
        # SAME value as before (an amendment that did not change this particular fact) -- counting it here
        # overstated restatements for every amendment regardless of whether anything in it actually changed.
        restatement_versions = [v for v in versions if v.version_reason == "RESTATED"]
        has_policy_change = any(getattr(e, "event_type", None) == "ACCOUNTING_POLICY_CHANGE" for e in events)

        # Team head item 8: distinguish WHY a value changed. revision_category comes from the version
        # resolver's RESTATEMENT_OR_REVISION events (SCALE_DIFFERENCE, AMENDED_FILING, RECAST_COMPARATIVE,
        # RESTATEMENT); only the last is a value change the resolver could not explain mechanically.
        revision_categories: Dict[str, int] = {}
        for e in events:
            if getattr(e, "event_type", None) == "RESTATEMENT_OR_REVISION":
                category = (e.details or {}).get("revision_category", "UNCATEGORIZED")
                revision_categories[category] = revision_categories.get(category, 0) + 1
        genuine_restatements = revision_categories.get("RESTATEMENT", 0)

        accounting_quality = {
            "restatement_status": "RESTATED_VALUES_PRESENT" if restatement_versions else "NO_RESTATEMENTS_DETECTED",
            "restatements_count": len(restatement_versions),
            "restatements_by_category": revision_categories,
            "genuine_restatements_count": genuine_restatements,
            "accounting_policy_change": "DETECTED" if has_policy_change else "NONE_DETECTED",
            "comparability_status": "RESTATED" if genuine_restatements else ("RECLASSIFIED" if restatement_versions else "COMPARABLE"),
            "unusual_items": []
        }

        # Material Events stream summary
        event_list = [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "event_date": e.event_date.isoformat(),
                "severity": e.severity,
                "thesis_tags": e.thesis_tags,
                "details": e.details
            }
            for e in events
        ]

        # Data Quality summary
        # Step 7 (team head): reconciliation_status was a hardcoded constant, true even for a run that
        # checked zero facts or had its SEC reconciliation blocked. It now reflects what the harness's own
        # EXTRACTION_ACCURACY rule actually found against SEC companyfacts.
        extraction_blocker = any(i.rule_code == "EXTRACTION_ACCURACY" and i.severity == "BLOCKER" for i in quality_report.issues)
        if extraction_blocker:
            reconciliation_status = "MISMATCHES_FOUND"
        elif quality_report.reconciliation_total == 0:
            reconciliation_status = "UNVERIFIED"
        elif quality_report.reconciled_count == quality_report.reconciliation_total:
            reconciliation_status = "RECONCILED"
        else:
            reconciliation_status = "PARTIAL"

        data_quality = {
            "completeness": "COMPLETE" if not warnings else "COMPLETE_WITH_WARNINGS",
            "reconciliation_status": reconciliation_status,
            "reconciled_count": quality_report.reconciled_count,
            "reconciliation_total": quality_report.reconciliation_total,
            "missing_periods": [_issue_text(i) for i in quality_report.issues if i.rule_code == "MISSING_PERIOD"],
            "warnings": [_issue_text(i) for i in warnings]
        }

        # Material changes (Factual observation, withholding subjective investment conclusions per §20.2)
        material_changes = []
        if restatement_versions:
            material_changes.append({
                "change": "Historical accounting restatement detected",
                "direction": "REVISED",
                "supporting_evidence": [v.canonical_key for v in restatement_versions]
            })

        return FIECompanyState(
            issuer=issuer.ticker,
            analysis_date=as_of_date.isoformat(),
            history_window=history_decision.years_selected,
            history_expanded=(history_decision.years_selected > 5),
            history_expansion_reasons=history_decision.triggers,
            financial_state=financial_state,
            material_changes=material_changes,
            accounting_quality=accounting_quality,
            material_events=event_list,
            data_quality=data_quality,
            confidence=confidence,
            handover_status=status,
            handover_blockers=blocker_msgs
        )
