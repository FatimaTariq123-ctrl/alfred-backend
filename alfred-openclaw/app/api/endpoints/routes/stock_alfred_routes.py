from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import urllib.parse

router = APIRouter()
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    return credentials.credentials

@router.get("/stocks/{symbol}", tags=["Stock details & Alfred"])
async def get_stock_detail(symbol: str, token: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "symbol": symbol.upper(),
            "name": "Palantir Corporation",
            "exchange": "NASDAQ",
            "price": "138.85",
            "change": "3.56",
            "change_percent": "2.63",
            "currency": "USD",
            "trend": "positive",
            "market_status": { "is_open": True, "next_close_at": "2026-07-29T20:00:00Z" },
            "position": {
                "held_shares": "20.000000",
                "avg_price": "124.60",
                "unrealized_return_percent": "11.47",
                "current_value": "2777.00",
                "total_cost": "2492.00",
                "portfolio_weighting_percent": "13.96",
                "invested_days": 4
            },
            "has_price_alert": True,
            "in_watchlist": True
        }
    }

@router.get("/stocks/{symbol}/chart", tags=["Stock details & Alfred"])
async def get_price_chart(symbol: str, range: str = "1D", token: str = Depends(get_current_user)):
    # Original spec requested an array of points
    return {
        "success": True,
        "data": {
            "range": range,
            "points": [
                { "t": "2026-07-29T09:30:00Z", "price": "135.10" },
                { "t": "2026-07-29T10:00:00Z", "price": "138.85" }
            ]
        }
    }

@router.get("/stocks/{symbol}/recommendation", tags=["Stock details & Alfred"])
async def get_alfred_recommendation(symbol: str, token: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "call": "BUY",
            "confidence_percent": 91,
            "key_statistics": { "macd": "+240", "rsi_14": "50", "sma": "45" },
            "breakdown_insight": {
                "social_media": 1300,
                "company_reports": 25,
                "articles": 1657,
                "reddit": 251,
                "threads": None,
                "edgar_filings": None
            }
        }
    }

@router.get("/stocks/{symbol}/price-target", tags=["Stock details & Alfred"])
async def get_price_target(symbol: str, token: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "locked": False,
            "macro_sentiment": "Positive",
            "current_price": "128.40",
            "suggested_exit_price": "134.82",
            "disclaimer": "Guidance, not a guarantee"
        }
    }

@router.post("/stocks/{symbol}/price-target/unlock", tags=["Stock details & Alfred"])
async def unlock_price_target(symbol: str, token: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "locked": False,
            "macro_sentiment": "Positive",
            "current_price": "128.40",
            "suggested_exit_price": "134.82",
            "disclaimer": "Guidance, not a guarantee"
        }
    }

class AskAlfredRequest(BaseModel):
    symbol: Optional[str] = None
    question: str

@router.post("/alfred/ask", tags=["Stock details & Alfred"])
async def ask_alfred(request: AskAlfredRequest, token: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "message_id": "msg_a91f",
            "answer": "MACD (Moving Average Convergence Divergence), RSI (Relative Strength Index), and SMA (Simple Moving Average) are key technical indicators. MACD shows trend momentum, RSI indicates if a stock is overbought or oversold, and SMA smooths out price data to identify broader trends."
        }
    }

@router.get("/alfred/suggested-questions", tags=["Stock details & Alfred"])
async def get_suggested_questions(symbol: Optional[str] = None, token: str = Depends(get_current_user)):
    return {
        "success": True,
        "data": ["Why BUY?", "What is MACD, RSI and SMA?", "What is EDGAR?"]
    }
