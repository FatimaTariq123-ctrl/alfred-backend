CREATE TABLE IF NOT EXISTS fie_company_state (
    run_id VARCHAR(64) PRIMARY KEY REFERENCES ingestion_run(run_id),
    issuer_id VARCHAR(64) NOT NULL REFERENCES issuer(issuer_id),
    as_of_date DATE NOT NULL,
    handover_status VARCHAR(32) NOT NULL,
    confidence VARCHAR(16) NOT NULL,
    history_window_years INT NOT NULL,
    policy_version VARCHAR(32) NOT NULL,
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0',
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fie_state_issuer ON fie_company_state(issuer_id, as_of_date DESC, created_at DESC);
CREATE OR REPLACE VIEW fie_company_state_latest AS
    SELECT DISTINCT ON (issuer_id) * FROM fie_company_state
    ORDER BY issuer_id, as_of_date DESC, created_at DESC;
