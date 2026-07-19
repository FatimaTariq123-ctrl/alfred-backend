from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
from app.api.endpoints.routes import auth_router, chat_router, orders_router, compliance_router, sanctions_router, trade_status_router, trade_prevention_router
from app.backend_services.openclaw_gateway import GatewayClient
from app.backend_services.pii_middleware.pii_masking import PIIMaskingMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API Gateway starting up. Initializing OpenClaw Gateway client.")
    app.state.gateway_client = GatewayClient()
    await app.state.gateway_client.connect()

    yield

    logger.info("API Gateway shutting down. Closing OpenClaw Gateway connection.")
    await app.state.gateway_client.disconnect()


app = FastAPI(
    title="CLAX API Gateway",
    description="Orchestration Backend and Idempotency Enforcement",
    version="1.0.0",
    lifespan=lifespan,
)

# Add PII Masking Middleware to the AI request flow
app.add_middleware(PIIMaskingMiddleware)

# Health endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "gateway"}

# Include routers
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(chat_router, prefix="/api/v1", tags=["Chat"])
app.include_router(orders_router, prefix="/api/v1", tags=["Conditional Orders"])
app.include_router(compliance_router, prefix="/api/v1", tags=["Compliance"])
app.include_router(sanctions_router, prefix="/api/v1", tags=["Sanctions"])
app.include_router(trade_status_router, prefix="/api/v1", tags=["Trade Status"])
app.include_router(trade_prevention_router, prefix="/api/v1", tags=["Trade Prevention"])
