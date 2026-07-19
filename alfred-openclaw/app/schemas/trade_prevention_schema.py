from pydantic import BaseModel


class TradeExecutionRequest(BaseModel):
    symbol: str
    quantity: float
    action: str
