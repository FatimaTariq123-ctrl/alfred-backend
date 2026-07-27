from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any

# Existing JWT schemas and utils
from app.backend_services.jwt_auth.schemas import TokenResponse, RefreshTokenRequest, LoginRequest
from app.backend_services.jwt_auth.security import generate_user_session_tokens, verify_refresh_token

# New Auth schemas
from app.schemas.auth_schema import (
    SignupEmailInitRequest, SignupEmailInitResponse,
    SignupEmailVerifyRequest, SignupEmailVerifyResponse,
    SignupGoogleRequest, SignupAppleRequest, SignupSocialResponse,
    PasskeyRegisterOptionsRequest, PasskeyRegisterVerifyRequest, PasskeyRegisterVerifyResponse,
    SigninPasskeyOptionsRequest, SigninPasskeyVerifyRequest, SigninPasskeyVerifyResponse,
    SigninEmailInitRequest, SigninEmailInitResponse,
    SigninEmailVerifyRequest, SigninEmailVerifyResponse,
    SigninGoogleRequest, SigninAppleRequest, SigninSocialResponse,
    SessionData
)

auth_router = APIRouter()

# --- Legacy endpoints (Kept for backwards compatibility) ---

@auth_router.post("/login", response_model=TokenResponse)
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

@auth_router.post("/refresh", response_model=TokenResponse)
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

# --- SIGN UP FLOW ---

@auth_router.post("/signup/email/init", response_model=SignupEmailInitResponse)
async def signup_email_init(request: SignupEmailInitRequest):
    """
    Initiates the email signup flow.
    Sends a 6-digit code to the user's email.
    """
    # TODO: Implement email sending logic
    return SignupEmailInitResponse(signup_session_id="dummy_signup_session_id")

@auth_router.post("/signup/email/verify", response_model=SignupEmailVerifyResponse)
async def signup_email_verify(request: SignupEmailVerifyRequest):
    """
    Verifies the 6-digit code and creates the account.
    Returns session tokens and a provisional token for passkey binding.
    """
    # TODO: Implement code verification and user creation
    return SignupEmailVerifyResponse(
        user_id="new_user_123",
        provisional_token="dummy_provisional_token",
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh")
    )

@auth_router.post("/signup/google", response_model=SignupSocialResponse)
async def signup_google(request: SignupGoogleRequest):
    """
    Signs up a user using a Google ID token.
    """
    # TODO: Verify Google token and create user
    return SignupSocialResponse(
        user_id="new_user_google_123",
        provisional_token="dummy_provisional_token",
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh")
    )

@auth_router.post("/signup/apple", response_model=SignupSocialResponse)
async def signup_apple(request: SignupAppleRequest):
    """
    Signs up a user using Apple tokens.
    """
    # TODO: Verify Apple token and create user
    return SignupSocialResponse(
        user_id="new_user_apple_123",
        provisional_token="dummy_provisional_token",
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh")
    )

# --- PASSKEY REGISTRATION ---

@auth_router.post("/passkey/register/options")
async def passkey_register_options(request: PasskeyRegisterOptionsRequest) -> Dict[str, Any]:
    """
    Returns the WebAuthn creation challenge for registering a new passkey (Face ID/Touch ID).
    """
    # TODO: Generate WebAuthn creation challenge
    return {"challenge": "dummy_challenge_string", "user": {"id": "encoded_id", "name": "user"}}

@auth_router.post("/passkey/register/verify", response_model=PasskeyRegisterVerifyResponse)
async def passkey_register_verify(request: PasskeyRegisterVerifyRequest):
    """
    Verifies the attestation response from the device and binds the passkey to the account.
    """
    # TODO: Verify WebAuthn attestation response
    return PasskeyRegisterVerifyResponse(
        credential_id="dummy_credential_id",
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh")
    )

# --- SIGN IN FLOW ---

@auth_router.post("/signin/passkey/options")
async def signin_passkey_options(request: SigninPasskeyOptionsRequest) -> Dict[str, Any]:
    """
    Returns the WebAuthn assertion challenge to initiate passkey sign-in.
    """
    # TODO: Generate WebAuthn assertion challenge
    return {"challenge": "dummy_assertion_challenge"}

@auth_router.post("/signin/passkey/verify", response_model=SigninPasskeyVerifyResponse)
async def signin_passkey_verify(request: SigninPasskeyVerifyRequest):
    """
    Verifies the passkey assertion and logs the user in.
    """
    # TODO: Verify WebAuthn assertion response
    return SigninPasskeyVerifyResponse(
        user_id="existing_user_123",
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh")
    )

@auth_router.post("/signin/email/init", response_model=SigninEmailInitResponse)
async def signin_email_init(request: SigninEmailInitRequest):
    """
    Fallback sign-in: Initiates email sign-in by sending a one-time code.
    """
    # TODO: Implement email sending logic
    return SigninEmailInitResponse(signin_session_id="dummy_signin_session_id")

@auth_router.post("/signin/email/verify", response_model=SigninEmailVerifyResponse)
async def signin_email_verify(request: SigninEmailVerifyRequest):
    """
    Fallback sign-in: Verifies the email code.
    If the device lacks a passkey, signals that passkey binding is required.
    """
    # TODO: Implement code verification
    return SigninEmailVerifyResponse(
        user_id="existing_user_123",
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh"),
        requires_device_binding=True
    )

@auth_router.post("/signin/google", response_model=SigninSocialResponse)
async def signin_google(request: SigninGoogleRequest):
    """
    Fallback sign-in via Google.
    """
    # TODO: Verify Google token
    return SigninSocialResponse(
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh"),
        requires_device_binding=True
    )

@auth_router.post("/signin/apple", response_model=SigninSocialResponse)
async def signin_apple(request: SigninAppleRequest):
    """
    Fallback sign-in via Apple.
    """
    # TODO: Verify Apple token
    return SigninSocialResponse(
        session=SessionData(access_token="dummy_access", refresh_token="dummy_refresh"),
        requires_device_binding=True
    )
