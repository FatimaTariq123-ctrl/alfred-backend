"""Tests for the compliance service and router.

The SQLAlchemy engine and Redis client are mocked — no infrastructure required.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.compliance_schema import VetoRequest
from app.services.compliance_service import ComplianceService, VETO_STATUS_CODES, VALID_VETO_TYPES


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_veto_request_fields(self):
        req = VetoRequest(ledger_id="L-1", veto_type="SANCTIONS_MATCH", veto_reason="OFAC hit")
        assert req.ledger_id == "L-1"
        assert req.veto_type == "SANCTIONS_MATCH"
        assert req.veto_reason == "OFAC hit"


# ---------------------------------------------------------------------------
# Service tests (mocked engine + Redis)
# ---------------------------------------------------------------------------

class TestComplianceServiceApplyVeto:
    @patch("app.services.compliance_service._get_redis", return_value=None)
    @patch("app.services.compliance_service.engine")
    def test_sanctions_match_returns_403(self, mock_engine, mock_redis):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = ComplianceService()
        result = svc.apply_veto("L-1", "SANCTIONS_MATCH", "OFAC hit")

        assert result["status"] == "VETOED"
        assert result["veto_type"] == "SANCTIONS_MATCH"
        assert result["ui_card"]["title"] == "Trade Blocked (Compliance)"
        assert VETO_STATUS_CODES[result["veto_type"]] == 403

    @patch("app.services.compliance_service._get_redis", return_value=None)
    @patch("app.services.compliance_service.engine")
    def test_wash_trade_returns_422(self, mock_engine, mock_redis):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = ComplianceService()
        result = svc.apply_veto("L-2", "WASH_TRADE", "Suspicious pattern")

        assert result["veto_type"] == "WASH_TRADE"
        assert VETO_STATUS_CODES[result["veto_type"]] == 422

    @patch("app.services.compliance_service._get_redis", return_value=None)
    @patch("app.services.compliance_service.engine")
    def test_pattern_violation_returns_422(self, mock_engine, mock_redis):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = ComplianceService()
        result = svc.apply_veto("L-3", "PATTERN_VIOLATION", "Wash trade detected")

        assert result["veto_type"] == "PATTERN_VIOLATION"
        assert VETO_STATUS_CODES[result["veto_type"]] == 422

    @patch("app.services.compliance_service._get_redis", return_value=None)
    @patch("app.services.compliance_service.engine")
    def test_invalid_veto_type_raises(self, mock_engine, mock_redis):
        svc = ComplianceService()
        with pytest.raises(ValueError, match="Invalid veto_type"):
            svc.apply_veto("L-1", "INVALID_TYPE", "bad")

    @patch("app.services.compliance_service._get_redis", return_value=None)
    @patch("app.services.compliance_service.engine")
    def test_db_writes_called(self, mock_engine, mock_redis):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = ComplianceService()
        svc.apply_veto("L-1", "SANCTIONS_MATCH", "OFAC hit")

        # Two SQL statements executed in the transaction
        assert mock_conn.execute.call_count == 2

    @patch("app.services.compliance_service._get_redis")
    @patch("app.services.compliance_service.engine")
    def test_redis_lock_released(self, mock_engine, mock_get_redis):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        svc = ComplianceService()
        svc.apply_veto("L-1", "SANCTIONS_MATCH", "OFAC hit")

        mock_redis.delete.assert_called_once_with("trade_lock_L-1")

    @patch("app.services.compliance_service._get_redis")
    @patch("app.services.compliance_service.engine")
    def test_redis_failure_does_not_propagate(self, mock_engine, mock_get_redis):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis = MagicMock()
        mock_redis.delete.side_effect = ConnectionError("Redis down")
        mock_get_redis.return_value = mock_redis

        svc = ComplianceService()
        # Should NOT raise — Redis failure is best-effort
        result = svc.apply_veto("L-1", "SANCTIONS_MATCH", "OFAC hit")
        assert result["status"] == "VETOED"


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

class TestComplianceRouter:
    def test_router_has_one_route(self):
        from app.api.endpoints.routes.compliance import compliance_router

        routes = [r for r in compliance_router.routes if hasattr(r, "methods")]
        assert len(routes) == 1
        assert routes[0].path == "/compliance/veto"
        assert "POST" in routes[0].methods

    def test_status_code_mapping(self):
        assert VETO_STATUS_CODES["SANCTIONS_MATCH"] == 403
        assert VETO_STATUS_CODES["WASH_TRADE"] == 422
        assert VETO_STATUS_CODES["PATTERN_VIOLATION"] == 422

    def test_valid_veto_types(self):
        assert VALID_VETO_TYPES == {"SANCTIONS_MATCH", "WASH_TRADE", "PATTERN_VIOLATION"}
