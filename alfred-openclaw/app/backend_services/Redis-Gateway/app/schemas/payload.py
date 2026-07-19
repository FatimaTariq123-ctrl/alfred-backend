from pydantic import BaseModel
from typing import Any, Dict

class CLAXAgentOutputContract(BaseModel):
    """Standardized JSON payload contract (A1)."""
    status: str
    message: str
    data: Dict[str, Any]

class TradeVerificationResponse(BaseModel):
    """Standardized payload for trade verification (pre-commit)."""
    action_required: str
    order_details: Dict[str, Any]
    temporary_token: str