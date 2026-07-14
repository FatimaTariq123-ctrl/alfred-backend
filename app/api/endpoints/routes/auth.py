from fastapi import APIRouter, HTTPException
from app.schemas.auth import TokenResponse, RefreshTokenRequest, LoginRequest
from app.core.security import generate_user_session_tokens, verify_refresh_token

router = APIRouter()

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    Issue the initial token pair.
    In a real app, this would verify credentials.
    """
    tokens = generate_user_session_tokens(request.user_id)
    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"]
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest):
    """
    Validates the refresh token and returns a new pair of access and refresh tokens.
    Token rotation provides an extra layer of security.
    """
    user_id = verify_refresh_token(request.refresh_token)
    
    tokens = generate_user_session_tokens(user_id)
    
    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"]
    )
