"""
Stage 7: Material Event Emitter & FactGuard Bridge (§9)

Emits accounting and corporate events separately from normalized financial facts.
Enables FactGuard and thesis engine to react to accounting-quality signals
without contaminating historical quantitative series.

8-K events are classified from the SEC item numbers the filing itself declares (Item 2.02, 5.02, ...),
never from a blanket default. One event is emitted per substantive item, so a filing with several items
keeps all of its evidence (details.all_items) and is not forced into one unrelated category.
"""

import re
import hashlib
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from schema.models import Issuer, Filing, MaterialEvent, TextChunk
from storage.db import DatabaseManager
from common.ids import stable_id

logger = logging.getLogger(__name__)

# SEC Form 8-K item -> (event_type, severity, extra thesis tags, official item title)
# Item 9.01 (financial statements and exhibits) only lists exhibits, so it never produces an event by itself.
EIGHT_K_ITEMS: Dict[str, Tuple[str, str, List[str], str]] = {
    "1.01": ("MATERIAL_AGREEMENT", "MEDIUM", ["agreements"], "Entry into a Material Definitive Agreement"),
    "1.02": ("AGREEMENT_TERMINATION", "MEDIUM", ["agreements"], "Termination of a Material Definitive Agreement"),
    "1.03": ("BANKRUPTCY_OR_RECEIVERSHIP", "HIGH", ["distress"], "Bankruptcy or Receivership"),
    "1.04": ("MINE_SAFETY_DISCLOSURE", "LOW", ["safety"], "Mine Safety - Reporting of Shutdowns and Patterns of Violations"),
    "1.05": ("CYBERSECURITY_INCIDENT", "HIGH", ["cyber"], "Material Cybersecurity Incidents"),
    "2.01": ("ACQUISITION_OR_DISPOSITION", "MEDIUM", ["corporate_action", "m_and_a"], "Completion of Acquisition or Disposition of Assets"),
    "2.02": ("RESULTS_OF_OPERATIONS", "LOW", ["earnings"], "Results of Operations and Financial Condition"),
    "2.03": ("NEW_DEBT_OR_FINANCING", "MEDIUM", ["financing"], "Creation of a Direct Financial Obligation"),
    "2.04": ("OBLIGATION_ACCELERATION", "HIGH", ["financing", "distress"], "Triggering Events That Accelerate or Increase a Direct Financial Obligation"),
    "2.05": ("EXIT_OR_RESTRUCTURING_COSTS", "MEDIUM", ["restructuring"], "Costs Associated with Exit or Disposal Activities"),
    "2.06": ("MATERIAL_IMPAIRMENT", "MEDIUM", ["accounting_quality", "impairment"], "Material Impairments"),
    "3.01": ("LISTING_NOTICE_OR_DELISTING", "HIGH", ["listing"], "Notice of Delisting or Failure to Satisfy a Continued Listing Rule"),
    "3.02": ("UNREGISTERED_EQUITY_SALE", "MEDIUM", ["dilution"], "Unregistered Sales of Equity Securities"),
    "3.03": ("SECURITY_HOLDER_RIGHTS_CHANGE", "MEDIUM", ["governance"], "Material Modification to Rights of Security Holders"),
    "4.01": ("AUDITOR_CHANGE", "HIGH", ["governance", "auditor_change"], "Changes in Registrant's Certifying Accountant"),
    "4.02": ("NON_RELIANCE_ON_FINANCIALS", "HIGH", ["accounting_quality", "restatement"], "Non-Reliance on Previously Issued Financial Statements"),
    "5.01": ("CHANGE_IN_CONTROL", "HIGH", ["governance", "control"], "Changes in Control of Registrant"),
    "5.02": ("MANAGEMENT_CHANGE", "MEDIUM", ["governance", "management_change"], "Departure or Appointment of Directors or Officers; Compensatory Arrangements"),
    "5.03": ("GOVERNING_DOCUMENT_AMENDMENT", "LOW", ["governance"], "Amendments to Articles of Incorporation or Bylaws; Change in Fiscal Year"),
    "5.04": ("BENEFIT_PLAN_BLACKOUT", "LOW", ["governance"], "Temporary Suspension of Trading Under Registrant's Employee Benefit Plans"),
    "5.05": ("ETHICS_CODE_CHANGE", "LOW", ["governance"], "Amendments to the Registrant's Code of Ethics, or Waiver of a Provision"),
    "5.06": ("SHELL_COMPANY_STATUS_CHANGE", "MEDIUM", ["governance"], "Change in Shell Company Status"),
    "5.07": ("SHAREHOLDER_VOTE", "LOW", ["governance", "shareholder_vote"], "Submission of Matters to a Vote of Security Holders"),
    "5.08": ("DIRECTOR_NOMINATION_WINDOW", "LOW", ["governance"], "Shareholder Director Nominations"),
    "7.01": ("REGULATION_FD", "LOW", ["disclosure"], "Regulation FD Disclosure"),
    "8.01": ("OTHER_MATERIAL_EVENT", "LOW", ["other"], "Other Events"),
}
IGNORED_ITEMS = {"9.01"}          # exhibits only
ASSET_BACKED_ITEMS = {"6.01", "6.02", "6.03", "6.04", "6.05", "6.06", "6.10"}

