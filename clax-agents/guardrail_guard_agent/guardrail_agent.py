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

    def validate_restricted_asset(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        ticker = (request.ticker or "").upper()
        
        # 1. Check hardcoded SFC sanctions
        banned_tokens = {"TORN", "XMR", "ZEC"}
        if ticker in banned_tokens:
            return self._failed_check(
                ReasonCode.RESTRICTED_ASSET,
                f"Asset {request.ticker} is currently restricted under SFC compliance rules.",
                {"source": "sfc_sanctions", "banned_tokens": sorted(banned_tokens)}
            )
            
        # 2. Check dynamic restricted assets from the request
        restricted_tickers = self._extract_restricted_tickers(request.restrictions)
        if ticker and ticker in restricted_tickers:
            return self._failed_check(
                ReasonCode.RESTRICTED_ASSET,
                f"{ticker} is restricted for this request.",
                {"restricted_tickers": sorted(restricted_tickers)},
            )
        return None

    def validate_macro_sectors(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        blocked_sectors = request.metadata.get("blocked_sectors", [])
        sector_map = {"0700.HK": "TECH", "0005.HK": "FINANCE", "XOM": "ENERGY"}
        asset_sector = sector_map.get((request.ticker or "").upper())
        
        if asset_sector and asset_sector in blocked_sectors:
            return self._failed_check(
                ReasonCode.RESTRICTED_ASSET,
                f"Asset {request.ticker} is in a restricted sector ({asset_sector}) based on current Macro conditions.",
            )
        return None

    def validate_investor_dna(self, request: ActionRequest) -> Optional[dict[str, Any]]:
        risk_tier = request.metadata.get("risk_tier", "Ambitious Builder")
        high_risk_assets = {"DOGE", "SHIB", "PEPE"}
        
        if risk_tier in {"Guided Starter", "Steady Builder"} and (request.ticker or "").upper() in high_risk_assets:
            return self._failed_check(
                ReasonCode.RESTRICTED_ASSET,
                f"Asset {request.ticker} exceeds your current Investor DNA risk profile ({risk_tier}).",
            )
        return None

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

    def evaluate(self, payload: dict[str, Any] | ActionRequest) -> dict[str, Any]:
        request = payload if isinstance(payload, ActionRequest) else ActionRequest.from_payload(payload)

        hard_checks = [
            self.validate_restricted_asset,
            self.validate_macro_sectors,
            self.validate_investor_dna,
            self.validate_market_open,
            self.validate_simulation_only,
            self.validate_slippage
        ]
        failed_checks = [check for validator in hard_checks if (check := validator(request))]

        if failed_checks:
            first_failure = failed_checks[0]
            return self._decision_payload(
                Decision.BLOCK_WITH_REASON,
                False,
                first_failure["reason_code"],
                first_failure["reason"],
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

    def _decision_payload(self, decision: Decision, approved: bool, reason_code: str, reason: str, failed_checks: list[dict[str, Any]], request: ActionRequest) -> dict[str, Any]:
        return {
            "decision": decision.value,
            "approved": approved,
            "reason_code": reason_code,
            "reason": reason,
            "failed_checks": failed_checks,
            "metadata": {
                "agent": "guardrail-guard-agent",
                **request.metadata,
            },
        }

    def _failed_check(self, reason_code: ReasonCode, reason: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {
            "check": reason_code.value.lower(),
            "reason_code": reason_code.value,
            "reason": reason,
            "metadata": metadata or {},
        }

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

    def _slippage_threshold_for(self, asset_class: Optional[str]) -> float:
        return self.slippage_thresholds.get((asset_class or "").upper(), 0.02)

    def _to_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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