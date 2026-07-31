import psycopg2
from psycopg2 import OperationalError
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# The exact ALFRED SQL schema we created
SCHEMA_SQL = """
-- ENUMS
DO $$ BEGIN
    CREATE TYPE trade_status AS ENUM ('PROCESSING', 'RECONCILING', 'SUCCESS', 'FAILED', 'VETOED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE order_action AS ENUM ('BUY', 'SELL');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 1. user_investor_dna
CREATE TABLE IF NOT EXISTS user_investor_dna (
    profile_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           TEXT NOT NULL UNIQUE,
    created_date      DATE DEFAULT CURRENT_DATE,
    last_updated      DATE DEFAULT CURRENT_DATE,
    reprofile_due     DATE DEFAULT CURRENT_DATE + INTERVAL '6 months',
    archetype         TEXT,
    full_profile_json JSONB,
    raw_answers       JSONB
);

-- 2. clax_trade_ledger
CREATE TABLE IF NOT EXISTS clax_trade_ledger (
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

-- 3. clax_conditional_orders
CREATE TABLE IF NOT EXISTS clax_conditional_orders (
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

-- 4. clax_compliance_worm_logs
CREATE TABLE IF NOT EXISTS clax_compliance_worm_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_id UUID REFERENCES clax_trade_ledger(id),
    veto_type VARCHAR(50) NOT NULL,
    veto_reason TEXT NOT NULL,
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. sanctions_blacklist
CREATE TABLE IF NOT EXISTS sanctions_blacklist (
    ticker VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    regulatory_body VARCHAR(50) NOT NULL,
    listed_on DATE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- INDEXES
CREATE INDEX IF NOT EXISTS idx_ledger_user_id ON clax_trade_ledger(user_id);
CREATE INDEX IF NOT EXISTS idx_conditional_active ON clax_conditional_orders(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_worm_logs_ledger ON clax_compliance_worm_logs(ledger_id);
CREATE INDEX IF NOT EXISTS idx_sanctions_ticker ON sanctions_blacklist(ticker);

-- FUNCTIONS & TRIGGERS
CREATE OR REPLACE FUNCTION prevent_update_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Updates and Deletes are strictly forbidden on WORM tables (SFC Schedule 7).';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS worm_insert_only ON clax_compliance_worm_logs;
CREATE TRIGGER worm_insert_only
BEFORE UPDATE OR DELETE ON clax_compliance_worm_logs
FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();
"""

def setup_database():
    # Attempt to get the database URL from the environment (.env)
    # Uses NEON_DATABASE_URL to match your repository conventions
    db_url = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ Error: Database URL not found.")
        print("Please set NEON_DATABASE_URL or DATABASE_URL in your .env file or environment.")
        return

    print("🔄 Connecting to the database...")
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        print("⚙️  Executing schema setup script...")
        cur.execute(SCHEMA_SQL)
        conn.commit()
        
        print("✅ Database schema created successfully! All tables, enums, and triggers are ready.")
        
        cur.close()
        conn.close()
    except OperationalError as e:
        print(f"❌ Connection failed: {e}")
        print("Check your database credentials and ensure the server is accessible.")
    except Exception as e:
        print(f"❌ An error occurred during schema execution: {e}")
        # Rollback in case of a mid-execution failure
        if 'conn' in locals() and conn:
            conn.rollback()

if __name__ == "__main__":
    setup_database()
