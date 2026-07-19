-- Rollback Script (Shanza)

DROP TABLE IF EXISTS clax_compliance_worm_logs CASCADE;
DROP TABLE IF EXISTS clax_conditional_orders CASCADE;
DROP TABLE IF EXISTS clax_trade_ledger CASCADE;

DROP TYPE IF EXISTS trade_status;
DROP TYPE IF EXISTS order_action;
