import os
import sys
import logging
from enum import Enum
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# 1. Cloud-Native Logging (Twelve-Factor: stdout only, no local /tmp files)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger("d4_trade_state")

# 2. Native OS Environment Lookups (No .env files allowed)
class ConfigurationError(Exception):
    pass

def get_env_var(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ConfigurationError(f"Missing mandatory environment variable: {var_name}")
    return value

# 3. State Transition Table
class TradeState(str, Enum):
    PROCESSING = "PROCESSING"   # Initial atomic lock state
    RECONCILING = "RECONCILING" # Transient error, picked up by D5 background worker
    SUCCESS = "SUCCESS"         # Terminal success
    FAILED = "FAILED"           # Terminal failure
    VETOED = "VETOED"           # Terminal compliance/slippage rejection

class TradeStatusResponse(BaseModel):
    idempotency_key: str
    status: TradeState
    source: str
    payload: dict | None = None

# Stub for JWT Authentication (from Task E5)
async def verify_jwt(authorization: str = Depends(lambda: "Bearer stub_token")) -> str:
    """
    Validates the 15-min access token and extracts the user_id.
    """
    # Simulate JWT decoding
    return "user_123"

# 4. Encapsulated Execution Scope (No global state bleed)
class TradeStatusService:
    def __init__(self, redis_client: redis.Redis, db_session: AsyncSession):
        self.redis_client = redis_client
        self.db_session = db_session

    async def get_status(self, user_id: str, idempotency_key: str) -> TradeStatusResponse:
        # Step 1: Redis Front-line Check (Mitigates Thundering Herd)
        redis_key = f"idempotency:{user_id}:{idempotency_key}"
        cached_state = await self.redis_client.get(redis_key)
        
        if cached_state:
            state_str = cached_state.decode("utf-8")
            logger.info(f"Cache HIT for {redis_key}: {state_str}")
            return TradeStatusResponse(
                idempotency_key=idempotency_key,
                status=TradeState(state_str),
                source="redis",
                payload=None # Would fetch cached success payload here if applicable
            )

        # Step 2: Database Fallback 
        logger.info(f"Cache MISS for {redis_key}. Falling back to clax_trade_ledger.")
        query = text("""
            SELECT status, payload 
            FROM clax_trade_ledger 
            WHERE user_id = :uid AND client_idempotency_key = :ikey
        """)
        
        result = await self.db_session.execute(query, {"uid": user_id, "ikey": idempotency_key})
        row = result.fetchone()

        if not row:
            logger.warning(f"Trade not found for key {idempotency_key}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Trade instruction not found or invalid idempotency key"
            )

        return TradeStatusResponse(
            idempotency_key=idempotency_key,
            status=TradeState(row.status),
            source="postgresql",
            payload=row.payload
        )

# FastAPI App Setup
app = FastAPI(title="Clax Trade State Machine - Task D4")

# Dependency Injection for isolated per-request clients
async def get_redis_client():
    client = redis.from_url(get_env_var("REDIS_URL"))
    try:
        yield client
    finally:
        await client.aclose()

async def get_db_session():
    # pool_size=10, max_overflow=20 as required by Task A2
    engine = create_async_engine(get_env_var("DATABASE_URL"), pool_size=10, max_overflow=20)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session

# 5. API Endpoint
@app.get("/trade/status", response_model=TradeStatusResponse)
async def trade_status_endpoint(
    idempotency_key: str,
    user_id: str = Depends(verify_jwt),
    redis_client: redis.Redis = Depends(get_redis_client),
    db_session: AsyncSession = Depends(get_db_session)
):
    """
    GET /trade/status
    Prioritizes Redis atomic lock state, falling back to PostgreSQL.
    """
    service = TradeStatusService(redis_client, db_session)
    return await service.get_status(user_id, idempotency_key)