from fastapi import APIRouter, Header, Body, Path, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List

router = APIRouter(tags=["Watchlist & Price Alerts"])

# Pydantic Models for Requests
class AddWatchlistRequest(BaseModel):
    symbol: str

class CreatePriceAlertRequest(BaseModel):
    symbol: str
    target_type: str = Field(..., description="percent or price")
    target_value: str
    direction: str = Field(..., description="above or below")

class UpdatePriceAlertRequest(BaseModel):
    target_value: str

# 6.4.1 Get Watchlist
@router.get("/watchlist", summary="6.4.1 Get Watchlist", status_code=200)
def get_watchlist(
    Authorization: str = Header(default="Bearer mock_token_123", description="Bearer <access_token>")
):
    return {
        "success": True,
        "data": {
            "indices": [
                {
                    "symbol": "SPX",
                    "name": "S&P 500 Index",
                    "price": "4365.99",
                    "change": "7.64",
                    "change_percent": "0.18"
                }
            ],
            "stocks": [
                {
                    "symbol": "PLTR",
                    "name": "Palantir Corporation",
                    "price": "138.85",
                    "change_percent": "2.63",
                    "held": True,
                    "has_price_alert": True
                }
            ]
        }
    }

# 6.4.2 Add to Watchlist
@router.post("/watchlist", summary="6.4.2 Add to Watchlist", status_code=201)
def add_watchlist(
    request: AddWatchlistRequest = Body(
        default=AddWatchlistRequest(symbol="PLTR"),
        examples=[{"symbol": "PLTR"}]
    ),
    Authorization: str = Header(default="Bearer mock_token_123", description="Bearer <access_token>"),
    content_type: str = Header(default="application/json", alias="Content-Type")
):
    return {
        "success": True,
        "data": {
            "symbol": request.symbol,
            "added_at": "2026-07-29T10:00:00Z"
        }
    }

# 6.4.3 Remove from Watchlist
@router.delete("/watchlist/{symbol}", summary="6.4.3 Remove from Watchlist", status_code=200)
def remove_watchlist(
    symbol: str = Path(..., example="PLTR"),
    Authorization: str = Header(default="Bearer mock_token_123", description="Bearer <access_token>")
):
    return {
        "success": True,
        "data": {
            "removed": True
        }
    }

# 6.4.4 Create Price Alert
@router.post("/price-alerts", summary="6.4.4 Create Price Alert", status_code=201)
def create_price_alert(
    request: CreatePriceAlertRequest = Body(
        default=CreatePriceAlertRequest(
            symbol="PLTR",
            target_type="percent",
            target_value="10",
            direction="above"
        ),
        examples=[{
            "symbol": "PLTR",
            "target_type": "percent",
            "target_value": "10",
            "direction": "above"
        }]
    ),
    Authorization: str = Header(default="Bearer mock_token_123", description="Bearer <access_token>"),
    content_type: str = Header(default="application/json", alias="Content-Type")
):
    return {
        "success": True,
        "data": {
            "id": "pa_77bd",
            "symbol": request.symbol,
            "resolved_target_price": "161.56",
            "status": "active"
        }
    }

# 6.4.5 List Price Alerts
@router.get("/price-alerts", summary="6.4.5 List Price Alerts", status_code=200)
def list_price_alerts(
    symbol: Optional[str] = Query(None, description="Optional filter by symbol"),
    status: Optional[str] = Query(None, description="active, triggered, or cancelled"),
    Authorization: str = Header(default="Bearer mock_token_123", description="Bearer <access_token>")
):
    return [
        {
            "id": "pa_77bd",
            "symbol": symbol or "PLTR",
            "resolved_target_price": "161.56",
            "status": status or "active"
        }
    ]

# 6.4.6 Update Price Alert
@router.patch("/price-alerts/{id}", summary="6.4.6 Update Price Alert", status_code=200)
def update_price_alert(
    id: str = Path(..., example="pa_77bd"),
    request: UpdatePriceAlertRequest = Body(
        default=UpdatePriceAlertRequest(target_value="15"),
        examples=[{"target_value": "15"}]
    ),
    Authorization: str = Header(default="Bearer mock_token_123", description="Bearer <access_token>"),
    content_type: str = Header(default="application/json", alias="Content-Type")
):
    return {
        "id": id,
        "symbol": "PLTR",
        "resolved_target_price": "161.56",
        "status": "active",
        "target_value": request.target_value
    }

# 6.4.7 Delete Price Alert
@router.delete("/price-alerts/{id}", summary="6.4.7 Delete Price Alert", status_code=200)
def delete_price_alert(
    id: str = Path(..., example="pa_77bd"),
    Authorization: str = Header(default="Bearer mock_token_123", description="Bearer <access_token>")
):
    return {
        "success": True,
        "data": {
            "deleted": True
        }
    }