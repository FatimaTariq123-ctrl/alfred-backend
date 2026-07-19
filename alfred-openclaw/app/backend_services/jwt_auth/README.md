# JWT Authentication

Shared JWT token generation, validation, and refresh logic.

## What it does

- Generates short-lived access tokens (15 min) and refresh tokens (7 days)
- Validates tokens via FastAPI's `HTTPBearer` dependency
- Handles token type checking, expiry, and refresh rotation

## Status

**Active** — imported by `auth_routes.py` and `chat.py`.

## Key files

- `security.py` — `generate_user_session_tokens()`, `get_current_user()`, `verify_refresh_token()`
- `schemas.py` — `TokenResponse`, `LoginRequest`, `RefreshTokenRequest` models

## How it's used

```python
from app.backend_services.jwt_auth.security import get_current_user

@router.get("/protected")
def protected_route(user_id: str = Depends(get_current_user)):
    return {"user_id": user_id}
```
