import os
import time
import random
import string
import logging

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# SQLAlchemy engine — same pool config as other integrated services
_db_url = os.environ.get("NEON_DATABASE_URL", "")
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(_db_url, pool_size=10, max_overflow=20) if _db_url else None

# Duplicate detection window in seconds
DUPLICATE_WINDOW = 60


class DuplicateTradeError(Exception):
    """Raised when a duplicate trade is detected."""

    def __init__(self, confirmation_token: str, symbol: str, quantity: float):
        self.confirmation_token = confirmation_token
        self.symbol = symbol
        self.quantity = quantity


class TradePreventionService:
    """Duplicate trade detection with 60-second window."""

    def execute_trade(self, user_id: str, symbol: str, quantity: float, action: str) -> dict:
        """Execute a trade, raising DuplicateTradeError if a duplicate is detected."""
        now = time.time()

        with engine.begin() as conn:
            # Check for duplicate trade within window
            duplicate_query = text(
                "SELECT * FROM trades "
                "WHERE user_id = :uid AND symbol = :sym AND quantity = :qty "
                "AND action = :act AND timestamp > :ts"
            )
            duplicate = conn.execute(duplicate_query, {
                "uid": user_id,
                "sym": symbol,
                "qty": quantity,
                "act": action,
                "ts": now - DUPLICATE_WINDOW,
            }).fetchone()

            if duplicate:
                token = "conf_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
                raise DuplicateTradeError(token, symbol, quantity)

            # Insert new trade
            insert_query = text(
                "INSERT INTO trades (user_id, symbol, quantity, action, timestamp) "
                "VALUES (:uid, :sym, :qty, :act, :ts)"
            )
            conn.execute(insert_query, {
                "uid": user_id,
                "sym": symbol,
                "qty": quantity,
                "act": action,
                "ts": now,
            })

        # Generate mock success response
        trade_id = "trd_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        execution_price = round(random.uniform(50.0, 150.0), 2)

        return {
            "status": "success",
            "trade_id": trade_id,
            "symbol": symbol,
            "quantity": quantity,
            "action": action,
            "execution_price": execution_price,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }
