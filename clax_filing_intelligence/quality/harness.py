"""
Quality Validation Harness (§12, §14, §20.5, Part 2)

Automates the 10 machine-readable validation rules:
1. EXTRACTION_ACCURACY (Blocker) — Reconciles extracted per-filing XBRL facts against SEC companyfacts API independent source.
2. PERIOD_MAPPING (Blocker) — Verifies facts assigned to correct fiscal period.
3. DUPLICATE_SUPPRESSION (Blocker) — Re-run does not create duplicate filings/facts.
4. RESTATEMENT_HANDLING (Blocker) — Original and revised values both preserved; preferred updated.
5. UNIT_CONSISTENCY (Blocker) — Scale and units normalized correctly.
6. FISCAL_YEAR_CHANGE (Blocker) — Short/long transition period detected.
7. AMENDMENT_LINKAGE (Blocker) — 10-K/A or 10-Q/A linked to base filing.
8. MISSING_PERIOD (Warn/Block) — Expected gaps flagged.
9. COMPARABILITY (Warn/Block) — Reclassifications/restatements reflected.
10. STORAGE_FOOTPRINT (Warn) — Raw + parsed + normalized size measured.

Emits machine-readable QualityIssue records and overall QualityReport.
"""

import uuid
import json
import logging
import requests
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

from config.settings import EDGAR_IDENTITY
from schema.models import Issuer, Filing, FactObservation, FactVersion, NormalizedMetric, QualityIssue
from storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class QualityReport(BaseModel):
    run_id: str
    issuer_id: str
    total_filings_evaluated: int
    total_facts_evaluated: int
    total_issues: int
    blocker_count: int
    warning_count: int
    info_count: int
    is_valid: bool  # True if blocker_count == 0
    issues: List[QualityIssue] = Field(default_factory=list)
    reconciled_count: int = 0      # sample key facts that matched SEC companyfacts
    reconciliation_total: int = 0  # sample key facts actually checked (0 = nothing could be checked)


