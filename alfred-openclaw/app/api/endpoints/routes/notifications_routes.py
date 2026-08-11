from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(tags=["Notifications"])

# Mock Authentication
from fastapi.security import APIKeyHeader
api_key_header = APIKeyHeader(name="Authorization", auto_error=True, description="Enter Mock Token (e.g. Bearer mock_token)")

def verify_token(api_key: str = Depends(api_key_header)):
    if not api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return api_key

class Notification(BaseModel):
    id: str
    type: str
    title: str
    body: str
    read: bool
    created_at: str

class Meta(BaseModel):
    next_cursor: Optional[str] = None
    has_more: bool

class NotificationsResponse(BaseModel):
    success: bool
    data: List[Notification]
    meta: Meta

class ReadResponseData(BaseModel):
    updated: bool

class ReadResponse(BaseModel):
    success: bool
    data: ReadResponseData

class NotificationPreferences(BaseModel):
    price_alerts: bool = True
    autopilot_trades: bool = True
    portfolio_recommendations: bool = True
    marketing: bool = False

class PushTokenRequest(BaseModel):
    device_id: str
    push_token: str
    platform: str

class PushTokenResponseData(BaseModel):
    registered: bool

class PushTokenResponse(BaseModel):
    success: bool
    data: PushTokenResponseData

@router.get("/notifications", response_model=NotificationsResponse, summary="List Notifications")
def list_notifications(
    cursor: Optional[str] = None, 
    limit: Optional[int] = None, 
    unread_only: Optional[bool] = None,
    token: str = Depends(verify_token),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    return {
        "success": True,
        "data": [
            { "id": "ntf_10ab", "type": "price_alert", "title": "PLTR hit your target", "body": "PLTR crossed $161.56", "read": False, "created_at": "2026-07-29T10:05:00Z" }
        ],
        "meta": { "next_cursor": None, "has_more": False }
    }

@router.patch("/notifications/{id}/read", response_model=ReadResponse, summary="Mark Notification as Read")
def mark_notification_read(
    id: str,
    token: str = Depends(verify_token),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    return { "success": True, "data": { "updated": True } }

@router.post("/notifications/read-all", response_model=ReadResponse, summary="Mark All as Read")
def mark_all_read(
    token: str = Depends(verify_token),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    return { "success": True, "data": { "updated": True } }

@router.get("/notifications/preferences", response_model=NotificationPreferences, summary="Get Notification Preferences")
def get_preferences(
    token: str = Depends(verify_token),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    return { "price_alerts": True, "autopilot_trades": True, "portfolio_recommendations": True, "marketing": False }

@router.patch("/notifications/preferences", response_model=NotificationPreferences, summary="Update Notification Preferences")
def update_preferences(
    preferences: NotificationPreferences,
    token: str = Depends(verify_token),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    return {"price_alerts": True, "autopilot_trades": True, "portfolio_recommendations": True, "marketing": False}

@router.post("/devices/push-token", response_model=PushTokenResponse, summary="Register Push Token")
def register_push_token(
    payload: PushTokenRequest,
    token: str = Depends(verify_token),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    return { "success": True, "data": { "registered": True } }
