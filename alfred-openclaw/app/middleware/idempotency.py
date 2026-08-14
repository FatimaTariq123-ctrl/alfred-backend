import json
import logging
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
from fastapi.responses import JSONResponse
import os

logger = logging.getLogger(__name__)

# Try importing redis for production use
try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

class CacheStore:
    """Abstract cache store for idempotency"""
    async def get(self, key: str) -> Optional[str]:
        raise NotImplementedError
    async def set(self, key: str, value: str, nx: bool = False, ex: int = None) -> bool:
        raise NotImplementedError
    async def delete(self, key: str):
        raise NotImplementedError

class MemoryStore(CacheStore):
    """In-memory fallback for local development or single-worker deployments."""
    def __init__(self):
        self._store = {}

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int = None) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    async def delete(self, key: str):
        if key in self._store:
            del self._store[key]

class RedisStore(CacheStore):
    """Redis-backed store for production, multi-worker safety."""
    def __init__(self, url: str):
        self.redis = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[str]:
        return await self.redis.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int = None) -> bool:
        res = await self.redis.set(key, value, nx=nx, ex=ex)
        return bool(res)

    async def delete(self, key: str):
        await self.redis.delete(key)

# Global store initialization
redis_url = os.environ.get("REDIS_URL")
if HAS_REDIS and redis_url:
    logger.info("Initializing Idempotency Middleware with RedisStore.")
    cache_store = RedisStore(redis_url)
else:
    logger.info("Initializing Idempotency Middleware with MemoryStore (fallback).")
    cache_store = MemoryStore()

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to ensure API idempotency for POST, PUT, PATCH, DELETE requests.
    Prevents duplicate executions and returns cached responses for repeated identical requests.
    """
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in ["POST", "PUT", "PATCH", "DELETE"]:
            return await call_next(request)
            
        # Support both standard header names
        idempotency_key = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
        
        if not idempotency_key:
            return await call_next(request)

        # In a real app, user_id should be extracted from the authenticated request state.
        user_id = getattr(request.state, "user_id", request.headers.get("x-user-id", "anonymous"))
        cache_key = f"idempotency:{user_id}:{idempotency_key}"

        # 1. Check current state
        cached_data_str = await cache_store.get(cache_key)
        if cached_data_str:
            try:
                cached_data = json.loads(cached_data_str)
                if cached_data.get("status") == "PROCESSING":
                    return JSONResponse(
                        status_code=409, 
                        content={"detail": "This request is already being worked on, do not spin up a duplicate execution."}
                    )
                elif cached_data.get("status") == "COMPLETED":
                    return Response(
                        content=cached_data["response_body"].encode('utf-8') if isinstance(cached_data["response_body"], str) else cached_data["response_body"], 
                        status_code=cached_data["status_code"], 
                        media_type=cached_data.get("media_type", "application/json")
                    )
            except json.JSONDecodeError:
                await cache_store.delete(cache_key)

        # 2. Acquire lock for processing
        lock_data = json.dumps({"status": "PROCESSING"})
        lock_acquired = await cache_store.set(cache_key, lock_data, nx=True, ex=86400)
        
        if not lock_acquired:
            return JSONResponse(
                status_code=409, 
                content={"detail": "This request is already being worked on, do not spin up a duplicate execution."}
            )

        # 3. Process the request safely
        try:
            response = await call_next(request)
            
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
            
            reconstructed_response = Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type
            )

            # Cache successful and client error responses (2xx, 3xx, 4xx)
            if response.status_code < 500:
                completed_data = json.dumps({
                    "status": "COMPLETED",
                    "status_code": response.status_code,
                    "response_body": response_body.decode('utf-8', errors='replace'),
                    "media_type": response.media_type
                })
                await cache_store.set(cache_key, completed_data, ex=86400)
            else:
                await cache_store.delete(cache_key)

            return reconstructed_response

        except Exception as e:
            await cache_store.delete(cache_key)
            raise e
