from fastapi import APIRouter, Depends, Request
from app.schemas.payload import CLAXAgentOutputContract, TradeVerificationResponse
from app.api.dependencies import verify_idempotency
from app.services.idempotency import IdempotencyEngine
import uuid
import json
import os
import sys

# Append root to sys.path to import app.core
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../..")))
try:
    from app.core.audit_logging import AuditEventBuilder
except ImportError:
    # Fallback mock if running in isolation during tests
    class AuditEventBuilder:
        def __init__(self, *args, **kwargs): pass
        def build_snapshot(self, **kwargs): return kwargs
        async def stream_to_worm_vault(self, snapshot): return "mocked_hash"

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
    
    # 🚀 Selective Logging (Category 2 Action: WORM Compliance Audit)
    is_financial_action = payload.get("is_financial_action", True) # Explicitly flag trades
    
    if is_financial_action:
        audit_builder = AuditEventBuilder()
        snapshot = audit_builder.build_snapshot(
            user_context={
                "user_id": request.state.user_id,
                "ip_address": getattr(request.client, "host", "0.0.0.0"),
                "device_fingerprint": request.headers.get("User-Agent", "Unknown")
            },
            investor_dna=payload.get("investor_dna", {}),
            user_trigger={
                "raw_input_prompt": payload.get("raw_input_prompt", "System execution"),
                "client_idempotency_key": request.state.idempotency_key
            },
            ai_reasoning=payload.get("ai_reasoning", {}),
            safety_evals=payload.get("safety_evals", {}),
            execution_result={
                "ledger_status": "PENDING_EXECUTION",
                "transaction_id": ml_output["data"]["trade_id"]
            }
        )
        # Asynchronously stream artifact snapshot to GCP Bucket
        # Non-Repudiation cryptographic hash is tracked in DB
        snapshot_hash = await audit_builder.stream_to_worm_vault(snapshot)
        ml_output["data"]["audit_hash"] = snapshot_hash
    
    # After successful ML execution, overwrite the PROCESSING lock with SUCCESS payload
    engine = IdempotencyEngine(request.state.redis)
    await engine.set_success(
        user_id=request.state.user_id,
        idempotency_key=request.state.idempotency_key,
        payload=ml_output
    )
    
    return CLAXAgentOutputContract(**ml_output)