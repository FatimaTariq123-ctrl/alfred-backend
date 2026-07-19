"""Tests for the trade status service and router.

Redis client is mocked — no infrastructure required.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.trade_status_schema import TradeState, TradeStatusResponse
from app.services.trade_status_service import TradeStatusService


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_trade_state_values(self):
        assert TradeState.PROCESSING == "PROCESSING"
        assert TradeState.RECONCILING == "RECONCILING"
        assert TradeState.SUCCESS == "SUCCESS"
        assert TradeState.FAILED == "FAILED"
        assert TradeState.VETOED == "VETOED"

    def test_trade_status_response_fields(self):
        resp = TradeStatusResponse(
            idempotency_key="key-1",
            status=TradeState.SUCCESS,
            source="redis",
            payload={"result": "ok"},
        )
        assert resp.idempotency_key == "key-1"
        assert resp.status == TradeState.SUCCESS
        assert resp.source == "redis"
        assert resp.payload == {"result": "ok"}

    def test_trade_status_response_optional_payload(self):
        resp = TradeStatusResponse(
            idempotency_key="key-2",
            status=TradeState.PROCESSING,
            source="postgresql",
        )
        assert resp.payload is None


# ---------------------------------------------------------------------------
# Service tests (mocked Redis + engine)
# ---------------------------------------------------------------------------

class TestTradeStatusService:
    @patch("app.services.trade_status_service.engine")
    def test_redis_cache_hit(self, mock_engine):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"SUCCESS"

        svc = TradeStatusService(mock_redis)
        result = svc.get_status("user-1", "key-1")

        assert result.idempotency_key == "key-1"
        assert result.status == TradeState.SUCCESS
        assert result.source == "redis"
        assert result.payload is None

    @patch("app.services.trade_status_service.engine")
    def test_redis_cache_miss_falls_back_to_db(self, mock_engine):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        mock_row = MagicMock()
        mock_row.status = "FAILED"
        mock_row.payload = {"error": "timeout"}

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        svc = TradeStatusService(mock_redis)
        result = svc.get_status("user-1", "key-1")

        assert result.idempotency_key == "key-1"
        assert result.status == TradeState.FAILED
        assert result.source == "postgresql"
        assert result.payload == {"error": "timeout"}

    @patch("app.services.trade_status_service.engine")
    def test_not_found_returns_none(self, mock_engine):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        svc = TradeStatusService(mock_redis)
        result = svc.get_status("user-1", "nonexistent")

        assert result is None

    @patch("app.services.trade_status_service.engine")
    def test_redis_key_format(self, mock_engine):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"PROCESSING"

        svc = TradeStatusService(mock_redis)
        svc.get_status("user-42", "idem-99")

        mock_redis.get.assert_called_once_with("idempotency:user-42:idem-99")


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

class TestTradeStatusRouter:
    def test_router_has_one_route(self):
        from app.api.endpoints.routes.trade_status import trade_status_router

        routes = [r for r in trade_status_router.routes if hasattr(r, "methods")]
        assert len(routes) == 1
        assert routes[0].path == "/trade/status"
        assert "GET" in routes[0].methods

    def test_router_uses_get_current_user(self):
        from app.api.endpoints.routes.trade_status import trade_status_router

        for route in trade_status_router.routes:
            if hasattr(route, "dependant"):
                dep_names = [
                    d.call.__name__
                    for d in route.dependant.dependencies
                    if hasattr(d.call, "__name__")
                ]
                if route.path == "/trade/status" and "GET" in route.methods:
                    assert "get_current_user" in dep_names
