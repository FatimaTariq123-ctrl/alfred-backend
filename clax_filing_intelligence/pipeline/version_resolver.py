"""
Stage 6: Version Resolver & Restatement Lineage Manager (§7.1-7.3)

Implements §7.2 preferred value resolution algorithm per canonical_fact_key.
"""

import json
import logging
from hashlib import sha256
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timezone

from schema.models import Filing, FactObservation, FactVersion, MaterialEvent, NormalizedMetric
from storage.db import DatabaseManager
from pipeline.normalizer import CONCEPT_TO_METRIC
from config.policy import PolicyConfig, DEFAULT_POLICY

logger = logging.getLogger(__name__)

STATUS_PRECEDENCE = {
    "NON_COMPARABLE": 4,
    "RESTATED": 3,
    "RECLASSIFIED": 2,
    "COMPARABLE": 1,
}

CLASSIFICATION_TO_STATUS = {
    "UNCHANGED": "COMPARABLE",
    "SIGN_ONLY": "RECLASSIFIED",
    "VALUE_CHANGE": "RESTATED",
    "ZERO_BOUNDARY": "NON_COMPARABLE",
}


def classify_revision(original_value: Optional[float], preferred_value: Optional[float]) -> str:
    """
    Classifies the value difference between original and preferred observations (§7.2).
    Exact comparison only.
    """
    if original_value is None or preferred_value is None or original_value == preferred_value:
        return "UNCHANGED"
    if original_value == 0 or preferred_value == 0:
        return "ZERO_BOUNDARY"
    if preferred_value == -original_value:
        return "SIGN_ONLY"
    return "VALUE_CHANGE"


_SCALE_FACTORS = (10.0, 100.0, 1000.0, 1_000_000.0)


def classify_value_change_reason(
    original_value: Optional[float],
    preferred_value: Optional[float],
    preferred_obs: FactObservation,
    preferred_filing: Optional[Filing],
    tolerance_days: int = 120
) -> str:
    """
    For a VALUE_CHANGE only: WHY the value differs, using signals that are actually in the data
    (team head item 8: "give each change a reason" -- duplicate/scale/context/amended/recast/genuine).
    "Context" (a dimension mismatch) cannot occur here: canonical_fact_key already hashes dimensions,
    so two facts with different dimensions never share a key in the first place. The remaining,
    data-groundable categories, checked in order of mechanical certainty:
      SCALE_DIFFERENCE    the ratio is (within tolerance) a power of ten or its reciprocal -- a unit/
                          scale reporting difference, not an economic change
      AMENDED_FILING      the preferred observation comes from a 10-K/A or 10-Q/A: the filer itself
                          marked this value as amended
      RECAST_COMPARATIVE  the preferred observation's own period (period_end or instant_date) predates
                          the filing that carries it by more than ~45 days: it is a comparative figure
                          a later filing re-stated, not a correction made within its own original filing
      RESTATEMENT         none of the above explains it: the most likely genuine restatement/revision
    """
    if original_value is None or preferred_value is None or original_value == 0:
        return "RESTATEMENT"
    ratio = preferred_value / original_value
    for factor in _SCALE_FACTORS:
        if abs(ratio - factor) < 1e-6 or abs(ratio - (1.0 / factor)) < 1e-6:
            return "SCALE_DIFFERENCE"

    if preferred_filing and preferred_filing.amendment_flag:
        return "AMENDED_FILING"

    fact_date = preferred_obs.period_end or preferred_obs.instant_date
    if fact_date and preferred_filing and preferred_filing.filing_date:
        if (preferred_filing.filing_date - fact_date).days > tolerance_days:
            return "RECAST_COMPARATIVE"

    return "RESTATEMENT"
    ratio = preferred_value / original_value
    for factor in _SCALE_FACTORS:
        if abs(ratio - factor) < 1e-6 or abs(ratio - (1.0 / factor)) < 1e-6:
            return "SCALE_DIFFERENCE"

    if preferred_filing and preferred_filing.amendment_flag:
        return "AMENDED_FILING"

    if preferred_filing and preferred_filing.filing_date:
        fact_date = None  # the fact's own period, if we have one to compare against the filing date
    return "RESTATEMENT"


def _is_consolidated_fact(fact: FactObservation) -> bool:
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


class VersionResolver:
    def __init__(self, db_manager: Optional[DatabaseManager] = None, policy: Optional["PolicyConfig"] = None):
        self.db = db_manager or DatabaseManager()
        self.policy = policy or DEFAULT_POLICY
        self.last_summary: Dict[str, int] = {
            "UNCHANGED": 0,
            "SIGN_ONLY": 0,
            "ZERO_BOUNDARY": 0,
            "VALUE_CHANGE": 0,
            "events_high": 0,
            "events_low": 0,
            "revision_SCALE_DIFFERENCE": 0,
            "revision_AMENDED_FILING": 0,
            "revision_RECAST_COMPARATIVE": 0,
            "revision_RESTATEMENT": 0,
        }

    def resolve(
        self,
        filings: List[Filing],
        facts: List[FactObservation],
        metrics: List[NormalizedMetric]
    ) -> Tuple[List[FactVersion], List[MaterialEvent]]:
        """
        Executes preferred value resolution for all canonical fact keys per §7.2 algorithm.
        """
        fact_versions: List[FactVersion] = []
        emitted_events: List[MaterialEvent] = []

        filing_map = {f.filing_id: f for f in filings}

        # Group facts by canonical_fact_key. A fact the normalizer flagged excluded_from_versioning
        # (an intra-filing duplicate-value anomaly -- the filer tagged the same value under two
        # different periods in one filing) is left out of comparison entirely: it stays in
        # fact_observation exactly as extracted, it is just never used to detect a restatement.
        key_to_facts: Dict[str, List[FactObservation]] = {}
        skipped_excluded = 0
        for f in facts:
            if getattr(f, "excluded_from_versioning", False):
                skipped_excluded += 1
                continue
            if f.canonical_fact_key:
                key_to_facts.setdefault(f.canonical_fact_key, []).append(f)
        if skipped_excluded:
            logger.info(f"Version resolution: {skipped_excluded} fact(s) excluded from comparison "
                        f"(flagged by the normalizer's duplicate-value anomaly check).")

        counts = {
            "UNCHANGED": 0,
            "SIGN_ONLY": 0,
            "ZERO_BOUNDARY": 0,
            "VALUE_CHANGE": 0,
            "events_high": 0,
            "events_low": 0,
            "revision_SCALE_DIFFERENCE": 0,
            "revision_AMENDED_FILING": 0,
            "revision_RECAST_COMPARATIVE": 0,
            "revision_RESTATEMENT": 0,
        }
        warning_examples: List[Dict[str, Any]] = []
        fact_id_to_status: Dict[str, str] = {}

        for canonical_key, candidate_facts in key_to_facts.items():
            # Order observations by filing_date ascending, then amendment_flag
            sorted_candidates = sorted(
                candidate_facts,
                key=lambda x: (
                    filing_map[x.filing_id].filing_date if x.filing_id in filing_map else datetime.min.date(),
                    1 if (x.filing_id in filing_map and filing_map[x.filing_id].amendment_flag) else 0
                )
            )

            original_obs = sorted_candidates[0]
            preferred_obs = sorted_candidates[-1]

            pref_filing = filing_map.get(preferred_obs.filing_id)
            orig_filing = filing_map.get(original_obs.filing_id)
            is_amended = pref_filing.amendment_flag if pref_filing else False

            classification = classify_revision(original_obs.value, preferred_obs.value)
            counts[classification] += 1

            if classification == "UNCHANGED":
                reason = "AMENDED" if is_amended else "ORIGINAL"
            elif classification == "SIGN_ONLY":
                reason = "RECLASSIFIED"
            elif classification == "ZERO_BOUNDARY":
                reason = "UNRESOLVED"
            elif classification == "VALUE_CHANGE":
                reason = "RESTATED"
                revision_category = classify_value_change_reason(original_obs.value, preferred_obs.value, preferred_obs, pref_filing,
                                                                   tolerance_days=self.policy.recast_comparative_tolerance_days)
                counts[f"revision_{revision_category}"] += 1

            if classification in ("SIGN_ONLY", "ZERO_BOUNDARY") and len(warning_examples) < 5:
                warning_examples.append({
                    "concept": preferred_obs.concept,
                    "original_value": original_obs.value,
                    "preferred_value": preferred_obs.value,
                    "original_accession": orig_filing.accession_number if orig_filing else "",
                    "preferred_accession": pref_filing.accession_number if pref_filing else "",
                })

            metric_status = CLASSIFICATION_TO_STATUS[classification]
            fact_id_to_status[original_obs.fact_id] = metric_status
            fact_id_to_status[preferred_obs.fact_id] = metric_status

            if pref_filing and pref_filing.filing_date:
                effective_dt = datetime.combine(pref_filing.filing_date, datetime.min.time(), tzinfo=timezone.utc)
            else:
                effective_dt = datetime.now(timezone.utc)

            fact_version = FactVersion(
                canonical_key=canonical_key,
                original_fact_id=original_obs.fact_id,
                preferred_fact_id=preferred_obs.fact_id,
                version_reason=reason,
                effective_from=effective_dt,
                updated_at=datetime.now(timezone.utc)
            )

            fact_versions.append(fact_version)

            # Emit RESTATEMENT_OR_REVISION event ONLY for VALUE_CHANGE
            if classification == "VALUE_CHANGE":
                # Exact match on taxonomy:LocalName only (was previously an "endswith" check, which treated
                # any concept merely ending in a headline tag's local name, e.g. "...OfPlanAssets" ending in
                # "Assets", as headline). CONCEPT_TO_METRIC now covers the full policy metric list, so an
                # endswith match became too loose; exact match is what the headline classification needs.
                taxonomy, _, local_name = preferred_obs.concept.partition(":")
                is_headline_concept = taxonomy == "us-gaap" and f"us-gaap:{local_name}" in CONCEPT_TO_METRIC
                is_consolidated = _is_consolidated_fact(preferred_obs)
                is_high = is_headline_concept and is_consolidated
                severity = "HIGH" if is_high else "LOW"

                if is_high:
                    counts["events_high"] += 1
                    thesis_tags = ["accounting_quality", "restatement", "preferred_value_revision"]
                else:
                    counts["events_low"] += 1
                    thesis_tags = ["accounting_quality", "preferred_value_revision"]

                variance = (preferred_obs.value - original_obs.value) if (preferred_obs.value is not None and original_obs.value is not None) else None
                event_hash = sha256(f"{canonical_key}|{original_obs.filing_id}|{preferred_obs.filing_id}".encode("utf-8")).hexdigest()[:12]
                event_id = f"evt_restatement_{event_hash}"

                event = MaterialEvent(
                    event_id=event_id,
                    issuer_id=pref_filing.issuer_id if pref_filing else "unknown",
                    filing_id=preferred_obs.filing_id,
                    event_type="RESTATEMENT_OR_REVISION",
                    event_date=pref_filing.filing_date if pref_filing else datetime.min.date(),
                    severity=severity,
                    thesis_tags=thesis_tags,
                    details={
                        "concept": preferred_obs.concept,
                        "canonical_fact_key": canonical_key,
                        "original_value": original_obs.value,
                        "preferred_value": preferred_obs.value,
                        "variance": variance,
                        "classification": classification,
                        "original_filing_id": original_obs.filing_id,
                        "preferred_filing_id": preferred_obs.filing_id,
                        "original_accession": orig_filing.accession_number if orig_filing else "",
                        "preferred_accession": pref_filing.accession_number if pref_filing else "",
                        "dimensions": preferred_obs.dimensions,
                        "revision_category": revision_category
                    }
                )
                emitted_events.append(event)
                logger.info(f"Emitted RESTATEMENT_OR_REVISION event ({severity}, {revision_category}) for concept {preferred_obs.concept}: {original_obs.value} -> {preferred_obs.value}")

        # Batch-persist fact versions and material events accumulated above
        self.db.save_fact_versions(fact_versions)
        self.db.save_material_events(emitted_events)

        # Update metric comparability status
        for m in metrics:
            candidate_statuses = [
                fact_id_to_status[fid]
                for fid in m.provenance_fact_ids
                if fid in fact_id_to_status
            ]
            if candidate_statuses:
                worst_status = max(candidate_statuses, key=lambda s: STATUS_PRECEDENCE.get(s, 0))
                if m.comparability_status != worst_status:
                    m.comparability_status = worst_status
                    self.db.save_normalized_metric(m)

        self.last_summary = counts
        logger.info(f"Version resolution summary: {self.last_summary}")
        if counts["ZERO_BOUNDARY"] > 0 or counts["SIGN_ONLY"] > 0:
            logger.warning(
                f"Detected revisions requiring attention (RECLASSIFIED={counts['SIGN_ONLY']}, UNRESOLVED={counts['ZERO_BOUNDARY']}). "
                f"Sample examples: {warning_examples}"
            )

        return fact_versions, emitted_events
