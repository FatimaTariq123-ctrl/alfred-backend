from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID

# --- Enums for Lifecycle and Business Logic ---
class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class TriggerType(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    LIMIT_ORDER = "LIMIT_ORDER"

class TriggerStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

# --- API Request/Response Schemas (Pydantic) ---

class ConditionalOrderCreate(BaseModel):
    user_id: UUID
    conversation_id: UUID
    asset: str = Field(..., max_length=20, description="Asset ticker symbol, e.g., AAPL")
    action: OrderAction
    trigger_type: TriggerType
    trigger_condition: str = Field(..., max_length=50, description="Logic representation, e.g., PRICE_DROP_PERCENT")
    trigger_value: float = Field(..., description="Numeric threshold for the trigger")
    expires_at: Optional[datetime] = None

class ConditionalOrderResponse(ConditionalOrderCreate):
    id: UUID
    status: TriggerStatus
    trade_ledger_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

class ConditionalOrderStatusUpdate(BaseModel):
    status: TriggerStatus
    trade_ledger_id: Optional[UUID] = None
