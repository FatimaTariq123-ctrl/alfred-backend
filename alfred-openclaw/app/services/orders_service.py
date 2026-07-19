import os
import logging

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# SQLAlchemy engine — same pool config as the standalone orders_service
_db_url = os.environ.get("NEON_DATABASE_URL", "")
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(_db_url, pool_size=10, max_overflow=20) if _db_url else None


class OrdersService:
    """CRUD operations for conditional orders against clax_conditional_orders."""

    def create(self, user_id: str, order) -> dict:
        query = text("""
            INSERT INTO clax_conditional_orders
                (user_id, ledger_id, ticker, action, condition_type, trigger_condition, trigger_value)
            VALUES
                (:user_id, :ledger_id, :ticker, :action, :condition_type, :trigger_condition, :trigger_value)
            RETURNING id, user_id, ledger_id, ticker, action, condition_type,
                      trigger_condition, trigger_value, status, is_active, created_at;
        """)
        with engine.begin() as conn:
            result = conn.execute(query, {
                "user_id": user_id,
                "ledger_id": order.ledger_id,
                "ticker": order.ticker,
                "action": order.action,
                "condition_type": order.condition_type,
                "trigger_condition": order.trigger_condition,
                "trigger_value": order.trigger_value,
            }).fetchone()
        return dict(result._mapping)

    def list_active(self, user_id: str) -> list[dict]:
        query = text(
            "SELECT * FROM clax_conditional_orders "
            "WHERE user_id = :user_id AND is_active = TRUE"
        )
        with engine.connect() as conn:
            results = conn.execute(query, {"user_id": user_id}).fetchall()
        return [dict(row._mapping) for row in results]

    def delete(self, user_id: str, order_id: str) -> dict:
        query = text(
            "DELETE FROM clax_conditional_orders "
            "WHERE id = :order_id AND user_id = :user_id "
            "RETURNING id"
        )
        with engine.begin() as conn:
            result = conn.execute(query, {
                "order_id": order_id,
                "user_id": user_id,
            }).fetchone()
        if not result:
            return None
        return {"message": "Order deleted", "id": result._mapping["id"]}