_ITEM_IN_TEXT = re.compile(r"\bitem\s+(\d{1,2}\.\d{2})\b", re.IGNORECASE)
_ACQUISITION_EVIDENCE = re.compile(
    r"(agreement and plan of merger|merger agreement|definitive agreement to (?:acquire|purchase|sell)|"
    r"(?:completed|completion of|consummated)\s+(?:the|its|our)\s+acquisition|acquisition of [A-Z][A-Za-z&.\- ]{3,60}|"
    r"sale of (?:substantially all|its|our) )",
    re.IGNORECASE,
)


def classify_8k_item(item: str) -> Dict[str, Any]:
    """Maps one SEC 8-K item number to its event category. Unknown items are kept, flagged as unmapped."""
    if item in EIGHT_K_ITEMS:
        etype, severity, tags, title = EIGHT_K_ITEMS[item]
        return {"item": item, "event_type": etype, "severity": severity, "tags": list(tags), "title": title, "mapped": True}
    if item in ASSET_BACKED_ITEMS:
        return {"item": item, "event_type": "ASSET_BACKED_SECURITIES_REPORT", "severity": "LOW", "tags": ["abs"],
                "title": "Asset-backed securities item", "mapped": True}
    return {"item": item, "event_type": "OTHER_MATERIAL_EVENT", "severity": "LOW", "tags": ["other"],
            "title": "Item not in the mapping table", "mapped": False}


def items_from_chunks(chunks: List[TextChunk]) -> List[str]:
    """Fallback when the EDGAR index gave no items: read 'Item X.XX' from the section names / first lines of the filing text."""
    found: List[str] = []
    for c in chunks:
        for source in ((c.section or ""), (c.text or "")[:200]):
            for m in _ITEM_IN_TEXT.finditer(source):
                if m.group(1) not in found:
                    found.append(m.group(1))
    return found


def find_acquisition_evidence(chunks: List[TextChunk]) -> Optional[str]:
    """Explicit acquisition / merger wording in the filing text, or None. Used only to ANNOTATE an event, never to type it."""
    for c in chunks:
        m = _ACQUISITION_EVIDENCE.search(c.text or "")
        if m:
            start = max(0, m.start() - 60)
            return re.sub(r"\s+", " ", (c.text or "")[start:m.end() + 100]).strip()
    return None


