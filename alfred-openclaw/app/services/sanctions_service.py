import os
import time
import logging

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# SQLAlchemy engine — same pool config as the standalone sanctions_service
_db_url = os.environ.get("NEON_DATABASE_URL", "")
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(_db_url, pool_size=10, max_overflow=20) if _db_url else None


class SanctionsService:
    """CRUD operations for sanctions_blacklist."""

    def upsert(self, ticker: str, name: str, regulatory_body: str) -> dict:
        """Insert or update a sanctioned entity. Returns the upserted row."""
        query = text("""
            INSERT INTO sanctions_blacklist (ticker, name, regulatory_body, listed_on, updated_at)
            VALUES (:ticker, :name, :regulatory_body, CURRENT_DATE, CURRENT_TIMESTAMP)
            ON CONFLICT (ticker)
            DO UPDATE SET
                name = EXCLUDED.name,
                regulatory_body = EXCLUDED.regulatory_body,
                updated_at = CURRENT_TIMESTAMP
            RETURNING ticker, name, regulatory_body;
        """)
        with engine.begin() as conn:
            result = conn.execute(query, {
                "ticker": ticker,
                "name": name,
                "regulatory_body": regulatory_body,
            }).fetchone()
        return dict(result._mapping)

    def get_by_ticker(self, ticker: str) -> dict | None:
        """Look up a ticker. Returns the row dict or None."""
        start = time.perf_counter()
        query = text(
            "SELECT ticker, name, regulatory_body "
            "FROM sanctions_blacklist WHERE ticker = :ticker"
        )
        with engine.connect() as conn:
            result = conn.execute(query, {"ticker": ticker}).fetchone()
        latency_ms = (time.perf_counter() - start) * 1000

        if not result:
            return None

        return {
            "data": dict(result._mapping),
            "lookup_time_ms": round(latency_ms, 2),
        }
