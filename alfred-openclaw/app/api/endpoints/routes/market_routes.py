from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from app.backend_services.jwt_auth.security import get_current_user

router = APIRouter()

@router.get("/home")
def get_home(user_id: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "greeting_name": "John Doe",
            "wallet_quick_balance": "10000.00",
            "categories": {
                "us_stock": [
                    { "symbol": "TSLA", "name": "Tesla, Inc", "price": "1058.60", "change_percent": "1.43" },
                    { "symbol": "AAPL", "name": "Apple Inc", "price": "150.00", "change_percent": "0.50" },
                    { "symbol": "MSFT", "name": "Microsoft Corp", "price": "299.50", "change_percent": "1.20" },
                    { "symbol": "GOOGL", "name": "Alphabet Inc", "price": "2800.00", "change_percent": "-0.30" },
                    { "symbol": "AMZN", "name": "Amazon.com", "price": "3400.00", "change_percent": "2.10" }
                ],
                "hk_stock": [
                    { "symbol": "0700.HK", "name": "Tencent Holdings", "price": "350.60", "change_percent": "1.43" }
                ],
                "crypto": [
                    { "symbol": "BTCUSD", "name": "Bitcoin", "price": "6058.60", "change_percent": "1.43" }
                ]
            },
            "assistant_prompt": "Tap me anytime to talk."
        }
    }

@router.get("/markets/movers")
def get_market_movers(
    category: str = Query(..., description="Category: us_stock|hk_stock|crypto"),
    limit: int = Query(5, description="Number of items to return"),
    user_id: str = Depends(get_current_user)
):
    if category not in ["us_stock", "hk_stock", "crypto"]:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    # Mock data, in a real scenario this would fetch from a DB/Cache based on the category and limit
    mock_data = {
        "us_stock": [
            { "symbol": "TSLA", "name": "Tesla, Inc", "price": "1058.60", "change_percent": "1.43" },
            { "symbol": "AAPL", "name": "Apple Inc", "price": "150.00", "change_percent": "0.50" },
            { "symbol": "MSFT", "name": "Microsoft Corp", "price": "299.50", "change_percent": "1.20" },
            { "symbol": "GOOGL", "name": "Alphabet Inc", "price": "2800.00", "change_percent": "-0.30" },
            { "symbol": "AMZN", "name": "Amazon.com", "price": "3400.00", "change_percent": "2.10" },
            { "symbol": "META", "name": "Meta Platforms", "price": "330.00", "change_percent": "0.80" },
            { "symbol": "NVDA", "name": "NVIDIA Corp", "price": "220.00", "change_percent": "3.50" }
        ],
        "hk_stock": [
            { "symbol": "0700.HK", "name": "Tencent Holdings", "price": "350.60", "change_percent": "1.43" },
            { "symbol": "9988.HK", "name": "Alibaba Group", "price": "120.50", "change_percent": "-1.20" }
        ],
        "crypto": [
            { "symbol": "BTCUSD", "name": "Bitcoin", "price": "6058.60", "change_percent": "1.43" },
            { "symbol": "ETHUSD", "name": "Ethereum", "price": "400.50", "change_percent": "2.10" }
        ]
    }
    
    items = mock_data.get(category, [])
    return {
        "success": True,
        "data": items[:limit]
    }

@router.get("/markets/search")
def search_instruments(
    q: str = Query(..., description="Search query"),
    category: Optional[str] = Query(None, description="Optional category filter"),
    user_id: str = Depends(get_current_user)
):
    # Mock data to simulate search
    return {
        "success": True,
        "data": [
            { "symbol": "PLTR", "name": "Palantir Corporation", "asset_class": "stock_us" },
            { "symbol": q.upper(), "name": f"Mock Company {q}", "asset_class": category or "stock_us" }
        ]
    }

@router.get("/markets/status")
def get_market_status(user_id: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": [
            { "exchange": "NASDAQ", "is_open": False, "next_open_at": "2026-07-29T13:30:00Z", "next_close_at": "2026-07-29T20:00:00Z" },
            { "exchange": "HKEX", "is_open": True, "next_open_at": None, "next_close_at": "2026-07-29T08:00:00Z" },
            { "exchange": "CRYPTO", "is_open": True, "next_open_at": None, "next_close_at": None }
        ]
    }
