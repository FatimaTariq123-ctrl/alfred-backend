"""Tests for the orders service and router.

The SQLAlchemy engine is mocked — no database required.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.orders_schema import ConditionalOrderCreate
from app.services.orders_service import OrdersService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(**overrides) -> ConditionalOrderCreate:
    defaults = dict(
        ledger_id=None,
        ticker="AAPL",
        action="BUY",
        condition_type="PRICE_DROP_PERCENT",
        trigger_condition="price < 150",
        trigger_value=150.0,
    )
    defaults.update(overrides)
    return ConditionalOrderCreate(**defaults)


def _make_row(**overrides) -> dict:
    defaults = {
        "id": "row-1",
        "user_id": "user-123",
        "ledger_id": None,
        "ticker": "AAPL",
        "action": "BUY",
        "condition_type": "PRICE_DROP_PERCENT",
        "trigger_condition": "price < 150",
        "trigger_value": 150.0,
        "status": "PENDING",
        "is_active": True,
        "created_at": "2026-01-01T00:00:00",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_create_order_minimal(self):
        order = ConditionalOrderCreate(ticker="TSLA", action="SELL", condition_type="LIMIT", trigger_value=200.0)
        assert order.ticker == "TSLA"
        assert order.ledger_id is None
        assert order.trigger_condition is None

    def test_create_order_with_optional_fields(self):
        order = ConditionalOrderCreate(
            ledger_id="ledger-1",
            ticker="GOOG",
            action="BUY",
            condition_type="TAKE_PROFIT",
            trigger_condition="price > 300",
            trigger_value=300.0,
        )
        assert order.ledger_id == "ledger-1"
        assert order.trigger_condition == "price > 300"


# ---------------------------------------------------------------------------
# Service tests (mocked engine)
# ---------------------------------------------------------------------------

class TestOrdersServiceCreate:
    @patch("app.services.orders_service.engine")
    def test_create_returns_mapped_row(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result._mapping = _make_row(id="new-id")
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        svc = OrdersService()
        order = _make_order()
        result = svc.create("user-123", order)

        assert result["id"] == "new-id"
        assert result["ticker"] == "AAPL"
        mock_conn.execute.assert_called_once()

    @patch("app.services.orders_service.engine")
    def test_create_passes_all_fields(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result._mapping = _make_row()
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        svc = OrdersService()
        order = _make_order(ledger_id="L-99")
        svc.create("user-123", order)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["user_id"] == "user-123"
        assert params["ledger_id"] == "L-99"
        assert params["ticker"] == "AAPL"
        assert params["trigger_value"] == 150.0


class TestOrdersServiceListActive:
    @patch("app.services.orders_service.engine")
    def test_list_active_returns_rows(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        rows = [_make_row(id="r1"), _make_row(id="r2")]
        mock_conn.execute.return_value.fetchall.return_value = [MagicMock(_mapping=r) for r in rows]

        svc = OrdersService()
        result = svc.list_active("user-123")

        assert len(result) == 2
        assert result[0]["id"] == "r1"
        assert result[1]["id"] == "r2"

    @patch("app.services.orders_service.engine")
    def test_list_active_empty(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchall.return_value = []

        svc = OrdersService()
        result = svc.list_active("user-123")

        assert result == []


class TestOrdersServiceDelete:
    @patch("app.services.orders_service.engine")
    def test_delete_existing(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result._mapping = {"id": "order-1"}
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        svc = OrdersService()
        result = svc.delete("user-123", "order-1")

        assert result["message"] == "Order deleted"
        assert result["id"] == "order-1"

    @patch("app.services.orders_service.engine")
    def test_delete_not_found(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = None

        svc = OrdersService()
        result = svc.delete("user-123", "nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# Router integration tests (mocked service + auth)
# ---------------------------------------------------------------------------

class TestOrdersRouter:
    """Test the router by importing it and verifying it has the expected routes."""

    def test_router_has_three_routes(self):
        from app.api.endpoints.routes.orders import orders_router

        paths = set()
        for route in orders_router.routes:
            if hasattr(route, "methods"):
                for method in route.methods:
                    paths.add(f"{method} {route.path}")

        assert "POST /conditional_orders" in paths
        assert "GET /conditional_orders" in paths
        assert "DELETE /conditional_orders/{order_id}" in paths

    def test_router_uses_get_current_user(self):
        from app.api.endpoints.routes.orders import orders_router

        for route in orders_router.routes:
            if hasattr(route, "dependant"):
                dep_names = [
                    d.call.__name__
                    for d in route.dependant.dependencies
                    if hasattr(d.call, "__name__")
                ]
                if route.path == "/conditional_orders" and "POST" in route.methods:
                    assert "get_current_user" in dep_names
