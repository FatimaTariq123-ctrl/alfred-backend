from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Decision(str, Enum):
    APPROVE = "APPROVE"
    BLOCK = "BLOCK"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    BLOCK_WITH_REASON = "BLOCK_WITH_REASON"


class ReasonCode(str, Enum):
    APPROVED = "APPROVED"
    MARKET_CLOSED = "MARKET_CLOSED"
    REAL_EXECUTION_BLOCKED = "REAL_EXECUTION_BLOCKED"
    USER_CONFIRMATION_REQUIRED = "USER_CONFIRMATION_REQUIRED"
    STALE_PRICE = "STALE_PRICE"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    RESTRICTED_ASSET = "RESTRICTED_ASSET"
    SLIPPAGE_EXCEEDED = "SLIPPAGE_EXCEEDED"


@dataclass
class ActionRequest:
    """Structured execution action request evaluated before ledger or execution handoff."""

    user_id: Optional[str] = None
    ticker: Optional[str] = None
    asset_class: Optional[str] = None
    action: Optional[str] = None
    quantity: Optional[float] = None
    order_type: Optional[str] = None
    execution_price: Optional[float] = None
    reference_price: Optional[float] = None
    market_price: Optional[float] = None
    market_timestamp: Any = None
    user_cash_balance: Optional[float] = None
    estimated_total: Optional[float] = None
    is_simulation: bool = True
    user_approved: bool = False
    market_open: bool = False
    restrictions: Any = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ActionRequest":
        known_fields = set(cls.__dataclass_fields__)
        values = {key: payload.get(key) for key in known_fields if key in payload}
        extra = {key: value for key, value in payload.items() if key not in known_fields}
        raw_metadata = values.get("metadata") or {}
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {"raw_metadata": raw_metadata}
        if extra:
            metadata["extra_payload_fields"] = extra
        values["metadata"] = metadata
        return cls(**values)


