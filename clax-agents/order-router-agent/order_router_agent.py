from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    REBALANCE = "REBALANCE"


class AssetClass(str, Enum):
    HK_EQUITY = "HK_EQUITY"
    US_EQUITY = "US_EQUITY"
    VIRTUAL_ASSET = "VIRTUAL_ASSET"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    CONDITIONAL = "CONDITIONAL"


class OrderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(..., min_length=1, max_length=20)
    asset_class: AssetClass
    action: OrderAction
    order_type: OrderType
    quantity: Optional[float] = Field(default=None, gt=0)
    cash_allocation: Optional[float] = Field(default=None, gt=0)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,20}", normalized):
            raise ValueError("ticker must be 1-20 characters and contain only letters, numbers, dots, underscores, or hyphens")
        if normalized.lower() in {"unknown", "none", "null"}:
            raise ValueError("ticker is invalid")
        return normalized

    @model_validator(mode="after")
    def validate_asset_rules(self) -> "OrderPayload":
        if self.quantity is not None:
            decimal_places = self._decimal_places(self.quantity)
            if self.asset_class in {AssetClass.US_EQUITY, AssetClass.HK_EQUITY}:
                if decimal_places != 0:
                    raise ValueError("quantity must be an integer for equity orders")
            elif decimal_places > 8:
                raise ValueError("quantity must have at most 8 decimal places for crypto orders")

        if self.cash_allocation is not None and self._decimal_places(self.cash_allocation) > 2:
            raise ValueError("cash_allocation must have at most 2 decimal places")

        return self

    @staticmethod
    def _decimal_places(value: float) -> int:
        decimal_value = Decimal(str(value))
        if decimal_value == decimal_value.to_integral():
            return 0
        return abs(decimal_value.as_tuple().exponent)

    def to_guardrail_payload(self, user_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "ticker": self.ticker,
            "asset_class": self.asset_class.value,
            "action": self.action.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "execution_price": None,
            "reference_price": None,
            "market_price": None,
            "market_timestamp": None,
            "user_cash_balance": None,
            "estimated_total": None,
            "is_simulation": True,
            "user_approved": False,
            "market_open": False,
            "restrictions": [],
            "metadata": {
                "source": "order-router-agent",
                "cash_allocation": self.cash_allocation,
            },
        }


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    message: str
    code: str


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    payload: Optional[OrderPayload] = None
    errors: list[ValidationIssue] = Field(default_factory=list)


