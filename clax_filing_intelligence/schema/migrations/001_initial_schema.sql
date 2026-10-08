-- CLAX Filing Intelligence - PostgreSQL DDL Migration
-- Version: 1.1.0
-- Authoritative schema implementation per §6, §11.1, C2, C10

-- 1. Ingestion Run Table (§11.1, C10)
CREATE TABLE IF NOT EXISTS ingestion_run (
    run_id VARCHAR(64) PRIMARY KEY,
    issuer_id VARCHAR(64) NOT NULL,
    as_of_date DATE NOT NULL,
    policy_version VARCHAR(32) NOT NULL,
    edgartools_version VARCHAR(32),
    parser_version VARCHAR(32),
    normalizer_version VARCHAR(32),
    status VARCHAR(32) NOT NULL, -- RUNNING, COMPLETED, FAILED
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    source_snapshot JSONB
);

-- 2. Issuer Table (§6)
CREATE TABLE IF NOT EXISTS issuer (
    issuer_id VARCHAR(64) PRIMARY KEY,
    market VARCHAR(16) NOT NULL, -- US, HK
    legal_name VARCHAR(255) NOT NULL,
    ticker VARCHAR(16) NOT NULL,
    cik VARCHAR(16),
    fiscal_year_end VARCHAR(8),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Filing Table (§6)
-- DB Constraint: UNIQUE(accession_number) enforces no-duplicate ingestion (C2)
CREATE TABLE IF NOT EXISTS filing (
    filing_id VARCHAR(64) PRIMARY KEY,
    issuer_id VARCHAR(64) NOT NULL REFERENCES issuer(issuer_id),
    accession_number VARCHAR(32) NOT NULL UNIQUE,
    form_type VARCHAR(32) NOT NULL, -- 10-K, 10-Q, 8-K, 10-K/A, 10-Q/A
    filing_date DATE NOT NULL,
    report_period DATE NOT NULL,
    amendment_flag BOOLEAN DEFAULT FALSE,
    base_filing_id VARCHAR(64) REFERENCES filing(filing_id),
    source_uri TEXT NOT NULL,
    source_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Filing Asset Table (§6, §11)
CREATE TABLE IF NOT EXISTS filing_asset (
    asset_id VARCHAR(64) PRIMARY KEY,
    filing_id VARCHAR(64) NOT NULL REFERENCES filing(filing_id),
    asset_type VARCHAR(32) NOT NULL, -- HTML, IXBRL, XML, PDF, TXT
    storage_uri TEXT NOT NULL,
    mime_type VARCHAR(64) NOT NULL,
    hash VARCHAR(64) NOT NULL,
    retrieved_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Fact Observation Table (§6, §6.1)
-- DB Constraint: UNIQUE(canonical_fact_key, filing_id) prevents duplicate observation per filing
CREATE TABLE IF NOT EXISTS fact_observation (
    fact_id VARCHAR(64) PRIMARY KEY,
    canonical_fact_key VARCHAR(64) NOT NULL,
    filing_id VARCHAR(64) NOT NULL REFERENCES filing(filing_id),
    concept VARCHAR(255) NOT NULL,
    value NUMERIC,
    unit VARCHAR(64),
    currency VARCHAR(16),
    period_start DATE,
    period_end DATE,
    instant_date DATE,
    dimensions JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_canonical_filing UNIQUE(canonical_fact_key, filing_id)
);

-- 6. Fact Version Table (§6, §7.2)
CREATE TABLE IF NOT EXISTS fact_version (
    canonical_key VARCHAR(64) PRIMARY KEY,
    original_fact_id VARCHAR(64) NOT NULL REFERENCES fact_observation(fact_id),
    preferred_fact_id VARCHAR(64) NOT NULL REFERENCES fact_observation(fact_id),
    version_reason VARCHAR(64) NOT NULL, -- ORIGINAL, RESTATED, AMENDED, RECLASSIFIED
    effective_from TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Normalized Metric Table (§6, §8)
CREATE TABLE IF NOT EXISTS normalized_metric (
    metric_id VARCHAR(64) PRIMARY KEY,
    issuer_id VARCHAR(64) NOT NULL REFERENCES issuer(issuer_id),
    metric_code VARCHAR(64) NOT NULL, -- REVENUE, NET_INCOME, OPERATING_INCOME, FCF, DEBT, EPS
    period VARCHAR(32) NOT NULL, -- FY2023, Q1-2024, Q4-2023 (DERIVED)
    value NUMERIC,
    unit VARCHAR(64),
    provenance_fact_ids TEXT[], -- Array of source fact_observation IDs
    provenance_filing_ids TEXT[], -- Array of source filing IDs
    comparability_status VARCHAR(32) NOT NULL, -- COMPARABLE, RESTATED, RECLASSIFIED, NON_COMPARABLE, MISSING
    is_derived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. Text Chunk Table (§6)
CREATE TABLE IF NOT EXISTS text_chunk (
    chunk_id VARCHAR(64) PRIMARY KEY,
    filing_id VARCHAR(64) NOT NULL REFERENCES filing(filing_id),
    section VARCHAR(128) NOT NULL,
    text TEXT NOT NULL,
    page_anchor VARCHAR(64),
    embedding_ref VARCHAR(128),
    source_span JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. Material Event Table (§6, §9)
CREATE TABLE IF NOT EXISTS material_event (
    event_id VARCHAR(64) PRIMARY KEY,
    issuer_id VARCHAR(64) NOT NULL REFERENCES issuer(issuer_id),
    filing_id VARCHAR(64) NOT NULL REFERENCES filing(filing_id),
    event_type VARCHAR(64) NOT NULL, -- RESTATEMENT_OR_REVISION, ACCOUNTING_POLICY_CHANGE, etc.
    event_date DATE NOT NULL,
    severity VARCHAR(16) NOT NULL, -- HIGH, MEDIUM, LOW
    thesis_tags TEXT[],
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. History Decision Table (§6, §10)
CREATE TABLE IF NOT EXISTS history_decision (
    decision_id VARCHAR(64) PRIMARY KEY,
    issuer_id VARCHAR(64) NOT NULL REFERENCES issuer(issuer_id),
    run_id VARCHAR(64) NOT NULL REFERENCES ingestion_run(run_id),
    mode VARCHAR(32) NOT NULL, -- NORMAL, EXTENDED, FORENSIC
    years_selected INT NOT NULL, -- 5, 10, etc.
    triggers TEXT[],
    policy_version VARCHAR(32) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 11. Quality Issue Table (§6, §12)
CREATE TABLE IF NOT EXISTS quality_issue (
    issue_id VARCHAR(64) PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES ingestion_run(run_id),
    filing_id VARCHAR(64) REFERENCES filing(filing_id),
    fact_id VARCHAR(64) REFERENCES fact_observation(fact_id),
    rule_code VARCHAR(64) NOT NULL, -- EXTRACTION_ACCURACY, RESTATEMENT_HANDLING, etc.
    severity VARCHAR(16) NOT NULL, -- BLOCKER, WARNING, INFO
    status VARCHAR(32) NOT NULL, -- OPEN, RESOLVED, FLAGGED
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast query performance
CREATE INDEX IF NOT EXISTS idx_filing_issuer_date ON filing(issuer_id, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_fact_canonical ON fact_observation(canonical_fact_key);
CREATE INDEX IF NOT EXISTS idx_fact_filing ON fact_observation(filing_id);
CREATE INDEX IF NOT EXISTS idx_metric_issuer_code ON normalized_metric(issuer_id, metric_code);
CREATE INDEX IF NOT EXISTS idx_event_issuer ON material_event(issuer_id, event_date DESC);
