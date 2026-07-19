# OpenClaw Gateway Client

HTTP client library for the OpenClaw Gateway API.

## What it does

Sends chat messages to the OpenClaw Gateway (`POST /v1/responses`) and returns the response. Handles connection pooling, health checks, reconnection, and response parsing.

## Status

**Active** — imported by `main.py`, `chat.py`, and `chat_service.py`.

## Key files

- `gateway_client.py` — `GatewayClient` class with `connect()`, `disconnect()`, `send_chat()`
- `__init__.py` — exports `GatewayClient` and exception classes
- `test_gateway_client.py` — 24 integration tests (respx-mocked)

## How it's used

```python
from app.backend_services.openclaw_gateway import GatewayClient

client = GatewayClient()
await client.connect()
response = await client.send_chat(message="Hello", model="gemini-2.0-flash")
await client.disconnect()
```
