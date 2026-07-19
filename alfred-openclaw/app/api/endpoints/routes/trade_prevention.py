from fastapi import APIRouter, Depends, HTTPException

from app.schemas.trade_prevention_schema import TradeExecutionRequest
from app.services.trade_prevention_service import TradePreventionService, DuplicateTradeError
from app.backend_services.jwt_auth.security import get_current_user

trade_prevention_router = APIRouter()


def get_trade_prevention_service() -> TradePreventionService:
    return TradePreventionService()


# ==========================================
# POST /trades/execute — execute with duplicate detection
# ==========================================
@trade_prevention_router.post("/trades/execute")
def execute_trade(
    request: TradeExecutionRequest,
    user_id: str = Depends(get_current_user),
    service: TradePreventionService = Depends(get_trade_prevention_service),
):
    try:
        return service.execute_trade(user_id, request.symbol, request.quantity, request.action)
    except DuplicateTradeError as e:
        raise HTTPException(status_code=409, detail={
            "status": "requires_action",
            "error": {
                "code": "DUPLICATE_ORDER_WINDOW",
                "message": "An identical order was placed within the last 60 seconds.",
            },
            "requirements": {
                "action_type": "USER_CONFIRMATION",
                "confirmation_token": e.confirmation_token,
                "ui_prompt": f"You just placed an identical order for {e.quantity} shares of {e.symbol}. Are you sure you want to place another?",
                "expires_in_seconds": 60,
            },
        })
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
