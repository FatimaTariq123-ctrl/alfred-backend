from pydantic import BaseModel
from typing import Optional


class ConditionalOrderCreate(BaseModel):
    ledger_id: Optional[str] = None
    ticker: str
    action: str
    condition_type: str
    trigger_condition: Optional[str] = None
    trigger_value: float
