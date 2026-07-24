from fastapi import APIRouter, Depends, Request, HTTPException
from app.schemas.payload import CLAXAgentOutputContract
from app.api.dependencies import verify_idempotency
from app.services.idempotency import IdempotencyEngine
import asyncio
import httpx

router = APIRouter()

async def simulate_downstream_dispatch(payload: dict) -> dict:
    """Mock for downstream execution that might timeout"""
    await asyncio.sleep(0.5) # Simulate network call
    # If it times out or fails during real network call, an exception would be thrown.
    # For this mock, we pretend it works immediately
    return {
        "status": "success",
        "message": "Order processed statelessly by ML Agent",
        "data": {"trade_id": "12345", "details": payload}
    }

@router.post("/commit", response_model=CLAXAgentOutputContract)
async def commit_order(
    request: Request, 
    payload: dict, 
    lock_acquired: bool = Depends(verify_idempotency)
):
    """
    Simulates sending an order down to the ML Multi-Asset Order Router.
    Protected by idempotency middleware and wrapped in safe transaction retry logic.
    """
    
    # Path C: Lock failed, but we found a SUCCESS cache. Return it immediately.
    if request.state.cached_response:
        return CLAXAgentOutputContract(**request.state.cached_response)
        
    # Path A: Lock acquired. We are safe to process the trade.
    engine = IdempotencyEngine(request.state.redis)
    
    try:
        # Wrap trade dispatch with a strict timeout constraint
        ml_output = await asyncio.wait_for(simulate_downstream_dispatch(payload), timeout=5.0)
        
        # After successful ML execution, overwrite the PROCESSING lock with SUCCESS payload
        await engine.set_success(
            user_id=request.state.user_id,
            idempotency_key=request.state.idempotency_key,
            payload=ml_output
        )
        return CLAXAgentOutputContract(**ml_output)
        
    except (asyncio.TimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout):
        # On timeout, do not blindly retry execution. Move trade to RECONCILING safely.
        await engine.set_reconciling(
            user_id=request.state.user_id,
            idempotency_key=request.state.idempotency_key
        )
        
        reconciliation_response = {
            "status": "reconciling",
            "message": "Broker execution timed out. Trade entering background reconciliation. Please check status endpoint.",
            "data": {"idempotency_key": request.state.idempotency_key}
        }
        return CLAXAgentOutputContract(**reconciliation_response)
