import os
import logging

import redis as sync_redis
from sqlalchemy import create_engine, text

from app.schemas.trade_status_schema import TradeState, TradeStatusResponse

logger = logging.getLogger(__name__)

# SQLAlchemy engine — same pool config as other integrated services
_db_url = os.environ.get("NEON_DATABASE_URL", "")
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(_db_url, pool_size=10, max_overflow=20) if _db_url else None

# Redis URL
_redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class TradeStatusService:
    """Redis-first, PostgreSQL-fallback trade status lookup."""

    def __init__(self, redis_client: sync_redis.Redis):
        self.redis_client = redis_client

    def get_status(self, user_id: str, idempotency_key: str) -> TradeStatusResponse | None:
        # Step 1: Redis front-line check
        redis_key = f"idempotency:{user_id}:{idempotency_key}"
        cached_state = self.redis_client.get(redis_key)

        if cached_state:
            state_str = cached_state.decode("utf-8") if isinstance(cached_state, bytes) else cached_state
            logger.info("Cache HIT for %s: %s", redis_key, state_str)
            return TradeStatusResponse(
                idempotency_key=idempotency_key,
                status=TradeState(state_str),
                source="redis",
                payload=None,
            )

        # Step 2: Database fallback
        logger.info("Cache MISS for %s. Falling back to clax_trade_ledger.", redis_key)
        query = text("""
            SELECT status, payload
            FROM clax_trade_ledger
            WHERE user_id = :uid AND client_idempotency_key = :ikey
        """)
        with engine.connect() as conn:
            row = conn.execute(query, {"uid": user_id, "ikey": idempotency_key}).fetchone()

        if not row:
            logger.warning("Trade not found for key %s", idempotency_key)
            return None

        return TradeStatusResponse(
            idempotency_key=idempotency_key,
            status=TradeState(row.status),
            source="postgresql",
            payload=row.payload,
        )
