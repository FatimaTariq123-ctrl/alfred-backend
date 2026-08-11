from fastapi import APIRouter
from pydantic import BaseModel

auth_router = APIRouter()
onboarding_router = APIRouter()

class EmailCheckResponse(BaseModel): success: bool; data: dict
class InitiateRequest(BaseModel): email: str; full_name: str = None; device_id: str
class VerifyOtpRequest(BaseModel): otp_session_id: str; code: str
class ResendOtpRequest(BaseModel): otp_session_id: str
class OAuthRequest(BaseModel): id_token: str; device_id: str
class BiometricEnableRequest(BaseModel): device_id: str; public_key: str
class BiometricLoginRequest(BaseModel): device_id: str; challenge_id: str; signature: str
class RefreshRequest(BaseModel): refresh_token: str; device_id: str
class LogoutRequest(BaseModel): refresh_token: str

@auth_router.get("/email/check", response_model=EmailCheckResponse)
async def check_email_availability(email: str, purpose: str):
    return {"success": True, "data": {"email": email, "exists": False, "recommended_action": "continue_signup"}}

@auth_router.post("/signup/initiate")
async def signup_initiate(request: InitiateRequest):
    return {"success": True, "data": {"otp_session_id": "otp_6f2a91", "expires_in": 900, "resend_available_in": 42}}

@auth_router.post("/signup/verify-otp")
async def signup_verify_otp(request: VerifyOtpRequest):
    return {"success": True, "data": {"user": {"id": "usr_8f3ac1d0", "email": "johndoe@company.com", "full_name": "John Doe", "onboarding_complete": False}, "access_token": "***", "refresh_token": "***", "expires_in": 900}}

@auth_router.post("/signin/initiate")
async def signin_initiate(request: InitiateRequest):
    return {"success": True, "data": {"otp_session_id": "otp_6f2a91", "expires_in": 900, "resend_available_in": 42}}

@auth_router.post("/signin/verify-otp")
async def signin_verify_otp(request: VerifyOtpRequest):
    return {"success": True, "data": {"user": {"id": "usr_8f3ac1d0", "email": "johndoe@company.com", "full_name": "John Doe", "onboarding_complete": True}, "access_token": "***", "refresh_token": "***", "expires_in": 900}}

@auth_router.post("/otp/resend")
async def resend_otp(request: ResendOtpRequest):
    return {"success": True, "data": {"resend_available_in": 60}}

@auth_router.post("/oauth/{provider}")
async def oauth_signup_signin(provider: str, request: OAuthRequest):
    return {"success": True, "data": {"user": {"id": "usr_8f3ac1d0", "email": "johndoe@company.com", "full_name": "John Doe", "onboarding_complete": True}, "access_token": "***", "refresh_token": "***", "expires_in": 900, "is_new_user": False}}

@auth_router.post("/biometric/enable")
async def biometric_enable(request: BiometricEnableRequest):
    return {"success": True, "data": {"biometric_enabled": True}}

@auth_router.get("/biometric/challenge")
async def biometric_challenge(device_id: str):
    return {"success": True, "data": {"challenge_id": "chl_9a21", "nonce": "b64-random-nonce", "expires_in": 60}}

@auth_router.post("/biometric/login")
async def biometric_login(request: BiometricLoginRequest):
    return {"success": True, "data": {"user": {"id": "usr_8f3ac1d0"}, "access_token": "***", "refresh_token": "***"}}

@auth_router.post("/refresh")
async def refresh_token(request: RefreshRequest):
    return {"success": True, "data": {"access_token": "***", "refresh_token": "***", "expires_in": 900}}

@auth_router.post("/logout")
async def logout(request: LogoutRequest):
    return {"success": True, "data": {"logged_out": True}}

@onboarding_router.get("/questions")
async def get_questions():
    return {"success": True, "data": {"questions": [{"id": "q_risk", "prompt": "How would you describe your investing style?", "options": ["Cautious Saver", "Steady Grower", "Ambitious Builder"]}]}}

@onboarding_router.post("/answers")
async def post_answers(answers: dict):
    return {"success": True, "data": {"investor_archetype": "Ambitious Builder", "onboarding_complete": True}}
