from fastapi import APIRouter, Depends, HTTPException, Response

from app.schemas.compliance_schema import VetoRequest
from app.services.compliance_service import ComplianceService, VETO_STATUS_CODES
from app.backend_services.jwt_auth.security import get_current_user

compliance_router = APIRouter()


def get_compliance_service() -> ComplianceService:
    return ComplianceService()


# ==========================================
# POST /compliance/veto
# ==========================================
@compliance_router.post("/compliance/veto")
def apply_veto(
    request: VetoRequest,
    response: Response,
    user_id: str = Depends(get_current_user),
    service: ComplianceService = Depends(get_compliance_service),
):
    try:
        result = service.apply_veto(
            ledger_id=request.ledger_id,
            veto_type=request.veto_type,
            veto_reason=request.veto_reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to write audit log")

    # Map veto_type to the correct HTTP status code
    response.status_code = VETO_STATUS_CODES[result["veto_type"]]
    return result
