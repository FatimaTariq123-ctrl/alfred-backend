# PII Masking Middleware

Starlette middleware that redacts personally identifiable information from request payloads before they reach the LLM.

## What it does

Intercepts POST/PUT/PATCH requests and masks:
- Email addresses → `[REDACTED_EMAIL]`
- HKID numbers → `[REDACTED_HKID]`
- Phone numbers → `[REDACTED_PHONE]`
- Account numbers → `[REDACTED_ACCOUNT_NUMBER]`
- Name fields (user_name, first_name, etc.) → `[REDACTED_NAME]`

Logs audit summaries (counts only, no raw PII) for compliance.

## Status

**Active** — imported by `main.py`, added as app-level middleware.

## Key files

- `pii_masking.py` — `PIIMaskingMiddleware` class

## How it's used

```python
from app.backend_services.pii_middleware.pii_masking import PIIMaskingMiddleware

app.add_middleware(PIIMaskingMiddleware)
```
