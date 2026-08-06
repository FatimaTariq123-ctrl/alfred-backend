from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, constr
from typing import Optional

user_router = APIRouter()

class UpdateProfileRequest(BaseModel):
    full_name: constr(min_length=1, max_length=100) = "John A. Doe"

class UpdateCurrencyRequest(BaseModel):
    currency: constr(min_length=3, max_length=3) = "HKD"

# Mocked state for testing
mock_user_profile = {
    "id": "usr_8f3ac1d0",
    "email": "johndoe@company.com",
    "full_name": "John Doe",
    "investor_archetype": "Ambitious Builder",
    "member_since": "2026-01-08",
    "default_currency": "USD",
    "portfolio_value": "65000.00",
    "portfolio_today_change_percent": "4.2"
}

currency_map = {
    "USD": "US Dollar",
    "HKD": "Hong Kong Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "SGD": "Singapore Dollar"
}

@user_router.get("/users/me", tags=["Profile & settings"])
async def get_current_user_profile(authorization: Optional[str] = Header("Bearer mock_token")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "success": True,
        "data": mock_user_profile
    }

@user_router.patch("/users/me", tags=["Profile & settings"])
async def update_profile(request: UpdateProfileRequest, authorization: Optional[str] = Header("Bearer mock_token")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    mock_user_profile["full_name"] = request.full_name
    return {
        "success": True,
        "data": mock_user_profile
    }

@user_router.patch("/users/me/currency", tags=["Profile & settings"])
async def update_default_currency(request: UpdateCurrencyRequest, authorization: Optional[str] = Header("Bearer mock_token")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    currency = request.currency.upper()
    if currency not in currency_map:
        raise HTTPException(status_code=422, detail="Unsupported currency code")
    
    mock_user_profile["default_currency"] = currency
    return {
        "success": True,
        "data": {
            "default_currency": currency,
            "currency_name": currency_map[currency]
        }
    }

@user_router.delete("/users/me", tags=["Profile & settings"])
async def delete_account(authorization: Optional[str] = Header("Bearer mock_token")):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "success": True,
        "data": { "status": "deletion_scheduled" }
    }
