from fastapi import Header, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import json
from app.core.security import get_current_user
from app.services.redis_client import get_redis
from app.services.idempotency import IdempotencyEngine
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

async def verify_idempotency(
    request: Request,
    user_id: str = Depends(get_current_user),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key", description="UUIDv4 Idempotency Key"),
    redis_client: Redis = Depends(get_redis)
):
    """
    Enforces Task A5 Idempotency Contract.
    Evaluated before the route handler is called.
    """
    # Expose dependencies to the request state so the router can use them to call set_success
    request.state.user_id = user_id
    request.state.idempotency_key = x_idempotency_key
    request.state.redis = redis_client
    
    engine = IdempotencyEngine(redis_client)
    
    acquired = await engine.acquire_lock(user_id, x_idempotency_key)
    
    if not acquired:
        status = await engine.get_status(user_id, x_idempotency_key)
        
        if status == "PROCESSING":
            logger.warning(f"Idempotency Conflict: {x_idempotency_key} is PROCESSING")
            raise HTTPException(
                status_code=409, 
                detail="This request is already being worked on, do not spin up a duplicate execution."
            )
        elif status:
            try:
                # If it's not PROCESSING, it must be a SUCCESS cached JSON payload
                cached_payload = json.loads(status)
                logger.info(f"Idempotency Hit: Returning cached success for {x_idempotency_key}")
                # We raise an HTTPException to short-circuit the router, but use a custom 
                # exception or return a response directly if we bypass the router.
                # In FastAPI, returning a Response from a dependency doesn't halt execution cleanly,
                # so we raise a custom Exception that we catch globally, or raise HTTPException with custom headers.
                # For simplicity without adding global exception handlers, we can raise a 409 but format it, 
                # OR we attach a flag and let the router return it immediately.
                # The cleanest way to short-circuit in FastAPI dependencies is raising an HTTPException 
                # and handling it in a global exception handler. Let's do that.
                pass
            except json.JSONDecodeError:
                pass
                
            # To cleanly short-circuit and return 200 OK with the cached payload, 
            # we will attach the cached response to the request state and let the route return it immediately.
            request.state.cached_response = cached_payload
            return False # Indicates lock was not acquired, but we have a cache hit
            
    request.state.cached_response = None
    return True # Indicates lock was acquired, proceed with ML execution
