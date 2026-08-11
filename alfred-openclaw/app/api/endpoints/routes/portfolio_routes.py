from fastapi import APIRouter, Depends, Query, Path
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

portfolio_router = APIRouter()

# --- Models ---

class PortfolioGoalUpdate(BaseModel):
    target_annual_return_percent: str

class RecommendationApplyResponse(BaseModel):
    id: str
    status: str
    resulting_orders: List[str]

# --- Endpoints ---

@portfolio_router.get("/portfolio/overview")
async def get_portfolio_overview():
    return {
        "success": True,
        "data": {
            "current_value": "65000.00",
            "started_at_value": "50000.00",
            "total_return_percent": "30.0",
            "today_change_percent": "2.0",
            "ytd_progress_percent": "2.0",
            "goal_target_percent": "15.0",
            "goal_target_date": "2026-12-31",
            "pacing_status": "ahead",
            "total_pnl_lifetime": "15000.00",
            "total_pnl_period": "5000.00",
            "total_invested": "65000.00"
        }
    }

@portfolio_router.get("/portfolio/performance")
async def get_portfolio_performance(range: Optional[str] = Query("1W", description="1D|1W|1M")):
    return {
        "success": True,
        "data": {
            "range": range,
            "points": [
                { "label": "Mon", "target_value": "51000.00", "current_value": "50500.00" },
                { "label": "Wed", "target_value": "12500.00", "current_value": "7000.00" }
            ]
        }
    }

@portfolio_router.get("/portfolio/allocation")
async def get_portfolio_allocation(category: Optional[str] = Query("overview", description="overview|stocks|crypto|commodities")):
    if category == "stocks":
        return {
            "success": True,
            "data": {
                "total": "26000.00",
                "position_count": 4,
                "markets": {
                    "us": [
                        { "symbol": "NFLX", "name": "Netflix, Inc", "value": "9100.00", "percent": "35" },
                        { "symbol": "TSLA", "name": "Tesla, Inc", "value": "7800.00", "percent": "30" }
                    ],
                    "hk": [
                        { "symbol": "0700.HK", "name": "Tencent Holdings", "value": "9100.00", "percent": "35" }
                    ]
                }
            }
        }
    elif category == "crypto":
        return {
            "success": True,
            "data": {
                "total": "13000.00",
                "position_count": 3,
                "change_24h_percent": "2.4",
                "positions": [
                    { "symbol": "BTC", "name": "Bitcoin", "value": "7150.00", "percent": "55" },
                    { "symbol": "ETH", "name": "Ethereum", "value": "3900.00", "percent": "30" },
                    { "symbol": "SOL", "name": "Solana", "value": "1950.00", "percent": "15" }
                ]
            }
        }
    else:
        # overview
        return {
            "success": True,
            "data": {
                "total_invested": "65000.00",
                "categories": [
                    { "category": "commodities", "percent": "40" },
                    { "category": "stocks", "percent": "30" },
                    { "category": "crypto", "percent": "20" },
                    { "category": "etfs", "percent": "10" }
                ]
            }
        }

@portfolio_router.get("/portfolio/holdings")
async def get_portfolio_holdings():
    return {
        "success": True,
        "data": {
            "total_value": "65000.00",
            "holdings": [
                {
                    "symbol": "NFLX",
                    "name": "Netflix, Inc",
                    "asset_class": "us_stock",
                    "quantity": "25.0",
                    "avg_price": "350.00",
                    "current_price": "364.00",
                    "current_value": "9100.00",
                    "pnl_absolute": "350.00",
                    "pnl_percent": "4.0"
                },
                {
                    "symbol": "BTCUSD",
                    "name": "Bitcoin",
                    "asset_class": "crypto",
                    "quantity": "0.1",
                    "avg_price": "60000.00",
                    "current_price": "71500.00",
                    "current_value": "7150.00",
                    "pnl_absolute": "1150.00",
                    "pnl_percent": "19.1"
                }
            ]
        }
    }

@portfolio_router.get("/portfolio/goal")
async def get_portfolio_goal():
    return {
        "success": True,
        "data": { 
            "target_annual_return_percent": "15", 
            "start_value": "50000.00", 
            "start_date": "2026-01-08", 
            "target_date": "2026-12-31" 
        }
    }

@portfolio_router.put("/portfolio/goal")
async def update_portfolio_goal(payload: PortfolioGoalUpdate):
    return {
        "success": True,
        "data": { 
            "target_annual_return_percent": payload.target_annual_return_percent, 
            "start_value": "50000.00", 
            "start_date": "2026-01-08", 
            "target_date": "2026-12-31" 
        }
    }

@portfolio_router.get("/portfolio/recommendations")
async def get_portfolio_recommendations():
    return {
        "success": True,
        "data": [
            {
                "id": "rec_2f81",
                "type": "replace",
                "symbol_from": "NFLX",
                "symbol_to": "PLTR",
                "rationale": "Replace NFLX with PLTR for better alignment to your 15% ROI target.",
                "status": "pending"
            }
        ]
    }

@portfolio_router.post("/portfolio/recommendations/{id}/apply")
async def apply_portfolio_recommendation(id: str = Path(...)):
    return {
        "success": True,
        "data": { 
            "id": id, 
            "status": "applied", 
            "resulting_orders": ["ord_9d4e17", "ord_7c1a2b"] 
        }
    }

@portfolio_router.post("/portfolio/recommendations/{id}/dismiss")
async def dismiss_portfolio_recommendation(id: str = Path(...)):
    return {
        "success": True,
        "data": { 
            "id": id, 
            "status": "dismissed" 
        }
    }

@portfolio_router.get("/autopilot")
async def get_autopilot_status():
    return {
        "success": True,
        "data": { 
            "is_active": True, 
            "activated_at": "2026-07-15T00:00:00Z", 
            "strategy_summary": "Automated trading + daily health check" 
        }
    }

@portfolio_router.post("/autopilot/activate")
async def activate_autopilot():
    return { 
        "success": True, 
        "data": { "is_active": True, "activated_at": "2026-07-29T10:00:00Z" } 
    }

@portfolio_router.post("/autopilot/deactivate")
async def deactivate_autopilot():
    return { 
        "success": True, 
        "data": { "is_active": False, "deactivated_at": "2026-07-29T10:00:00Z" } 
    }

@portfolio_router.get("/autopilot/logs")
async def get_autopilot_logs(cursor: Optional[str] = None, limit: Optional[int] = 20):
    return {
        "success": True,
        "data": [
            { 
                "id": "apl_881a", 
                "action": "rebalance", 
                "symbol": "NFLX→PLTR", 
                "rationale": "Portfolio drift exceeded target allocation by 6%.", 
                "executed_at": "2026-07-28T00:00:00Z" 
            }
        ],
        "meta": { "next_cursor": None, "has_more": False }
    }