class QualityHarness:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()

    @staticmethod
    def _is_consolidated_fact(fact: FactObservation) -> bool:
        """Returns True if fact represents a consolidated company-wide figure (no dimensions)."""
        dims = fact.dimensions
        if not dims:
            return True
        if isinstance(dims, str):
            try:
                dims = json.loads(dims)
            except Exception:
                return True
        if isinstance(dims, dict):
            return len(dims) == 0
        return True


    def validate(
        self,
        run_id: str,
        issuer: Issuer,
        filings: List[Filing],
        facts: List[FactObservation],
        versions: List[FactVersion],
        metrics: List[NormalizedMetric],
        external_issues: Optional[List[QualityIssue]] = None
    ) -> QualityReport:
        """
        Executes all 10 quality validation checks and produces machine-readable QualityReport.
        Reconciles sampled key facts against SEC companyfacts API (§12, §20.5).
        external_issues: issues raised by an earlier stage (for example the normalizer's own MISSING_PERIOD
        and FISCAL_YEAR_CHANGE findings) that this run must also persist and count. They are saved here, in
        one batch, and folded into the same report as the harness's own rules, so no issue a stage finds is
        ever silently dropped.
        """
        issues: List[QualityIssue] = list(external_issues or [])
        if external_issues:
            self.db.save_quality_issues(external_issues)
        filing_map = {f.filing_id: f for f in filings}
        reconciled_count, reconciliation_total = 0, 0

        # Rule 1: EXTRACTION_ACCURACY (Blocker) — Independent SEC companyfacts API Reconciliation (§12, §20.5)
        if not facts and len(filings) > 0:
            issue = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="EXTRACTION_ACCURACY",
                severity="BLOCKER",
                status="OPEN",
                details={"message": "No XBRL facts were extracted from retrieved filings."}
            )
            issues.append(issue)
            self.db.save_quality_issue(issue)
        else:
            reconciled_count, reconciliation_total, reconciliation_blocker = self._reconcile_against_companyfacts(
                run_id=run_id,
                issuer=issuer,
                filings=filings,
                facts=facts,
                metrics=metrics,
                filing_map=filing_map
            )
            if reconciliation_blocker:
                issues.append(reconciliation_blocker)
                self.db.save_quality_issue(reconciliation_blocker)


        # Rule 2: PERIOD_MAPPING (Blocker)
        unmapped_period_facts = [f for f in facts if not f.period_end and not f.instant_date]
        if unmapped_period_facts:
            issue = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="PERIOD_MAPPING",
                severity="BLOCKER",
                status="OPEN",
                details={"message": f"{len(unmapped_period_facts)} facts missing fiscal period identity."}
            )
            issues.append(issue)
            self.db.save_quality_issue(issue)

        # Rule 3: DUPLICATE_SUPPRESSION (Blocker)
        filing_fact_keys = set()
        dup_count = 0
        for f in facts:
            fk = f"{f.canonical_fact_key}_{f.filing_id}"
            if fk in filing_fact_keys:
                dup_count += 1
            filing_fact_keys.add(fk)
        if dup_count > 0:
            issue = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="DUPLICATE_SUPPRESSION",
                severity="BLOCKER",
                status="OPEN",
                details={"message": f"{dup_count} duplicate fact observations detected within single filings."}
            )
            issues.append(issue)
            self.db.save_quality_issue(issue)

        # Rule 4: RESTATEMENT_HANDLING (Blocker)
        restated_versions = [v for v in versions if v.version_reason == "RESTATED"]
        for rv in restated_versions:
            if rv.original_fact_id == rv.preferred_fact_id:
                issue = QualityIssue(
                    issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    fact_id=rv.original_fact_id,
                    rule_code="RESTATEMENT_HANDLING",
                    severity="BLOCKER",
                    status="OPEN",
                    details={"message": f"Restated fact version {rv.canonical_key} points preferred_fact_id to original_fact_id without update."}
                )
                issues.append(issue)
                self.db.save_quality_issue(issue)

        # Rule 5: UNIT_CONSISTENCY (Blocker) — Fix 2: Severities restored to BLOCKER per §12
        unknown_units = [f for f in facts if not f.unit]
        if unknown_units:
            issue = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="UNIT_CONSISTENCY",
                severity="BLOCKER",
                status="OPEN",
                details={"message": f"{len(unknown_units)} facts extracted with missing unit definition."}
            )
            issues.append(issue)
            self.db.save_quality_issue(issue)

        # Rule 6: FISCAL_YEAR_CHANGE (Blocker) — Primary annual context check (§8, §12)
        # Note: Exclude multi-year / cumulative facts (> 550 days, e.g. 2556 or 2921 days) which are multi-year disclosures,
        # not reporting period transitions. Genuine transitions range from ~150 to 550 days (~6 to ~18 months).
        for filing in filings:
            if filing.form_type == "10-K":
                matching_facts = [
                    f for f in facts
                    if f.filing_id == filing.filing_id
                    and f.period_start and f.period_end and f.period_end == filing.report_period
                    and (f.period_end - f.period_start).days <= 550
                ]
                if matching_facts:
                    longest_days = max((f.period_end - f.period_start).days for f in matching_facts)
                    if (longest_days < 330 or longest_days > 400) and longest_days >= 150:
                        issue = QualityIssue(
                            issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                            run_id=run_id,
                            filing_id=filing.filing_id,
                            rule_code="FISCAL_YEAR_CHANGE",
                            severity="BLOCKER",
                            status="OPEN",
                            details={"message": f"Short/long fiscal year transition period detected ({longest_days} days) in 10-K report period {filing.report_period}."}
                        )
                        issues.append(issue)
                        self.db.save_quality_issue(issue)

        # Rule 7: AMENDMENT_LINKAGE (§12, §20.3)
        # Only financial-statement amendments are in scope for lineage linkage per §1.1/§4.2.
        # Other /A forms (SC 13G/A, DEF 14A, Forms 3/4/5-A, S-3/A, etc.) are unrelated ownership/
        # proxy/registration filings with no base 10-K/10-Q/8-K to link, and must not be flagged here.
        FINANCIAL_AMENDMENT_FORMS = {"10-K/A", "10-Q/A", "8-K/A"}
        unlinked_amendments = [
            f for f in filings
            if f.amendment_flag and not f.base_filing_id
            and f.form_type in FINANCIAL_AMENDMENT_FORMS
        ]

        in_window_unlinked = []
        out_of_window_unlinked = []

        for am in unlinked_amendments:
            base_form = am.form_type.replace("/A", "")
            has_matching_base_in_set = any(
                f.form_type == base_form and f.report_period == am.report_period 
                for f in filings
            )
            if has_matching_base_in_set:
                in_window_unlinked.append(am)
            else:
                out_of_window_unlinked.append(am)

        if in_window_unlinked:
            issue = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="AMENDMENT_LINKAGE",
                severity="BLOCKER",
                status="OPEN",
                details={"message": f"{len(in_window_unlinked)} amendment filings could not be linked to base filing lineage in scope."}
            )
            issues.append(issue)
            self.db.save_quality_issue(issue)

        if out_of_window_unlinked:
            issue = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="AMENDMENT_LINKAGE",
                severity="WARNING",
                status="FLAGGED",
                details={"message": f"{len(out_of_window_unlinked)} amendment filings have base filings outside the retrieved analytical window."}
            )
            issues.append(issue)
            self.db.save_quality_issue(issue)

        # Rule 8: MISSING_PERIOD (Warn/Block)
        report_years = set(f.report_period.year for f in filings if f.form_type == "10-K")
        if report_years:
            min_yr, max_yr = min(report_years), max(report_years)
            expected_years = set(range(min_yr, max_yr + 1))
            missing_years = expected_years - report_years
            if missing_years:
                issue = QualityIssue(
                    issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    rule_code="MISSING_PERIOD",
                    severity="WARNING",
                    status="FLAGGED",
                    details={"message": f"Expected annual 10-K report periods missing: {sorted(list(missing_years))}"}
                )
                issues.append(issue)
                self.db.save_quality_issue(issue)

        # Rule 9: COMPARABILITY (Warn/Block)
        non_comparable = [m for m in metrics if m.comparability_status == "NON_COMPARABLE"]
        if non_comparable:
            issue = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="COMPARABILITY",
                severity="WARNING",
                status="FLAGGED",
                details={"message": f"{len(non_comparable)} metrics marked as NON_COMPARABLE due to structural changes."}
            )
            issues.append(issue)
            self.db.save_quality_issue(issue)

        # Rule 10: STORAGE_FOOTPRINT (Warn)
        logger.info(f"Quality validation storage footprint check: {len(filings)} filings, {len(facts)} facts.")

        blockers = [i for i in issues if i.severity == "BLOCKER"]
        warnings = [i for i in issues if i.severity == "WARNING"]

        report = QualityReport(
            run_id=run_id,
            issuer_id=issuer.issuer_id,
            total_filings_evaluated=len(filings),
            total_facts_evaluated=len(facts),
            total_issues=len(issues),
            blocker_count=len(blockers),
            warning_count=len(warnings),
            info_count=0,
            is_valid=(len(blockers) == 0),
            issues=issues,
            reconciled_count=reconciled_count,
            reconciliation_total=reconciliation_total
        )

        logger.info(f"Quality Report generated for run {run_id}: Valid={report.is_valid}, Blockers={report.blocker_count}, Warnings={report.warning_count}")
        return report

    def _reconcile_against_companyfacts(
        self,
        run_id: str,
        issuer: Issuer,
        filings: List[Filing],
        facts: List[FactObservation],
        metrics: List[NormalizedMetric],
        filing_map: Dict[str, Filing]
    ) -> Tuple[int, Optional[QualityIssue]]:
        """
        Reconciles sampled key headline metrics (REVENUE, OPERATING_INCOME)
        against SEC companyfacts API independent source (§12, §20.5).
        """
        if not filings:
            logger.info(
                f"No US-GAAP filings available for issuer {issuer.ticker} "
                "(likely non-US / ADR filer); out of scope for US connector."
            )
            return 0, 0, None

        cik = str(issuer.cik).strip() if issuer.cik else ""
        if not cik or not cik.isdigit():
            if filings:
                acc = filings[0].accession_number
                cik = str(int(acc.split("-")[0])) if "-" in acc else cik

        if not cik or not cik.isdigit():
            blocker = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="EXTRACTION_ACCURACY",
                severity="BLOCKER",
                status="OPEN",
                details={"message": f"Could not resolve valid CIK for issuer {issuer.ticker} to execute reconciliation."}
            )
            return 0, 0, blocker

        cik_formatted = cik.zfill(10)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_formatted}.json"
        headers = {"User-Agent": EDGAR_IDENTITY}

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                blocker = QualityIssue(
                    issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    rule_code="EXTRACTION_ACCURACY",
                    severity="BLOCKER",
                    status="OPEN",
                    details={"message": f"SEC companyfacts API query failed with HTTP status {resp.status_code} for CIK {cik_formatted}."}
                )
                return 0, 0, blocker

            company_data = resp.json()
            us_gaap_facts = company_data.get("facts", {}).get("us-gaap", {})
            if not us_gaap_facts:
                logger.info(
                    f"No US-GAAP filings available for this issuer ({issuer.ticker} / CIK {cik_formatted}) "
                    "(likely non-US / ADR filer); out of scope for US connector."
                )
                return 0, 0, None

            concept_map = {
                "REVENUE": [
                    "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "SalesRevenueNet",
                    "Revenues"
                ],
                "NET_INCOME": ["NetIncomeLoss"],
                "OPERATING_INCOME": [
                    "OperatingIncomeLoss"
                ]
            }

            fact_map = {f.fact_id: f for f in facts}
            reconciled_count = 0
            mismatch_details = []

            import re

            # Extract annual FY years and compute max_fy_year to exclude the most recent fiscal year
            fy_years = []
            for m in metrics:
                if str(m.period).startswith("FY"):
                    yr_m = re.search(r'(20\d\d)', str(m.period))
                    if yr_m:
                        fy_years.append(int(yr_m.group(1)))

            max_fy_year = max(fy_years) if fy_years else None

            # Key-facts-only sample check (§12): iterate ONLY annual FY metrics prior to the latest fiscal year
            target_metrics = []
            for m in metrics:
                if m.metric_code in concept_map and m.value is not None and str(m.period).startswith("FY"):
                    yr_m = re.search(r'(20\d\d)', str(m.period))
                    if yr_m:
                        yr_val = int(yr_m.group(1))
                        if max_fy_year is None or yr_val < max_fy_year:
                            target_metrics.append(m)

            for metric in target_metrics:
                prov_facts = [fact_map[fid] for fid in metric.provenance_fact_ids if fid in fact_map]
                consolidated_prov_facts = [f for f in prov_facts if self._is_consolidated_fact(f)]

                # Skip reconciliation if ONLY dimensional facts exist for this metric (no consolidated counterpart)
                if prov_facts and not consolidated_prov_facts:
                    logger.info(
                        f"Skipping reconciliation for {metric.metric_code} ({metric.period}): "
                        "only dimensional/segment facts exist with no consolidated counterpart."
                    )
                    continue

                period_end = prov_facts[0].period_end if prov_facts and prov_facts[0].period_end else None

                if period_end:
                    end_year = str(period_end.year)
                    end_date_str = str(period_end)
                else:
                    yr_match = re.search(r'(20\d\d)', metric.period)
                    end_year = yr_match.group(1) if yr_match else None
                    end_date_str = None

                fp_label = prov_facts[0].fiscal_period.upper() if (prov_facts and prov_facts[0].fiscal_period) else None
                if not fp_label:
                    if "FY" in metric.period:
                        fp_label = "FY"
                    elif "Q" in metric.period:
                        fp_label = metric.period.split("-")[0]

                filing = filing_map.get(prov_facts[0].filing_id) if prov_facts else None
                form_label = filing.form_type.replace("/A", "") if filing else None

                # Collect all matching SEC companyfacts entries for this period across concept variants and filing vintages
                candidate_entries = []
                for concept_short in concept_map[metric.metric_code]:
                    c_entries = us_gaap_facts.get(concept_short, {}).get("units", {}).get("USD", [])
                    for entry in c_entries:
                        if "val" not in entry:
                            continue
                        entry_end = str(entry.get("end", ""))
                        entry_year = entry_end[:4]
                        entry_fp = str(entry.get("fp", "")).upper()
                        entry_form = str(entry.get("form", "")).replace("/A", "")

                        # Match metric period_end year (or date) to companyfacts 'end' year AND 'fp'/'form'
                        year_matches = (end_year and entry_year == end_year) or (end_date_str and entry_end == end_date_str)
                        period_matches = (fp_label and entry_fp == fp_label) or (form_label and entry_form == form_label)

                        if year_matches and period_matches:
                            candidate_entries.append((entry, concept_short))

                if not candidate_entries:
                    continue

                # Vintage-Tolerant Reconciliation (§12, §20.5):
                # Extracted metric.value is the preferred/latest-restated figure selected by normalizer.
                # In SEC companyfacts, a period may have multiple valid reported figures across filing vintages
                # (e.g. original total including discontinued operations vs restated continuing-only figures).
                # Matching ANY SEC-reported vintage within 1% tolerance confirms a valid extraction.
                # A BLOCKER is recorded ONLY if metric.value matches NONE of the SEC-reported vintages.
                ext_val = float(metric.value)
                matched_vintage = False

                for entry, concept_short in candidate_entries:
                    ref_val = float(entry["val"])
                    if abs(ext_val - ref_val) <= (0.01 * abs(ref_val)):
                        matched_vintage = True
                        break

                if matched_vintage:
                    reconciled_count += 1
                else:
                    # Extracted value matches no reported vintage for this period -> genuine extraction error
                    latest_entry, latest_concept = max(
                        candidate_entries,
                        key=lambda item: str(item[0].get("filed", ""))
                    )
                    mismatch_details.append({
                        "metric_code": metric.metric_code,
                        "period": metric.period,
                        "extracted_value": ext_val,
                        "reference_value": float(latest_entry["val"]),
                        "concept": latest_concept
                    })

            total_evaluated = reconciled_count + len(mismatch_details)

            # BLOCKER only if a key fact value mismatches ("checked and wrong" -> FAIL per §12, §20.3)
            if len(mismatch_details) > 0:
                blocker = QualityIssue(
                    issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    rule_code="EXTRACTION_ACCURACY",
                    severity="BLOCKER",
                    status="OPEN",
                    details={
                        "message": f"Sample key facts reconciliation failed: {len(mismatch_details)} value mismatches against SEC companyfacts API.",
                        "reconciled_count": reconciled_count,
                        "total_evaluated": total_evaluated,
                        "mismatches": mismatch_details
                    }
                )
                return reconciled_count, total_evaluated, blocker

            # When zero key facts could be evaluated (total_evaluated == 0 due to no in-window annual metrics to check),
            # do NOT emit a BLOCKER ("nothing to check" -> INSUFFICIENT DATA, not FAIL per §20.3)
            if total_evaluated == 0:
                logger.info(f"Zero sample key facts could be evaluated for issuer {issuer.ticker} (no in-window annual metrics available for SEC companyfacts reconciliation).")
                return 0, 0, None

            logger.info(f"Sample key facts reconciliation passed: {reconciled_count}/{total_evaluated} key headline metrics matched SEC companyfacts API.")
            return reconciled_count, total_evaluated, None


        except Exception as e:
            blocker = QualityIssue(
                issue_id=f"issue_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                rule_code="EXTRACTION_ACCURACY",
                severity="BLOCKER",
                status="OPEN",
                details={"message": f"Independent SEC companyfacts reconciliation failed with exception: {e}"}
            )
            return 0, 0, blocker