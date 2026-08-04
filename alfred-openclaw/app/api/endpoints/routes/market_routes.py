from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uuid
import asyncio
import json
import random
from datetime import datetime

router = APIRouter()

# Data models
class ChartPoint(BaseModel):
    t: str
    p: float

class ChartPreview(BaseModel):
    range: str
    points: List[ChartPoint]

class PriceChange(BaseModel):
    absolute: float
    percentage: float

class Quote(BaseModel):
    current_price: float
    price_change: PriceChange
    market_status: str
    last_updated: str

class Asset(BaseModel):
    ticker: str
    name: str
    asset_image_url: str
    quote: Quote
    chart_preview: ChartPreview

class TopAssetsResponse(BaseModel):
    us_stocks: List[Asset]
    hk_stocks: List[Asset]
    crypto: List[Asset]

class BuyReviewRequest(BaseModel):
    mode: str
    shares: Optional[float] = None
    amount: Optional[float] = None
    payment_method: str

class BuyRequest(BaseModel):
    review_token: str

class SellReviewRequest(BaseModel):
    mode: str
    shares: Optional[float] = None
    amount: Optional[float] = None

class SellRequest(BaseModel):
    review_token: str

# Mocks
def generate_mock_asset(ticker: str, name: str, price: float) -> Asset:
    return Asset(
        ticker=ticker,
        name=name,
        asset_image_url=f"https://api.stock-logos.com/v1/{ticker.lower()}.png",
        quote=Quote(
            current_price=price,
            price_change=PriceChange(absolute=-5.27, percentage=-2.84),
            market_status="open",
            last_updated="2026-02-04T16:00:00Z"
        ),
        chart_preview=ChartPreview(
            range="1D",
            points=[
                ChartPoint(t="2026-02-04T14:30:00Z", p=price + 4.56),
                ChartPoint(t="2026-02-04T14:35:00Z", p=price + 2.76)
            ]
        )
    )

@router.get("/api/v1/dashboard/top-assets", response_model=TopAssetsResponse, tags=["Market"])
async def get_top_assets():
    return TopAssetsResponse(
        us_stocks=[
            generate_mock_asset("NVDA", "NVIDIA Corporation", 180.34),
            generate_mock_asset("AAPL", "Apple Inc.", 150.00),
            generate_mock_asset("TSLA", "Tesla Inc.", 200.00),
            generate_mock_asset("MSFT", "Microsoft Corp.", 330.00),
            generate_mock_asset("AMZN", "Amazon.com Inc.", 130.00)
        ],
        hk_stocks=[
            generate_mock_asset("0700.HK", "Tencent", 400.00),
            generate_mock_asset("9988.HK", "Alibaba", 85.00),
            generate_mock_asset("3690.HK", "Meituan", 120.00),
            generate_mock_asset("0941.HK", "China Mobile", 65.00),
            generate_mock_asset("1299.HK", "AIA", 70.00)
        ],
        crypto=[
            generate_mock_asset("BTC", "Bitcoin", 65000.00),
            generate_mock_asset("ETH", "Ethereum", 3500.00),
            generate_mock_asset("SOL", "Solana", 140.00),
            generate_mock_asset("XRP", "XRP", 0.60),
            generate_mock_asset("DOGE", "Dogecoin", 0.15)
        ]
    )

@router.get("/api/v1/stocks/{ticker}/details", tags=["Market"])
async def get_stock_details(ticker: str):
    return {
        "ticker": ticker.upper(),
        "name": f"{ticker.upper()} Corporation",
        "asset_image_url": f"https://api.stock-logos.com/v1/{ticker.lower()}.png",
        "quote": {
            "current_price": 180.34,
            "price_change": { "absolute": -5.27, "percentage": -2.84 },
            "market_status": "open",
            "last_updated": "2026-02-04T16:00:00Z"
        },
        "statistics": {
            "macd": 240,
            "rsi_14": 38.6,
            "sma": 182.10
        },
        "indicator": {
            "signal": "sell",
            "confidence": 0.90,
            "suggestion": "Good time to buy"
        },
        "macro_sentiment": {
            "value": 0.76,
            "label": "positive"
        },
        "holding": {
            "total_shares_held": 20,
            "avg_price": 85.40,
            "pnl_percentage": -0.59,
            "current_value": 5.03,
            "total_cost": 5.06,
            "unrealized_return": { "absolute": -0.03, "percentage": -0.59 },
            "quantity": 0.05925,
            "current_price": 84.92,
            "avg_cost_basis": 85.40,
            "avg_cost_paid": 85.40,
            "portfolio_weight_pct": 13.96,
            "invested_since": "2026-02-19",
            "invested_days": 4
        }
    }

