from fastapi import FastAPI
from app.api.routes import orders, artifacts
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title="CLAX API Gateway",
    description="Orchestration Backend and Idempotency Enforcement",
    version="1.0.0"
)

# Health endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "gateway"}

# Include routers
app.include_router(orders.router, prefix="/api/v1/orders", tags=["Orders"])
app.include_router(artifacts.router, prefix="/api/v1/artifacts", tags=["Artifacts"])

@app.on_event("startup")
async def startup_event():
    logger.info("API Gateway starting up. Stateless and twelve-factor compliant.")