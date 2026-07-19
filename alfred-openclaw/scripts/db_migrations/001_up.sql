-- Migration Script (Shanza)

CREATE TYPE trade_status AS ENUM ('PROCESSING', 'RECONCILING', 'SUCCESS', 'FAILED', 'VETOED');
CREATE TYPE order_action AS ENUM ('BUY', 'SELL');

CREATE TABLE clax_trade_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    client_idempotency_key UUID NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    action order_action NOT NULL,
    amount_usd DECIMAL(18,4) NOT NULL,
    status trade_status NOT NULL DEFAULT 'PROCESSING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_idempotency UNIQUE (user_id, client_idempotency_key)
);

CREATE TABLE clax_conditional_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    ledger_id UUID REFERENCES clax_trade_ledger(id),
    ticker VARCHAR(20) NOT NULL,
    action order_action NOT NULL,
    condition_type VARCHAR(50) NOT NULL,
    trigger_condition VARCHAR(255),
    trigger_value DECIMAL(18,4) NOT NULL,
    status VARCHAR(50) DEFAULT 'PENDING',
    is_active BOOLEAN DEFAULT TRUE,
    triggered_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE clax_compliance_worm_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_id UUID REFERENCES clax_trade_ledger(id),
    veto_type VARCHAR(50) NOT NULL,
    veto_reason TEXT NOT NULL,
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX idx_ledger_user_id ON clax_trade_ledger(user_id);
CREATE INDEX idx_conditional_active ON clax_conditional_orders(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_worm_logs_ledger ON clax_compliance_worm_logs(ledger_id);
