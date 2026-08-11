from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

router = APIRouter(tags=["Buy / Sell Orders"])

# Mock Authentication
from fastapi.security import APIKeyHeader
api_key_header = APIKeyHeader(name="Authorization", auto_error=True, description="Enter Mock Token (e.g. Bearer mock_token)")

def verify_token(api_key: str = Depends(api_key_header)):
    if not api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return api_key

class SideEnum(str, Enum):
    buy = "buy"
    sell = "sell"

class AmountTypeEnum(str, Enum):
    shares = "shares"
    dollars = "dollars"

class PreviewOrderRequest(BaseModel):
    symbol: str
    side: SideEnum
    amount_type: AmountTypeEnum
    amount: str

class PlaceOrderRequest(BaseModel):
    quote_id: str

# 6.6.1 Preview an Order (Quote)
@router.post("/orders/preview", summary="Preview an Order (Quote)")
def preview_order(request: PreviewOrderRequest, token: str = Depends(verify_token)):
    if request.side == SideEnum.buy:
        return {
             "success": True,
             "data": {
                 "quote_id": "qte_9f21ab",
                 "symbol": "PLTR",
                 "side": "buy",
                 "market_price": "80.00",
                 "estimated_shares": "0.062500",
                 "order_amount": "5.00",
                 "one_time_tip": "0.06",
                 "transaction_fees": "0.00",
                 "total_cost": "5.06",
                 "expires_at": "2026-07-29T10:16:00Z",
                 "day_trade_warning": None
             }
        }
    else:
        return {
             "success": True,
             "data": {
                 "quote_id": "qte_51c0e2",
                 "symbol": "PLTR",
                 "side": "sell",
                 "market_price": "84.66",
                 "estimated_shares": "0.059260",
                 "sell_amount": "5.00",
                 "regulatory_fee": "0.02",
                 "one_time_tip": "0.00",
                 "total_sale_proceeds": "4.98",
                 "expires_at": "2026-07-29T10:16:00Z",
                 "day_trade_warning": {
                     "day_trades_used": 0,
                     "day_trades_limit": 3,
                     "message": 'Under FINRA rules, you will be flagged a pattern day trader ("PDT") if you make 4 or more day trades within 5 consecutive business days.'
                 }
             }
        }

# 6.6.2 Place Order
@router.post("/orders", status_code=201, summary="Place Order")
def place_order(request: PlaceOrderRequest, token: str = Depends(verify_token), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    if request.quote_id == "qte_51c0e2":
        return {
             "success": True,
             "data": {
                 "order_id": "ord_9d4e17",
                 "symbol": "PLTR",
                 "side": "sell",
                 "status": "filled",
                 "market_price": "84.66",
                 "sell_amount": "5.00",
                 "quantity": "0.059250",
                 "transaction_fees": "0.00",
                 "regulatory_fee": "0.02",
                 "total_sale_proceeds": "4.98",
                 "is_day_trade": True,
                 "filled_at": "2026-07-29T10:22:10Z"
             }
        }
    return {
         "success": True,
         "data": {
             "order_id": "ord_7c1a2b",
             "symbol": "PLTR",
             "side": "buy",
             "status": "filled",
             "order_amount": "5.00",
             "avg_price_per_share": "80.00",
             "shares": "0.062500",
             "transaction_fees": "0.00",
             "one_time_tip": "0.06",
             "total_cost": "5.06",
             "is_day_trade": False,
             "filled_at": "2026-07-29T10:15:32Z"
         }
    }

# 6.6.3 Get Order
@router.get("/orders/{id}", summary="Get Order")
def get_order(id: str, token: str = Depends(verify_token)):
    return {
         "success": True,
         "data": {
             "order_id": id,
             "symbol": "PLTR",
             "side": "buy",
             "status": "filled",
             "order_amount": "5.00",
             "avg_price_per_share": "80.00",
             "shares": "0.062500",
             "transaction_fees": "0.00",
             "one_time_tip": "0.06",
             "total_cost": "5.06",
             "is_day_trade": False,
             "filled_at": "2026-07-29T10:15:32Z"
         }
    }

# 6.6.4 List Order History
@router.get("/orders", summary="List Order History")
def list_orders(symbol: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None, token: str = Depends(verify_token)):
    return {
        "success": True,
        "data": [
            {
                 "order_id": "ord_7c1a2b",
                 "symbol": "PLTR",
                 "side": "buy",
                 "status": "filled",
                 "order_amount": "5.00",
                 "avg_price_per_share": "80.00",
                 "shares": "0.062500",
                 "transaction_fees": "0.00",
                 "one_time_tip": "0.06",
                 "total_cost": "5.06",
                 "is_day_trade": False,
                 "filled_at": "2026-07-29T10:15:32Z"
            }
        ],
        "meta": {
            "next_cursor": "cur_123abc"
        }
    }

# 6.6.5 Day-Trade Status
@router.get("/orders/day-trade-status", summary="Day-Trade Status")
def day_trade_status(token: str = Depends(verify_token)):
    return {
         "success": True,
         "data": {
             "day_trades_used": 0,
             "day_trades_limit": 3,
             "is_pdt_restricted": False,
             "restriction_ends_at": None
         }
    }