@router.get("/api/v1/stocks/{ticker}/chart", tags=["Market"])
async def get_stock_chart(ticker: str, range: str = "1D"):
    return {
        "ticker": ticker.upper(),
        "range": range,
        "granularity": "1m",
        "is_streaming": True,
        "points": [
            { "t": "2026-02-04T14:30:00Z", "p": 184.90 },
            { "t": "2026-02-04T14:35:00Z", "p": 184.20 },
            { "t": "2026-02-04T14:40:00Z", "p": 183.75 }
        ]
    }

# Idempotency store (in-memory for demo)
idempotency_store: Dict[str, Any] = {}

@router.post("/api/v1/stocks/{ticker}/buy/review", tags=["Market"])
async def buy_review(ticker: str, req: BuyReviewRequest):
    return {
        "review_token": f"rvw_{uuid.uuid4().hex[:8]}",
        "expires_in": 30,
        "ticker": ticker.upper(),
        "payment_method": req.payment_method,
        "market_price": 80.00,
        "est_shares": 0.05926,
        "order_amount": req.amount or 5.00,
        "one_time_tip": 0.06,
        "total_cost": (req.amount or 5.00) + 0.06,
        "buying_power": 60.00
    }

@router.post("/api/v1/stocks/{ticker}/buy", tags=["Market"])
async def buy_stock(ticker: str, req: BuyRequest, idempotency_key: str = Header(None, alias="Idempotency-Key")):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
        
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]
        
    res = {
        "order_id": f"ord_{uuid.uuid4().hex[:8]}",
        "status": "completed",
        "order_type": "Market buy ($)",
        "order_amount": 5.00,
        "avg_price_per_share": 80.00,
        "shares": 0.05925,
        "transaction_fees": 0.00,
        "one_time_tip": 0.06,
        "total_cost": 5.06
    }
    idempotency_store[idempotency_key] = res
    return res

@router.post("/api/v1/stocks/{ticker}/sell/review", tags=["Market"])
async def sell_review(ticker: str, req: SellReviewRequest):
    return {
        "review_token": f"rvw_{uuid.uuid4().hex[:8]}",
        "expires_in": 30,
        "ticker": ticker.upper(),
        "market_price": 84.66,
        "est_shares": 0.05926,
        "sell_amount": req.amount or 5.00,
        "regulatory_fee": -0.02,
        "one_time_tip": -0.00,
        "total_sale_proceeds": (req.amount or 5.00) - 0.02,
        "available_to_close": 10.03,
        "day_trade": {
            "is_day_trade": True,
            "day_trade_count": 0,
            "day_trade_limit": 3
        }
    }

@router.post("/api/v1/stocks/{ticker}/sell", tags=["Market"])
async def sell_stock(ticker: str, req: SellRequest, idempotency_key: str = Header(None, alias="Idempotency-Key")):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
        
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]
        
    res = {
        "order_id": f"ord_{uuid.uuid4().hex[:8]}",
        "status": "completed",
        "order_type": "Market sell ($)",
        "order_amount": 5.00,
        "avg_price_per_share": 84.66,
        "quantity": 0.05925,
        "transaction_fees": -0.00,
        "regulatory_fee": -0.02,
        "total_sale_proceeds": 4.98
    }
    idempotency_store[idempotency_key] = res
    return res

# WebSockets
@router.websocket("/ws/v1/quotes")
async def websocket_quotes(websocket: WebSocket):
    await websocket.accept()
    active_tickers = set()
    
    try:
        while True:
            # We'll use asyncio.wait to concurrently wait for either a message from client
            # or a timer to push updates for active tickers.
            receive_task = asyncio.create_task(websocket.receive_text())
            push_task = asyncio.create_task(asyncio.sleep(3))
            
            done, pending = await asyncio.wait(
                [receive_task, push_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            if receive_task in done:
                data = receive_task.result()
                try:
                    msg = json.loads(data)
                    action = msg.get("action")
                    tickers = msg.get("tickers", [])
                    if action == "subscribe":
                        active_tickers.update(tickers)
                    elif action == "unsubscribe":
                        for t in tickers:
                            active_tickers.discard(t)
                except json.JSONDecodeError:
                    pass
                
            if push_task in done:
                # Push updates for subscribed tickers
                for ticker in list(active_tickers)[:5]: # Limit to 5 updates per tick for demo
                    base_price = 150.0
                    if ticker == "NVDA": base_price = 180.0
                    elif ticker == "BTC": base_price = 65000.0
                    
                    new_price = base_price + random.uniform(-2.0, 2.0)
                    update = {
                        "ticker": ticker,
                        "quote": {
                            "current_price": round(new_price, 2),
                            "price_change": {
                                "absolute": round(new_price - base_price, 2),
                                "percentage": round((new_price - base_price) / base_price * 100, 2)
                            },
                            "market_status": "open",
                            "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                        }
                    }
                    await websocket.send_json(update)
                    
            # Cancel pending tasks
            for task in pending:
                task.cancel()
                
    except WebSocketDisconnect:
        pass
