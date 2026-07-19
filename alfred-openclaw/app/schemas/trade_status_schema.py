from enum import Enum

from pydantic import BaseModel


class TradeState(str, Enum):
    PROCESSING = "PROCESSING"
    RECONCILING = "RECONCILING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    VETOED = "VETOED"


class TradeStatusResponse(BaseModel):
    idempotency_key: str
    status: TradeState
    source: str
    payload: dict | None = None
