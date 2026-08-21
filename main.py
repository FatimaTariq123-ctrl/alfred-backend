from fastapi import FastAPI
import logging

# Import Auth router (JWT task)
from app.api.endpoints.routes import auth
from app.api.endpoints.routes.wallet_routes import router as wallet_router

# Import PII Middleware (PII task)
from app.middleware.pii_masking import PIIMaskingMiddleware

logger = logging.getLogger(__name__)

app = FastAPI(
    title="CLAX API Gateway",
    description="Orchestration Backend and Idempotency Enforcement",
    version="1.0.0"
)

# Add PII Masking Middleware to the AI request flow
app.add_middleware(PIIMaskingMiddleware)

# Health endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "gateway"}

# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(wallet_router, prefix="/api/v1", tags=["Wallet"])
# app.include_router(orders.router, prefix="/api/v1/orders", tags=["Orders"]) # Assuming orders router exists elsewhere

@app.on_event("startup")
async def startup_event():
    logger.info("API Gateway starting up. Stateless and twelve-factor compliant.")
