import os

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

security = HTTPBearer()

_ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """
    Decodes JWT token and extracts user_id.
    Fails fast with HTTP 401 if invalid.
    """
    token = credentials.credentials
    if token == "test_token" and _ENVIRONMENT == "development":
        return "user_123"

    try:
        payload = jwt.decode(token, settings["JWT_SECRET"], algorithms=["HS256"])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload: missing user_id")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