def resolve_items(filing: Filing, filing_chunks: List[TextChunk]) -> Tuple[List[str], Optional[str]]:
    """Item numbers of an 8-K: the EDGAR index first, the filing text as a fallback. Returns (items, source)."""
    items = list(filing.sec_items or [])
    if items:
        return items, "EDGAR_INDEX"
    items = items_from_chunks(filing_chunks)
    return items, ("FILING_TEXT" if items else None)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def item_text_fingerprint(chunks: List[TextChunk], items: Tuple[str, ...]) -> Optional[str]:
    """
    Fingerprint of what an 8-K says under its substantive items (lower-cased, whitespace collapsed, exhibit-list item left out).
    When no chunk carries an item name, all chunks are used. None when the filing has no text at all.
    """
    wanted = set(items)
    named = [(m.group(1), c) for c in chunks for m in [_ITEM_IN_TEXT.search(c.section or "")] if m]
    selected = [c for item, c in named if item in wanted] if named else list(chunks)
    parts = [normalize_text(c.text) for c in selected if normalize_text(c.text)]
    if not parts:
        return None
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class MaterialEventEmitter:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        # Problems found while classifying (for the quality-issue stage): dicts with rule_code / severity / filing_id / message
        self.notes: List[Dict[str, Any]] = []

    def _eight_k_events(self, issuer: Issuer, filing: Filing, filing_chunks: List[TextChunk]) -> List[MaterialEvent]:
        items, item_source = resolve_items(filing, filing_chunks)
        all_items = list(items)
        substantive = [i for i in items if i not in IGNORED_ITEMS]
        base_details = {"form": filing.form_type, "accession": filing.accession_number,
                        "all_items": all_items, "item_source": item_source if items else None}

        if not substantive:
            reason = "ONLY_EXHIBIT_ITEM" if items else "NO_ITEMS_FOUND"
            self.notes.append({"rule_code": "EVENT_UNCLASSIFIED_8K", "severity": "WARNING", "filing_id": filing.filing_id,
                               "message": f"8-K {filing.accession_number} could not be classified ({reason})."})
            return [MaterialEvent(
                event_id=stable_id("evt_8k", filing.filing_id, "UNCLASSIFIED"),
                issuer_id=issuer.issuer_id, filing_id=filing.filing_id, event_type="UNCLASSIFIED_8K",
                event_date=filing.filing_date, severity="LOW", thesis_tags=["event_driven", "8K"],
                details={**base_details, "classification_basis": reason},
            )]

        evidence = find_acquisition_evidence(filing_chunks) if any(i in ("1.01", "2.01", "8.01") for i in substantive) else None
        events: List[MaterialEvent] = []
        for item in substantive:
            cls = classify_8k_item(item)
            tags = ["event_driven"] + cls["tags"] + ["8K"]
            details = {**base_details, "item": item, "item_title": cls["title"], "classification_basis": "SEC_ITEM"}
            if not cls["mapped"]:
                details["unmapped_item"] = True
                self.notes.append({"rule_code": "EVENT_UNMAPPED_8K_ITEM", "severity": "INFO", "filing_id": filing.filing_id,
                                   "message": f"8-K {filing.accession_number} item {item} is not in the mapping table."})
            if item in ("1.01", "2.01", "8.01"):
                details["acquisition_evidence"] = evidence      # None when the filing text has no explicit acquisition wording
                if evidence and item != "2.01":
                    tags.append("acquisition_related")
            events.append(MaterialEvent(
                event_id=stable_id("evt_8k", filing.filing_id, item),
                issuer_id=issuer.issuer_id, filing_id=filing.filing_id, event_type=cls["event_type"],
                event_date=filing.filing_date, severity=cls["severity"], thesis_tags=tags, details=details,
            ))
        return events

    def _annotate_same_day(self, eight_ks: List[Filing], events_by_filing: Dict[str, List[MaterialEvent]],
                           chunks_by_filing: Dict[str, List[TextChunk]]) -> None:
        """
        8-Ks filed on the same day with the same substantive items are compared by what their item text says.
        Identical text -> one economic event: the filing EDGAR accepted first is canonical, the others are marked
        duplicate_of it. Different text -> both are kept and the difference is documented. No text -> undetermined.
        Nothing is deleted: every filing keeps its own events and rows.
        """
        groups: Dict[Tuple[Any, Tuple[str, ...]], List[Filing]] = defaultdict(list)
        for f in eight_ks:
            items, _ = resolve_items(f, chunks_by_filing.get(f.filing_id, []))
            substantive = tuple(sorted(i for i in items if i not in IGNORED_ITEMS))
            if substantive:
                groups[(f.filing_date, substantive)].append(f)

        for (day, substantive), members in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            if len(members) < 2:
                continue
            accessions = sorted(m.accession_number for m in members)
            prints = {m.filing_id: item_text_fingerprint(chunks_by_filing.get(m.filing_id, []), substantive) for m in members}
            if any(v is None for v in prints.values()):
                for m in members:
                    self._tag(events_by_filing.get(m.filing_id, []), accessions, "UNDETERMINED",
                              "item text is not available for every filing of the group")
                self.notes.append({"rule_code": "EVENT_SAME_DAY_UNDETERMINED", "severity": "WARNING", "filing_id": members[0].filing_id,
                                   "message": f"Same-day 8-Ks {accessions} ({day}, items {list(substantive)}) cannot be compared: no item text."})
                continue

            clusters: Dict[str, List[Filing]] = defaultdict(list)
            for m in members:
                clusters[prints[m.filing_id]].append(m)
            for fp, cluster in clusters.items():
                if len(cluster) == 1:
                    basis = "item text differs from the other same-day filing(s)" if len(clusters) > 1 else ""
                    self._tag(events_by_filing.get(cluster[0].filing_id, []), accessions, "SEPARATE_FILING", basis)
                    continue
                canonical = min(cluster, key=lambda m: (m.accepted_at or datetime.max, m.accession_number))
                dup_accessions = sorted(m.accession_number for m in cluster if m is not canonical)
                basis = (f"same filing date, same SEC items {list(substantive)} and identical item text; "
                         f"canonical is the filing EDGAR accepted first ({canonical.accession_number})")
                canon_by_item = {(e.details or {}).get("item"): e for e in events_by_filing.get(canonical.filing_id, [])}
                for m in cluster:
                    evs = events_by_filing.get(m.filing_id, [])
                    if m is canonical:
                        self._tag(evs, accessions, "CANONICAL", basis, also_filed_as=dup_accessions)
                    else:
                        self._tag(evs, accessions, "DUPLICATE_SUBMISSION", basis, canonical_accession=canonical.accession_number)
                        for e in evs:
                            target = canon_by_item.get((e.details or {}).get("item"))
                            if target is not None:
                                e.details["duplicate_of"] = target.event_id

    @staticmethod
    def _tag(events: List[MaterialEvent], accessions: List[str], relationship: str, basis: str, **extra: Any) -> None:
        for e in events:
            e.details = {**(e.details or {}), "same_day_group": accessions, "relationship": relationship, "relationship_basis": basis, **extra}

    @staticmethod
    def economic_events(events: List[MaterialEvent]) -> List[MaterialEvent]:
        """The events to COUNT: duplicate submissions are left out (their rows stay in the table, flagged duplicate_of)."""
        return [e for e in events if not (e.details or {}).get("duplicate_of")]

    def emit_events(
        self,
        issuer: Issuer,
        filings: List[Filing],
        chunks: List[TextChunk]
    ) -> List[MaterialEvent]:
        """
        Scans filings and text chunks to detect and emit material accounting/corporate events.
        """
        emitted: Dict[str, MaterialEvent] = {}       # keyed by event_id: the same event can never be emitted twice
        events_by_filing: Dict[str, List[MaterialEvent]] = {}
        self.notes = []

        chunks_by_filing: Dict[str, List[TextChunk]] = {}
        for c in chunks:
            chunks_by_filing.setdefault(c.filing_id, []).append(c)

        for filing in filings:
            filing_chunks = chunks_by_filing.get(filing.filing_id, [])

            if filing.form_type == "8-K":
                filing_events = self._eight_k_events(issuer, filing, filing_chunks)
                events_by_filing[filing.filing_id] = filing_events
                for event in filing_events:
                    emitted.setdefault(event.event_id, event)
                continue                             # item-based; the keyword scan below is for periodic reports

            # Scan text chunks of periodic reports for accounting policy changes or auditor changes
            for chunk in filing_chunks:
                text_lower = chunk.text.lower()
                if "accounting policy change" in text_lower or "adoption of new accounting" in text_lower:
                    event = MaterialEvent(
                        event_id=stable_id("evt_policy", filing.filing_id, chunk.chunk_id),
                        issuer_id=issuer.issuer_id,
                        filing_id=filing.filing_id,
                        event_type="ACCOUNTING_POLICY_CHANGE",
                        event_date=filing.filing_date,
                        severity="MEDIUM",
                        thesis_tags=["accounting_quality", "policy_change"],
                        details={"section": chunk.section}
                    )
                    emitted.setdefault(event.event_id, event)

                if "auditor change" in text_lower or "resignation of independent registered" in text_lower:
                    event = MaterialEvent(
                        event_id=stable_id("evt_auditor", filing.filing_id, chunk.chunk_id),
                        issuer_id=issuer.issuer_id,
                        filing_id=filing.filing_id,
                        event_type="AUDITOR_CHANGE",
                        event_date=filing.filing_date,
                        severity="HIGH",
                        thesis_tags=["governance", "auditor_change"],
                        details={"section": chunk.section}
                    )
                    emitted.setdefault(event.event_id, event)

        self._annotate_same_day([f for f in filings if f.form_type == "8-K"], events_by_filing, chunks_by_filing)

        events = list(emitted.values())
        if events:
            if hasattr(self.db, "save_material_events"):
                self.db.save_material_events(events)         # one batch instead of one commit per event
            else:
                for event in events:
                    self.db.save_material_event(event)

        by_type: Dict[str, int] = {}
        for e in events:
            by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
        duplicates = sum(1 for e in events if (e.details or {}).get("duplicate_of"))
        logger.info(f"Emitted {len(events)} material corporate & accounting events: {by_type}"
                    + (f" ({duplicates} flagged as duplicate submissions, kept in the table but counted once)" if duplicates else ""))
        return events
