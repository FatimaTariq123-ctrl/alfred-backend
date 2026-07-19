import os
import logging

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# SQLAlchemy engine — same pool config as the standalone compliance_service
_db_url = os.environ.get("NEON_DATABASE_URL", "")
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(_db_url, pool_size=10, max_overflow=20) if _db_url else None

# Redis client — lazy, best-effort lock release
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as _redis
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = _redis.Redis.from_url(redis_url)
        return _redis_client
    except Exception:
        logger.warning("Redis unavailable — lock release will be skipped")
        return None


# Veto type → HTTP status code mapping
VETO_STATUS_CODES = {
    "SANCTIONS_MATCH": 403,
    "WASH_TRADE": 422,
    "PATTERN_VIOLATION": 422,
}

VALID_VETO_TYPES = set(VETO_STATUS_CODES.keys())


class ComplianceService:
    """Compliance veto: validate, audit-log, update trade, release lock."""

    def apply_veto(self, ledger_id: str, veto_type: str, veto_reason: str) -> dict:
        """Apply a compliance veto. Returns a result dict with veto_type."""
        # 1. Validate veto type
        if veto_type not in VALID_VETO_TYPES:
            valid = ", ".join(sorted(VALID_VETO_TYPES))
            raise ValueError(f"Invalid veto_type. Must be one of: {valid}")

        # 2. Write WORM audit log + update trade ledger (single transaction)
        insert_worm_log = text("""
            INSERT INTO clax_compliance_worm_logs (ledger_id, veto_type, veto_reason)
            VALUES (:ledger_id, :veto_type, :veto_reason)
        """)
        update_trade = text("""
            UPDATE clax_trade_ledger
            SET status = 'VETOED', updated_at = CURRENT_TIMESTAMP
            WHERE id = :ledger_id
        """)

        with engine.begin() as conn:
            conn.execute(insert_worm_log, {
                "ledger_id": ledger_id,
                "veto_type": veto_type,
                "veto_reason": veto_reason,
            })
            conn.execute(update_trade, {"ledger_id": ledger_id})

        # 3. Release Redis lock (best-effort)
        redis = _get_redis()
        if redis:
            try:
                lock_key = f"trade_lock_{ledger_id}"
                redis.delete(lock_key)
            except Exception as e:
                logger.warning("Failed to release Redis lock for %s: %s", ledger_id, e)

        # 4. Return result — router maps veto_type to HTTP status code
        return {
            "status": "VETOED",
            "veto_type": veto_type,
            "ui_card": {
                "title": "Trade Blocked (Compliance)",
                "body": f"Your trade was blocked due to a compliance flag: {veto_reason}",
            },
            "instructions": "Please contact compliance support to review this trade.",
        }
