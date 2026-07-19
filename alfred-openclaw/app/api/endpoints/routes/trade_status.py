from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import redis as sync_redis

from app.schemas.trade_status_schema import TradeStatusResponse
from app.services.trade_status_service import TradeStatusService, _redis_url
from app.backend_services.jwt_auth.security import get_current_user

trade_status_router = APIRouter()


def get_redis_client() -> sync_redis.Redis:
    return sync_redis.from_url(_redis_url)


def get_trade_status_service(
    redis_client: sync_redis.Redis = Depends(get_redis_client),
) -> TradeStatusService:
    return TradeStatusService(redis_client)


# ==========================================
# GET /trade/status — status lookup
# ==========================================
@trade_status_router.get("/trade/status", response_model=TradeStatusResponse)
def trade_status(
    idempotency_key: str,
    user_id: str = Depends(get_current_user),
    service: TradeStatusService = Depends(get_trade_status_service),
):
    result = service.get_status(user_id, idempotency_key)
    if not result:
        raise HTTPException(status_code=404, detail="Trade instruction not found or invalid idempotency key")
    return result
