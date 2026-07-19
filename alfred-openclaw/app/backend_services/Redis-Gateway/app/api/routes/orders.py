from fastapi import APIRouter, Depends, Request
from app.schemas.payload import CLAXAgentOutputContract, TradeVerificationResponse
from app.api.dependencies import verify_idempotency
from app.services.idempotency import IdempotencyEngine
import uuid
import json

router = APIRouter()

@router.post("/verify", response_model=TradeVerificationResponse)
async def verify_order(
    request: Request,
    payload: dict
):
    """
    Accepts structured payload from Multi-Asset Order Router.
    Creates temporary verification state only.
    Does not write to ledger/database.
    Returns verification payload and temporary token.
    """
    temporary_token = str(uuid.uuid4())
    
    # Save the order details in Redis with an expiration (e.g., 300s = 5 mins)
    redis_client = request.state.redis
    cache_key = f"verification:{temporary_token}"
    await redis_client.set(cache_key, json.dumps(payload), ex=300)
    
    return TradeVerificationResponse(
        action_required="USER_CONFIRMATION_REQUIRED",
        order_details=payload,
        temporary_token=temporary_token
    )
from sqlalchemy import create_engine, text
import json
from app.core.config import settings

router = APIRouter()

# Setup Global Database Connection Pool for Stateless Trade Persistence
db_url = settings["DATABASE_URL"]
if db_url and db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
db_engine = create_engine(db_url, pool_size=10, max_overflow=20)


@router.post("/commit", response_model=CLAXAgentOutputContract)
async def commit_order(
    request: Request, 
    payload: dict, 
    lock_acquired: bool = Depends(verify_idempotency)
):
    """
    Simulates sending an order down to the ML Multi-Asset Order Router.
    Protected by idempotency middleware.
    """
    
    # Path C: Lock failed, but we found a SUCCESS cache. Return it immediately.
    if request.state.cached_response:
        return CLAXAgentOutputContract(**request.state.cached_response)
        
    # Path A: Lock acquired. We are safe to process the trade.
    
    # --- [Simulated call to downstream stateless ML Agent] ---
    ml_output = {
        "status": "success",
        "message": "Order processed statelessly by ML Agent",
        "data": {"trade_id": "12345", "details": payload}
    }
    # ---------------------------------------------------------

    # Persist the trade payload directly to the backend database 
    # ensuring OpenClaw Order Router remains fully stateless.
    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO clax_trade_ledger (user_id, client_idempotency_key, status, payload)
                    VALUES (:uid, :ikey, 'SUCCESS', :payload)
                """),
                {
                    "uid": request.state.user_id,
                    "ikey": request.state.idempotency_key,
                    "payload": json.dumps(ml_output)
                }
            )
    except Exception as e:
        # In a production environment this would be routed to a dead letter queue or logging system
        print(f"Database insertion error during trade persistence: {e}")

    
    # After successful ML execution and persistence, overwrite the PROCESSING lock with SUCCESS payload
    engine = IdempotencyEngine(request.state.redis)
    await engine.set_success(
        user_id=request.state.user_id,
        idempotency_key=request.state.idempotency_key,
        payload=ml_output
    )
    
    return CLAXAgentOutputContract(**ml_output)