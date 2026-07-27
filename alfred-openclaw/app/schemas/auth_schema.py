from pydantic import BaseModel
from typing import Optional, Dict, Any

class SessionData(BaseModel):
    access_token: str
    refresh_token: str

# Sign Up Flow
class SignupEmailInitRequest(BaseModel):
    email: str
    username: str

class SignupEmailInitResponse(BaseModel):
    signup_session_id: str

class SignupEmailVerifyRequest(BaseModel):
    signup_session_id: str
    code: str

class SignupEmailVerifyResponse(BaseModel):
    user_id: str
    provisional_token: str
    session: SessionData

class SignupGoogleRequest(BaseModel):
    id_token: str

class SignupAppleRequest(BaseModel):
    identity_token: str
    authorization_code: str

class SignupSocialResponse(BaseModel):
    user_id: str
    provisional_token: str
    session: SessionData

# Passkey Registration
class PasskeyRegisterOptionsRequest(BaseModel):
    provisional_token: str
    device_id: str

class PasskeyRegisterVerifyRequest(BaseModel):
    provisional_token: str
    device_id: str
    attestation_response: Dict[str, Any]

class PasskeyRegisterVerifyResponse(BaseModel):
    credential_id: str
    session: SessionData

# Sign In Flow
class SigninPasskeyOptionsRequest(BaseModel):
    email_or_username: Optional[str] = None

class SigninPasskeyVerifyRequest(BaseModel):
    credential_id: str
    assertion_response: Dict[str, Any]

class SigninPasskeyVerifyResponse(BaseModel):
    user_id: str
    session: SessionData

class SigninEmailInitRequest(BaseModel):
    email: str

class SigninEmailInitResponse(BaseModel):
    signin_session_id: str

class SigninEmailVerifyRequest(BaseModel):
    signin_session_id: str
    code: str

class SigninEmailVerifyResponse(BaseModel):
    user_id: str
    session: SessionData
    requires_device_binding: bool

class SigninGoogleRequest(BaseModel):
    id_token: str

class SigninAppleRequest(BaseModel):
    identity_token: str
    authorization_code: str

class SigninSocialResponse(BaseModel):
    session: SessionData
    requires_device_binding: bool
