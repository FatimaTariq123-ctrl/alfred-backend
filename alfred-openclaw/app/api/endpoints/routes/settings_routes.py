from fastapi import APIRouter, Header, HTTPException, Path
from pydantic import BaseModel
from typing import Optional

settings_router = APIRouter()

class ToggleBiometricRequest(BaseModel):
    device_id: str = "dev_4471a9"
    enabled: bool = False

mock_sessions = [
    { "session_id": "ses_11ab", "device_platform": "ios", "is_current": True, "last_active_at": "2026-07-29T09:50:00Z" },
    { "session_id": "ses_22cd", "device_platform": "android", "is_current": False, "last_active_at": "2026-07-20T14:12:00Z" }
]

@settings_router.get("/settings/sessions", tags=["Profile & settings"])
async def list_active_sessions(authorization: Optional[str] = Header("Bearer mock_token")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "success": True,
        "data": mock_sessions
    }

@settings_router.delete("/settings/sessions/{session_id}", tags=["Profile & settings"])
async def revoke_session(session_id: str = Path(...), authorization: Optional[str] = Header("Bearer mock_token")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    session = next((s for s in mock_sessions if s["session_id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session doesn't belong to the caller")
    
    return {
        "success": True,
        "data": { "revoked": True }
    }

@settings_router.patch("/settings/biometric", tags=["Profile & settings"])
async def toggle_biometric_login(request: ToggleBiometricRequest, authorization: Optional[str] = Header("Bearer mock_token")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "success": True,
        "data": { "biometric_enabled": request.enabled }
    }
