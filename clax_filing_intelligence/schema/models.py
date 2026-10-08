"""
Data Models & Schema Entities (§6, §11.1)

Python dataclasses and Pydantic models for all 11 database entities.
Uses timezone-aware UTC timestamps for datetime fields.
"""

from typing import List, Optional, Dict, Any
from datetime import date, datetime, timezone
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionRun(BaseModel):
    run_id: str
    issuer_id: str
    as_of_date: date
    policy_version: str
    edgartools_version: Optional[str] = None
    parser_version: Optional[str] = None
    normalizer_version: Optional[str] = None
    status: str = "RUNNING"  # RUNNING, COMPLETED, FAILED
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = None
    source_snapshot: Optional[Dict[str, Any]] = None


class Issuer(BaseModel):
    issuer_id: str
    market: str  # US, HK
    legal_name: str
    ticker: str
    cik: Optional[str] = None
    fiscal_year_end: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class Filing(BaseModel):
    filing_id: str
    issuer_id: str
    accession_number: str
    form_type: str  # 10-K, 10-Q, 8-K, 10-K/A, 10-Q/A
    filing_date: date
    report_period: date
    amendment_flag: bool = False
    base_filing_id: Optional[str] = None
    source_uri: str
    source_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    # 8-K item numbers (for example ["2.02", "9.01"]) from the EDGAR index. Kept in memory for the event stage;
    # it is NOT a column of the filing table (the table is shared with other connectors).
    sec_items: Optional[List[str]] = None
    # When EDGAR accepted the submission (naive UTC). In memory only, like sec_items: used to pick the canonical one of two same-day 8-Ks.
    accepted_at: Optional[datetime] = None


class FilingAsset(BaseModel):
    asset_id: str
    filing_id: str
    asset_type: str  # HTML, IXBRL, XML, PDF, TXT
    storage_uri: str
    mime_type: str
    hash: str
    retrieved_at: datetime = Field(default_factory=utc_now)


class FactObservation(BaseModel):
    fact_id: str
    canonical_fact_key: str
    filing_id: str
    concept: str
    value: Optional[float] = None
    unit: Optional[str] = None
    currency: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    instant_date: Optional[date] = None
    dimensions: Optional[Dict[str, str]] = None
    fiscal_period: Optional[str] = None
    fiscal_year: Optional[str] = None
    context_ref: Optional[str] = None
    parser_version: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    # Set by the normalizer's duplicate-value anomaly check (never by the parser): True means this
    # fact must be skipped when version_resolver groups facts for restatement/revision comparison.
    # The row itself is still stored exactly as extracted; only its use in versioning is affected.
    excluded_from_versioning: bool = False
    exclusion_reason: Optional[str] = None


class FactVersion(BaseModel):
    canonical_key: str
    original_fact_id: str
    preferred_fact_id: str
    version_reason: str  # ORIGINAL, RESTATED, AMENDED, RECLASSIFIED, UNRESOLVED
    effective_from: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class NormalizedMetric(BaseModel):
    metric_id: str
    issuer_id: str
    metric_code: str  # REVENUE, NET_INCOME, OPERATING_INCOME, FCF, DEBT, EPS
    period: str  # FY2023, Q1-2024, Q4-2023 (DERIVED)
    value: Optional[float] = None
    unit: Optional[str] = None
    provenance_fact_ids: List[str] = Field(default_factory=list)
    provenance_filing_ids: List[str] = Field(default_factory=list)
    comparability_status: str  # COMPARABLE, RESTATED, RECLASSIFIED, NON_COMPARABLE, MISSING
    is_derived: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class TextChunk(BaseModel):
    chunk_id: str
    filing_id: str
    section: str
    text: str
    page_anchor: Optional[str] = None
    embedding_ref: Optional[str] = None
    source_span: Optional[Dict[str, Any]] = None
    parser_version: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class MaterialEvent(BaseModel):
    event_id: str
    issuer_id: str
    filing_id: str
    event_type: str  # RESTATEMENT_OR_REVISION, ACCOUNTING_POLICY_CHANGE, AUDITOR_CHANGE, IMPAIRMENT, etc.
    event_date: date
    severity: str  # HIGH, MEDIUM, LOW
    thesis_tags: List[str] = Field(default_factory=list)
    details: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=utc_now)


class HistoryDecision(BaseModel):
    decision_id: str
    issuer_id: str
    run_id: str
    mode: str  # NORMAL, EXTENDED, FORENSIC
    years_selected: int  # 5, 10, etc.
    triggers: List[str] = Field(default_factory=list)
    policy_version: str
    created_at: datetime = Field(default_factory=utc_now)


class QualityIssue(BaseModel):
    issue_id: str
    run_id: str
    filing_id: Optional[str] = None
    fact_id: Optional[str] = None
    rule_code: str  # EXTRACTION_ACCURACY, RESTATEMENT_HANDLING, etc.
    severity: str  # BLOCKER, WARNING, INFO
    status: str  # OPEN, RESOLVED, FLAGGED
    details: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=utc_now)
