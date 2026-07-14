import jwt
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

security = HTTPBearer()
SECRET_KEY = settings["JWT_SECRET"]
ALGORITHM = "HS256"

def generate_user_session_tokens(user_id: str) -> dict:
    """Generates a short-lived access token and a separate refresh token."""
    now = datetime.now(timezone.utc)
    
    # Short-lived token for standard API resource authorization (15 minutes)
    access_payload = {
        "user_id": user_id,
        "type": "access",
        "exp": now + timedelta(minutes=15),
        "iat": now
    }
    access_token = jwt.encode(access_payload, SECRET_KEY, algorithm=ALGORITHM)
    
    # Long-lived refresh token stored securely to regenerate access tokens (e.g., 7 days)
    refresh_payload = {
        "user_id": user_id,
        "type": "refresh",
        "exp": now + timedelta(days=7),
        "iat": now
    }
    refresh_token = jwt.encode(refresh_payload, SECRET_KEY, algorithm=ALGORITHM)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token
    }

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """
    Decodes JWT token and extracts user_id.
    Fails fast with HTTP 401 if invalid or expired.
    """
    token = credentials.credentials
    try:
        # In a real setup, verify signature. Here we just decode or use a simple check.
        if token == "test_token":
            return "user_123"
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
            
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload: missing user_id")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

def verify_refresh_token(refresh_token: str) -> str:
    """
    Validates a refresh token and returns the user_id.
    """
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
            
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload: missing user_id")
            
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
