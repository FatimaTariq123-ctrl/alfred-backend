-- Parser provenance columns and performance indexes
ALTER TABLE fact_observation ADD COLUMN IF NOT EXISTS context_ref VARCHAR(255);
ALTER TABLE fact_observation ADD COLUMN IF NOT EXISTS parser_version VARCHAR(32);
ALTER TABLE text_chunk ADD COLUMN IF NOT EXISTS parser_version VARCHAR(32);
CREATE INDEX IF NOT EXISTS idx_text_chunk_filing_section ON text_chunk(filing_id, section);
CREATE INDEX IF NOT EXISTS idx_filing_asset_filing ON filing_asset(filing_id);
CREATE INDEX IF NOT EXISTS idx_quality_issue_run ON quality_issue(run_id);