class OrderRouterAgent:
    """Translate conversational trade intent into a strict structured order payload."""

    def __init__(self, llm_client: Optional[Any] = None) -> None:
        self.llm_client = llm_client

    def get_json_schema(self) -> dict[str, Any]:
        schema = OrderPayload.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        return schema

    def translate(self, user_text: str, user_id: Optional[str] = None) -> ValidationResult:
        text = (user_text or "").strip()
        if not text:
            return ValidationResult(valid=False, errors=[ValidationIssue(path="user_text", message="user_text is required", code="missing_required")])

        extracted_payload = self._extract_payload(text)
        if not extracted_payload:
            return ValidationResult(valid=False, errors=[ValidationIssue(path="llm_output", message="structured extraction failed", code="llm_extraction_failed")])

        try:
            payload = OrderPayload.model_validate(extracted_payload)
        except Exception as exc:  # pragma: no cover - pydantic errors detail is platform-specific
            errors = []
            if hasattr(exc, "errors"):
                for error in exc.errors():
                    field_path = ".".join(str(part) for part in error.get("loc", [])) or "payload"
                    errors.append(ValidationIssue(path=field_path, message=error.get("msg", "invalid value"), code=error.get("type", "validation_error")))
            else:
                errors.append(ValidationIssue(path="payload", message=str(exc), code="validation_error"))
            return ValidationResult(valid=False, errors=errors)

        return ValidationResult(valid=True, payload=payload)

    def _extract_payload(self, text: str) -> dict[str, Any] | None:
        llm_payload = self._call_llm_for_payload(text)
        if isinstance(llm_payload, dict):
            normalized = {
                "ticker": llm_payload.get("ticker"),
                "asset_class": llm_payload.get("asset_class"),
                "action": llm_payload.get("action"),
                "order_type": llm_payload.get("order_type"),
                "quantity": llm_payload.get("quantity"),
                "cash_allocation": llm_payload.get("cash_allocation"),
            }
            return {key: value for key, value in normalized.items() if value is not None}

        return self._fallback_extract_payload(text)

    def _fallback_extract_payload(self, text: str) -> dict[str, Any] | None:
        action = self._detect_action(text)
        if not action:
            return None

        ticker = self._detect_ticker(text)
        if not ticker:
            return None

        asset_class = self._detect_asset_class(text, ticker)
        if not asset_class:
            return None

        quantity = self._detect_quantity(text)
        if quantity is None:
            quantity = 1

        order_type = self._detect_order_type(text)
        if not order_type:
            order_type = "MARKET"

        return {
            "ticker": ticker,
            "asset_class": asset_class,
            "action": action,
            "order_type": order_type,
            "quantity": quantity,
        }

    def _detect_action(self, text: str) -> Optional[str]:
        lower = text.lower()
        if re.search(r"\bbuy\b", lower):
            return "BUY"
        if re.search(r"\bsell\b", lower):
            return "SELL"
        if re.search(r"\brebalance\b", lower):
            return "REBALANCE"
        return None

    def _detect_order_type(self, text: str) -> Optional[str]:
        lower = text.lower()
        if "limit" in lower:
            return "LIMIT"
        if "conditional" in lower:
            return "CONDITIONAL"
        if "market" in lower:
            return "MARKET"
        if "stop" in lower:
            return "STOP"
        return None

    def _detect_quantity(self, text: str) -> Optional[float]:
        explicit_match = re.search(r"(?:^|\b)(?:shares?|units?|qty|quantity|amount|lots?)\s+(\d+(?:\.\d+)?)\b", text, re.IGNORECASE)
        if explicit_match:
            return float(explicit_match.group(1))

        direct_match = re.search(r"(?:^|\b)(buy|sell|rebalance)\s+(\d+(?:\.\d+)?)(?![A-Za-z0-9._-])", text, re.IGNORECASE)
        if direct_match:
            return float(direct_match.group(2))

        return None

    def _detect_ticker(self, text: str) -> Optional[str]:
        tokens = re.findall(r"[A-Za-z0-9._-]+", text)
        stopwords = {
            "buy",
            "sell",
            "rebalance",
            "at",
            "market",
            "limit",
            "conditional",
            "share",
            "shares",
            "stock",
            "stocks",
            "equity",
            "equities",
            "of",
            "for",
            "hk",
            "hkd",
        }
        for token in tokens:
            normalized = token.strip().upper()
            if not normalized or normalized.lower() in stopwords:
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", normalized):
                continue
            if re.fullmatch(r"[A-Za-z0-9._-]{1,20}", normalized) and normalized.lower() not in {"unknown", "none", "null"}:
                return normalized
        return None

    def _detect_asset_class(self, text: str, ticker: str) -> Optional[str]:
        lower_ticker = ticker.lower()
        if lower_ticker.endswith(".hk") or re.fullmatch(r"\d{1,5}", ticker) and ("hk" in text.lower() or "equity" in text.lower()):
            return AssetClass.HK_EQUITY.value

        if lower_ticker in {"btc", "eth", "xbt", "ada", "sol", "doge", "ltc", "bnb", "dot"}:
            return AssetClass.VIRTUAL_ASSET.value

        allowed_equities = {
            "AAPL",
            "MSFT",
            "NVDA",
            "TSLA",
            "AMZN",
            "GOOG",
            "GOOGL",
            "META",
            "AMD",
            "NFLX",
            "IBM",
            "KO",
            "INTC",
            "BAC",
            "JPM",
            "V",
            "MA",
            "WMT",
            "DIS",
            "ORCL",
            "HSBC",
            "0700",
            "0005",
        }
        if ticker.upper() in allowed_equities:
            return AssetClass.US_EQUITY.value

        return "FOREX"

    def _call_llm_for_payload(self, text: str) -> dict[str, Any] | None:
        if self.llm_client is not None:
            raw_response = self.llm_client(text)
            if isinstance(raw_response, dict):
                return raw_response
            if isinstance(raw_response, str):
                try:
                    parsed = json.loads(raw_response)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
            if hasattr(raw_response, "json"):
                try:
                    parsed = raw_response.json()
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
            return None

        return self._call_gemini(text)

    def _call_gemini(self, text: str) -> dict[str, Any] | None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        prompt = self._build_prompt(text)
        schema = self.get_json_schema()
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        try:
            response = requests.post(endpoint, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            if isinstance(raw_text, dict):
                return raw_text
            if isinstance(raw_text, str):
                parsed = json.loads(raw_text)
                return parsed if isinstance(parsed, dict) else None
            return None
        except Exception:
            return None

    def _build_prompt(self, text: str) -> str:
        schema = json.dumps(self.get_json_schema(), indent=2)
        return (
            "You are an order router. Convert the user's natural-language order intent into a strict JSON object that matches the schema below. "
            "Return only JSON. Do not include commentary or markdown.\n\n"
            f"User request: {text}\n\n"
            f"Schema:\n{schema}"
        )
