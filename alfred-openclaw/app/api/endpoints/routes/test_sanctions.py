"""Tests for the sanctions service and router.

The SQLAlchemy engine is mocked — no database required.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.sanctions_schema import SanctionEntity
from app.services.sanctions_service import SanctionsService


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_sanction_entity_fields(self):
        entity = SanctionEntity(ticker="OFAC-XYZ", name="Blocked Corp", regulatory_body="OFAC")
        assert entity.ticker == "OFAC-XYZ"
        assert entity.name == "Blocked Corp"
        assert entity.regulatory_body == "OFAC"


# ---------------------------------------------------------------------------
# Service tests (mocked engine)
# ---------------------------------------------------------------------------

class TestSanctionsServiceUpsert:
    @patch("app.services.sanctions_service.engine")
    def test_upsert_returns_mapped_row(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result._mapping = {"ticker": "OFAC-XYZ", "name": "Blocked Corp", "regulatory_body": "OFAC"}
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        svc = SanctionsService()
        result = svc.upsert("OFAC-XYZ", "Blocked Corp", "OFAC")

        assert result["ticker"] == "OFAC-XYZ"
        assert result["name"] == "Blocked Corp"
        mock_conn.execute.assert_called_once()

    @patch("app.services.sanctions_service.engine")
    def test_upsert_passes_all_params(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result._mapping = {"ticker": "HK-ALERT", "name": "Unlicensed Broker", "regulatory_body": "SFC"}
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        svc = SanctionsService()
        svc.upsert("HK-ALERT", "Unlicensed Broker", "SFC")

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["ticker"] == "HK-ALERT"
        assert params["name"] == "Unlicensed Broker"
        assert params["regulatory_body"] == "SFC"


class TestSanctionsServiceGetByTicker:
    @patch("app.services.sanctions_service.engine")
    def test_get_existing_ticker(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result._mapping = {"ticker": "OFAC-XYZ", "name": "Blocked Corp", "regulatory_body": "OFAC"}
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        svc = SanctionsService()
        result = svc.get_by_ticker("OFAC-XYZ")

        assert result["data"]["ticker"] == "OFAC-XYZ"
        assert "lookup_time_ms" in result
        assert result["lookup_time_ms"] >= 0

    @patch("app.services.sanctions_service.engine")
    def test_get_nonexistent_ticker(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.return_value.fetchone.return_value = None

        svc = SanctionsService()
        result = svc.get_by_ticker("NONEXISTENT")

        assert result is None


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

class TestSanctionsRouter:
    def test_router_has_two_routes(self):
        from app.api.endpoints.routes.sanctions import sanctions_router

        routes = [r for r in sanctions_router.routes if hasattr(r, "methods")]
        assert len(routes) == 2

    def test_routes_have_correct_paths(self):
        from app.api.endpoints.routes.sanctions import sanctions_router

        paths = set()
        for route in sanctions_router.routes:
            if hasattr(route, "methods"):
                for method in route.methods:
                    paths.add(f"{method} {route.path}")

        assert "POST /admin/blacklist" in paths
        assert "GET /admin/blacklist/{ticker}" in paths

    def test_router_uses_get_current_user(self):
        from app.api.endpoints.routes.sanctions import sanctions_router

        for route in sanctions_router.routes:
            if hasattr(route, "dependant"):
                dep_names = [
                    d.call.__name__
                    for d in route.dependant.dependencies
                    if hasattr(d.call, "__name__")
                ]
                assert "get_current_user" in dep_names