class GuardrailGuardAgent:
    """Deterministic execution firewall for simulated trade requests."""

    DEFAULT_PRICE_STALE_SECONDS = 60
    DEFAULT_SLIPPAGE_THRESHOLDS = {
        "HK_EQUITY": 0.02,
        "US_EQUITY": 0.02,
        "VIRTUAL_ASSET": 0.05,
    }

    def __init__(
        self,
        stale_price_seconds: int = DEFAULT_PRICE_STALE_SECONDS,
        slippage_thresholds: Optional[dict[str, float]] = None,
    ) -> None:
        self.stale_price_seconds = stale_price_seconds
        self.slippage_thresholds = {
            **self.DEFAULT_SLIPPAGE_THRESHOLDS,
            **(slippage_thresholds or {}),
        }

    def validate_market_open(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        if request.market_open is not True:
            return self._failed_check(
                ReasonCode.MARKET_CLOSED,
                "Market is closed for this action request.",
            )
        return None

    def validate_simulation_only(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        if request.is_simulation is not True:
            return self._failed_check(
                ReasonCode.REAL_EXECUTION_BLOCKED,
                "Real execution or missing simulation status is blocked. Guardrail Guard MVP allows simulation only.",
            )
        return None

    def validate_user_approval(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        if request.user_approved is not True:
            return self._failed_check(
                ReasonCode.USER_CONFIRMATION_REQUIRED,
                "User approval is required before simulated execution can continue.",
            )
        return None

    def validate_price_freshness(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        market_time = self._parse_timestamp(request.market_timestamp)
        if market_time is None:
            return self._failed_check(
                ReasonCode.STALE_PRICE,
                "Market timestamp is missing or invalid.",
            )

        age_seconds = (datetime.now(timezone.utc) - market_time).total_seconds()
        if age_seconds < 0:
            age_seconds = 0
        if age_seconds > self.stale_price_seconds:
            return self._failed_check(
                ReasonCode.STALE_PRICE,
                f"Market price is stale: {age_seconds:.1f}s old, threshold is {self.stale_price_seconds}s.",
                {"age_seconds": age_seconds, "threshold_seconds": self.stale_price_seconds},
            )
        return None

    def validate_balance(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        if (request.action or "").upper() != "BUY":
            return None
        if request.estimated_total is None or request.user_cash_balance is None:
            return self._failed_check(
                ReasonCode.INSUFFICIENT_BALANCE,
                "BUY requests require estimated_total and user_cash_balance.",
            )
        estimated_total = self._to_float(request.estimated_total)
        user_cash_balance = self._to_float(request.user_cash_balance)
        if estimated_total is None or user_cash_balance is None:
            return self._failed_check(
                ReasonCode.INSUFFICIENT_BALANCE,
                "BUY requests require numeric estimated_total and user_cash_balance.",
            )
        if estimated_total > user_cash_balance:
            return self._failed_check(
                ReasonCode.INSUFFICIENT_BALANCE,
                "Estimated total exceeds available user cash balance.",
                {
                    "estimated_total": estimated_total,
                    "user_cash_balance": user_cash_balance,
                },
            )
        return None

    def validate_restricted_asset(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        ticker = (request.ticker or "").upper()
        restricted_tickers = self._extract_restricted_tickers(request.restrictions)
        if ticker and ticker in restricted_tickers:
            return self._failed_check(
                ReasonCode.RESTRICTED_ASSET,
                f"{ticker} is restricted for this request.",
                {"restricted_tickers": sorted(restricted_tickers)},
            )
        return None

    def validate_slippage(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        comparison_price = request.reference_price or request.market_price
        if request.execution_price is None or comparison_price is None:
            return self._failed_check(
                ReasonCode.SLIPPAGE_EXCEEDED,
                "Slippage check requires execution_price and reference_price or market_price.",
            )
        execution_price = self._to_float(request.execution_price)
        comparison_price = self._to_float(comparison_price)
        if execution_price is None or comparison_price is None:
            return self._failed_check(
                ReasonCode.SLIPPAGE_EXCEEDED,
                "Slippage check requires numeric execution and comparison prices.",
            )
        if comparison_price <= 0:
            return self._failed_check(
                ReasonCode.SLIPPAGE_EXCEEDED,
                "Reference or market price must be greater than zero.",
            )

        deviation = abs(execution_price - comparison_price) / comparison_price
        threshold = self._slippage_threshold_for(request.asset_class)
        if deviation > threshold:
            return self._failed_check(
                ReasonCode.SLIPPAGE_EXCEEDED,
                "Execution price deviation exceeds the configured threshold.",
                {
                    "deviation": deviation,
                    "threshold": threshold,
                    "comparison_price": comparison_price,
                    "execution_price": execution_price,
                },
            )
        return None

    def evaluate(self, payload: dict[str, Any] | ActionRequest) -> dict[str, Any]:
        request = payload if isinstance(payload, ActionRequest) else ActionRequest.from_payload(payload)

        hard_checks = [
            self.validate_market_open,
            self.validate_simulation_only,
            self.validate_price_freshness,
            self.validate_balance,
            self.validate_restricted_asset,
            self.validate_slippage,
        ]
        failed_checks = [check for validator in hard_checks if (check := validator(request))]

        approval_check = self.validate_user_approval(request)
        if approval_check:
            failed_checks.append(approval_check)

        hard_failures = [
            check
            for check in failed_checks
            if check["reason_code"] != ReasonCode.USER_CONFIRMATION_REQUIRED.value
        ]
        if hard_failures:
            first_failure = hard_failures[0]
            return self._decision_payload(
                Decision.BLOCK_WITH_REASON,
                False,
                first_failure["reason_code"],
                first_failure["reason"],
                failed_checks,
                request,
            )

        if approval_check:
            return self._decision_payload(
                Decision.REQUIRE_CONFIRMATION,
                False,
                ReasonCode.USER_CONFIRMATION_REQUIRED.value,
                approval_check["reason"],
                failed_checks,
                request,
            )

        return self._decision_payload(
            Decision.APPROVE,
            True,
            ReasonCode.APPROVED.value,
            "All guardrail checks passed.",
            [],
            request,
        )

    def _decision_payload(
        self,
        decision: Decision,
        approved: bool,
        reason_code: str,
        reason: str,
        failed_checks: list[dict[str, Any]],
        request: ActionRequest,
    ) -> dict[str, Any]:
        return {
            "decision": decision.value,
            "approved": approved,
            "reason_code": reason_code,
            "reason": reason,
            "failed_checks": failed_checks,
            "metadata": {
                "agent": "guardrail-guard-agent",
                "user_id": request.user_id,
                "ticker": request.ticker,
                "asset_class": request.asset_class,
                "is_simulation": request.is_simulation,
                "stale_price_seconds": self.stale_price_seconds,
                "slippage_thresholds": self.slippage_thresholds,
                **request.metadata,
            },
        }

    def _failed_check(
        self,
        reason_code: ReasonCode,
        reason: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return {
            "check": reason_code.value.lower(),
            "reason_code": reason_code.value,
            "reason": reason,
            "metadata": metadata or {},
        }

    def _slippage_threshold_for(self, asset_class: Optional[str]) -> float:
        return self.slippage_thresholds.get((asset_class or "").upper(), 0.02)

    def _to_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        elif isinstance(value, str):
            normalized = value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                try:
                    parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
                except ValueError:
                    return None
        else:
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _extract_restricted_tickers(self, restrictions: Any) -> set[str]:
        if not restrictions:
            return set()
        if isinstance(restrictions, str):
            return {restrictions.upper()}
        if isinstance(restrictions, dict):
            candidates = []
            for key in ("tickers", "restricted_tickers", "assets", "symbols"):
                value = restrictions.get(key)
                if isinstance(value, list):
                    candidates.extend(value)
                elif isinstance(value, str):
                    candidates.append(value)
            return {str(item).upper() for item in candidates}
        if isinstance(restrictions, list):
            tickers = set()
            for item in restrictions:
                if isinstance(item, str):
                    tickers.add(item.upper())
                elif isinstance(item, dict):
                    for key in ("ticker", "symbol", "asset"):
                        if item.get(key):
                            tickers.add(str(item[key]).upper())
            return tickers
        return set()


def run_guardrail_guard(action_request: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a structured action request and return a decision payload."""

    return GuardrailGuardAgent().evaluate(action_request)


def _base_test_payload() -> dict[str, Any]:
    return {
        "user_id": "user-123",
        "ticker": "AAPL",
        "asset_class": "US_EQUITY",
        "action": "BUY",
        "quantity": 2,
        "order_type": "MARKET",
        "execution_price": 100.5,
        "reference_price": 100.0,
        "market_price": 100.0,
        "market_timestamp": datetime.now(timezone.utc).isoformat(),
        "user_cash_balance": 1000.0,
        "estimated_total": 201.0,
        "is_simulation": True,
        "user_approved": True,
        "market_open": True,
        "restrictions": [],
    }


if __name__ == "__main__":
    agent = GuardrailGuardAgent()
    stale_market_timestamp = time.time() - 120

    test_cases = {
        "Valid simulated approved trade": _base_test_payload(),
        "Missing user approval": {
            key: value for key, value in _base_test_payload().items() if key != "user_approved"
        },
        "Market closed": {**_base_test_payload(), "market_open": False},
        "Real execution attempt": {**_base_test_payload(), "is_simulation": False},
        "Stale price": {**_base_test_payload(), "market_timestamp": stale_market_timestamp},
        "Insufficient balance": {
            **_base_test_payload(),
            "estimated_total": 1200.0,
            "user_cash_balance": 1000.0,
        },
        "Restricted ticker": {**_base_test_payload(), "restrictions": ["AAPL"]},
        "Excessive slippage": {**_base_test_payload(), "execution_price": 104.0},
    }

    for name, payload in test_cases.items():
        result = agent.evaluate(payload)
        print("=" * 50)
        print(f"TEST: {name}")
        print(f"DECISION: {result['decision']}")
        print(f"REASON: {result['reason']}")
        print("PAYLOAD:")
        print(json.dumps(result, indent=2))
    print("=" * 50)
