"""Tests for the trade prevention service and router.

The SQLAlchemy engine is mocked — no database required.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.trade_prevention_schema import TradeExecutionRequest
from app.services.trade_prevention_service import TradePreventionService, DuplicateTradeError


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_trade_execution_request_fields(self):
        req = TradeExecutionRequest(symbol="AAPL", quantity=100, action="BUY")
        assert req.symbol == "AAPL"
        assert req.quantity == 100
        assert req.action == "BUY"


# ---------------------------------------------------------------------------
# Service tests (mocked engine)
# ---------------------------------------------------------------------------

class TestTradePreventionService:
    @patch("app.services.trade_prevention_service.engine")
    def test_no_duplicate_executes_trade(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # No duplicate found
        mock_conn.execute.return_value.fetchone.return_value = None

        svc = TradePreventionService()
        result = svc.execute_trade("user-1", "AAPL", 100, "BUY")

        assert result["status"] == "success"
        assert result["symbol"] == "AAPL"
        assert result["quantity"] == 100
        assert result["action"] == "BUY"
        assert result["trade_id"].startswith("trd_")
        assert 50.0 <= result["execution_price"] <= 150.0

    @patch("app.services.trade_prevention_service.engine")
    def test_duplicate_raises_error(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Duplicate found
        mock_conn.execute.return_value.fetchone.return_value = {"symbol": "AAPL"}

        svc = TradePreventionService()
        with pytest.raises(DuplicateTradeError) as exc_info:
            svc.execute_trade("user-1", "AAPL", 100, "BUY")

        assert exc_info.value.confirmation_token.startswith("conf_")
        assert exc_info.value.symbol == "AAPL"
        assert exc_info.value.quantity == 100

    @patch("app.services.trade_prevention_service.engine")
    def test_duplicate_query_uses_60s_window(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = None

        svc = TradePreventionService()
        svc.execute_trade("user-1", "AAPL", 100, "BUY")

        # Verify the duplicate check query was called with correct params
        calls = mock_conn.execute.call_args_list
        dup_query_call = calls[0]
        params = dup_query_call[0][1]
        assert params["uid"] == "user-1"
        assert params["sym"] == "AAPL"
        assert params["qty"] == 100
        assert params["act"] == "BUY"
        # ts should be now - 60
        import time
        expected_ts = time.time() - 60
        assert abs(params["ts"] - expected_ts) < 1

    @patch("app.services.trade_prevention_service.engine")
    def test_insert_query_executed(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = None

        svc = TradePreventionService()
        svc.execute_trade("user-1", "TSLA", 50, "SELL")

        # Second call should be the insert
        assert mock_conn.execute.call_count == 2
        insert_call = mock_conn.execute.call_args_list[1]
        insert_params = insert_call[0][1]
        assert insert_params["uid"] == "user-1"
        assert insert_params["sym"] == "TSLA"
        assert insert_params["qty"] == 50
        assert insert_params["act"] == "SELL"


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

class TestTradePreventionRouter:
    def test_router_has_one_route(self):
        from app.api.endpoints.routes.trade_prevention import trade_prevention_router

        routes = [r for r in trade_prevention_router.routes if hasattr(r, "methods")]
        assert len(routes) == 1
        assert routes[0].path == "/trades/execute"
        assert "POST" in routes[0].methods

    def test_router_uses_get_current_user(self):
        from app.api.endpoints.routes.trade_prevention import trade_prevention_router

        for route in trade_prevention_router.routes:
            if hasattr(route, "dependant"):
                dep_names = [
                    d.call.__name__
                    for d in route.dependant.dependencies
                    if hasattr(d.call, "__name__")
                ]
                if route.path == "/trades/execute" and "POST" in route.methods:
                    assert "get_current_user" in dep_names
