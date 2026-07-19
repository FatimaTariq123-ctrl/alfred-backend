from fastapi import APIRouter, Depends, HTTPException

from app.schemas.sanctions_schema import SanctionEntity
from app.services.sanctions_service import SanctionsService
from app.backend_services.jwt_auth.security import get_current_user

sanctions_router = APIRouter()


def get_sanctions_service() -> SanctionsService:
    return SanctionsService()


# ==========================================
# POST /admin/blacklist — upsert
# ==========================================
@sanctions_router.post("/admin/blacklist")
def add_or_update_sanction(
    entity: SanctionEntity,
    user_id: str = Depends(get_current_user),
    service: SanctionsService = Depends(get_sanctions_service),
):
    try:
        data = service.upsert(entity.ticker, entity.name, entity.regulatory_body)
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
    return {"message": "Sanction entity added/updated successfully", "data": data}


# ==========================================
# GET /admin/blacklist/{ticker} — lookup
# ==========================================
@sanctions_router.get("/admin/blacklist/{ticker}")
def get_sanction(
    ticker: str,
    user_id: str = Depends(get_current_user),
    service: SanctionsService = Depends(get_sanctions_service),
):
    try:
        result = service.get_by_ticker(ticker)
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
    if not result:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return result
