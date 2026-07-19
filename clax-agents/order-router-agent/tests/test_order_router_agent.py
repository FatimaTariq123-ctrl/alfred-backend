import json as json_module
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import order_router_agent as router_module
from order_router_agent import OrderRouterAgent


class StubLLMClient:
    def __init__(self, payload):
        self.payload = payload

    def __call__(self, _text):
        return self.payload


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_buy_order_with_us_equity_payload():
    agent = OrderRouterAgent(llm_client=StubLLMClient({"ticker": "AAPL", "asset_class": "US_EQUITY", "action": "BUY", "order_type": "MARKET", "quantity": 10}))
    result = agent.translate("Buy 10 shares of AAPL")
    assert result.valid is True
    assert result.payload is not None
    assert result.payload.ticker == "AAPL"
    assert result.payload.asset_class == "US_EQUITY"
    assert result.payload.action == "BUY"
    assert result.payload.order_type == "MARKET"
    assert result.payload.quantity == 10


def test_sell_order_with_crypto_payload():
    agent = OrderRouterAgent(llm_client=StubLLMClient({"ticker": "BTC", "asset_class": "VIRTUAL_ASSET", "action": "SELL", "order_type": "LIMIT", "quantity": 0.25}))
    result = agent.translate("Sell 0.25 BTC at $60000 limit")
    assert result.valid is True
    assert result.payload is not None
    assert result.payload.ticker == "BTC"
    assert result.payload.asset_class == "VIRTUAL_ASSET"
    assert result.payload.action == "SELL"
    assert result.payload.order_type == "LIMIT"
    assert result.payload.quantity == 0.25


def test_hk_equity_payload_is_supported():
    agent = OrderRouterAgent(llm_client=StubLLMClient({"ticker": "0005", "asset_class": "HK_EQUITY", "action": "BUY", "order_type": "LIMIT", "quantity": 100}))
    result = agent.translate("Buy 100 shares of HSBC")
    assert result.valid is True
    assert result.payload is not None
    assert result.payload.asset_class == "HK_EQUITY"


def test_rule_based_fallback_parses_plain_trade_request():
    agent = OrderRouterAgent()
    result = agent.translate("Buy 10 AAPL at market")
    assert result.valid is True
    assert result.payload is not None
    assert result.payload.ticker == "AAPL"
    assert result.payload.asset_class == "US_EQUITY"
    assert result.payload.action == "BUY"
    assert result.payload.order_type == "MARKET"
    assert result.payload.quantity == 10


def test_missing_required_fields_fail():
    agent = OrderRouterAgent(llm_client=StubLLMClient({"ticker": "AAPL", "asset_class": "US_EQUITY"}))
    result = agent.translate("Buy AAPL")
    assert result.valid is False
    assert any(error.path == "action" for error in result.errors)
    assert any(error.path == "order_type" for error in result.errors)


def test_invalid_asset_class_fails():
    agent = OrderRouterAgent(llm_client=StubLLMClient({"ticker": "AAPL", "asset_class": "FOREX", "action": "BUY", "order_type": "MARKET", "quantity": 10}))
    result = agent.translate("Buy 10 AAPL")
    assert result.valid is False
    assert any(error.code == "enum" for error in result.errors)


def test_invalid_quantity_fails():
    agent = OrderRouterAgent(llm_client=StubLLMClient({"ticker": "AAPL", "asset_class": "US_EQUITY", "action": "BUY", "order_type": "MARKET", "quantity": 0}))
    result = agent.translate("Buy 0 AAPL")
    assert result.valid is False
    assert any(error.path == "quantity" for error in result.errors)


def test_invalid_order_type_fails():
    agent = OrderRouterAgent(llm_client=StubLLMClient({"ticker": "AAPL", "asset_class": "US_EQUITY", "action": "BUY", "order_type": "STOP", "quantity": 10}))
    result = agent.translate("Buy 10 AAPL")
    assert result.valid is False
    assert any(error.path == "order_type" for error in result.errors)


def test_router_uses_project_gemini_client(monkeypatch):
    def fake_post(url, json=None, timeout=30):
        assert "gemini" in url
        assert json["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseSchema" in json["generationConfig"]
        return FakeResponse(
            {
                "candidates": [
                    {"content": {"parts": [{"text": json_module.dumps({"ticker": "AAPL", "asset_class": "US_EQUITY", "action": "BUY", "order_type": "MARKET", "quantity": 10})}]}}
                ]
            }
        )

    monkeypatch.setattr(router_module.requests, "post", fake_post)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    agent = OrderRouterAgent()
    result = agent.translate("Buy 10 AAPL")
    assert result.valid is True
    assert result.payload is not None
    assert result.payload.ticker == "AAPL"


def test_json_schema_exposed():
    agent = OrderRouterAgent()
    schema = agent.get_json_schema()
    assert "$schema" in schema
    assert schema["properties"]["ticker"]
    assert schema["properties"]["asset_class"]
