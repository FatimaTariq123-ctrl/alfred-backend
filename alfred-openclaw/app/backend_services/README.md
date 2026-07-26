# Backend Services

Shared infrastructure, libraries, and standalone services used by the Alfred FastAPI application.

## Directory Structure

```
backend_services/
├── database_service/          # PostgreSQL connection pool (Library)
├── jwt_auth/                  # JWT authentication (Library)
├── openclaw_gateway/          # OpenClaw Gateway client (Library)
├── pii_middleware/             # PII masking middleware (Middleware)
├── Redis-Gateway/             # Idempotent order processing (Microservice)
└── retry-reconciliation-worker/  # Trade retry worker (Worker)
```

---

## 1. database_service

**Type:** Library
**Purpose:** PostgreSQL connection pool utility using `psycopg2`.

### Responsibilities
- Creates and manages a `SimpleConnectionPool` (1–30 connections) to the Neon PostgreSQL database
- Provides a `pre_warm_pool()` function for startup optimization

### Main Modules
- `database_pool.py` — `db_pool` instance and `pre_warm_pool()` function

### Dependencies
- `psycopg2` / `psycopg2-binary`
- `NEON_DATABASE_URL` environment variable

### HTTP Endpoints
None (library module).

### Imported by Main App
Yes — lazy import in `app/api/endpoints/routes/chat.py` for the `/chat/history` endpoint.

### Notes
- Uses raw psycopg2, not SQLAlchemy
- Loads `NEON_DATABASE_URL` via `dotenv` with relative path

---

## 2. jwt_auth

**Type:** Library
**Purpose:** Shared JWT token generation, validation, and refresh logic.

### Responsibilities
- Generates short-lived access tokens (15 min) and refresh tokens (7 days)
- Validates tokens via FastAPI's `HTTPBearer` dependency
- Handles token type checking, expiry, and refresh rotation

### Main Modules
- `security.py` — `generate_user_session_tokens()`, `get_current_user()`, `verify_refresh_token()`
- `schemas.py` — `TokenResponse`, `LoginRequest`, `RefreshTokenRequest` models

### Dependencies
- `PyJWT`
- `fastapi` (HTTPBearer, Security)
- `app.config.config.settings` (JWT_SECRET)

### HTTP Endpoints
None (library module).

### Imported by Main App
Yes — used by all active routers:
- `auth_routes.py` — token generation and refresh
- `chat.py`, `orders.py`, `compliance.py`, `sanctions.py`, `trade_status.py`, `trade_prevention.py` — `get_current_user` dependency

### Notes
- Single source of truth for JWT authentication across the application
- Includes a `test_token` backdoor for development (returns `user_123`)

---

## 3. openclaw_gateway

**Type:** Library
**Purpose:** HTTP client library for the OpenClaw Gateway OpenResponses API.

### Responsibilities
- Sends chat messages to the OpenClaw Gateway (`POST /v1/responses`)
- Manages connection lifecycle (connect/disconnect/ensure_connected)
- Performs health checks (`/health` with `/v1/models` fallback)
- Parses response text from the OpenResponses output format

### Main Modules
- `gateway_client.py` — `GatewayClient` class with `connect()`, `disconnect()`, `send_chat()`
- `__init__.py` — exports `GatewayClient` and exception classes
- `test_gateway_client.py` — 24 integration tests (respx-mocked)

### Dependencies
- `httpx`
- `app.config.config` (OPENCLAW_GATEWAY_URL, OPENCLAW_GATEWAY_TOKEN, etc.)

### HTTP Endpoints
None (client library).

### Imported by Main App
Yes — used by:
- `main.py` — lifespan initialization/teardown
- `chat.py` — POST /chat endpoint
- `chat_service.py` — pass-through to gateway

### Notes
- Reads `OPENCLAW_GATEWAY_URL` env var (default: `http://localhost:18789`)
- Gateway auth token: `OPENCLAW_GATEWAY_TOKEN` env var, falls back to `openclaw.json`
- Gateway's `/v1/responses` must be enabled in `openclaw.json`

---

## 4. pii_middleware

**Type:** Middleware
**Purpose:** Starlette ASGI middleware that redacts personally identifiable information from request payloads.

### Responsibilities
- Intercepts POST/PUT/PATCH requests and masks PII:
  - Email addresses → `[REDACTED_EMAIL]`
  - HKID numbers → `[REDACTED_HKID]`
  - Phone numbers → `[REDACTED_PHONE]`
  - Account numbers → `[REDACTED_ACCOUNT_NUMBER]`
  - Name fields (user_name, first_name, etc.) → `[REDACTED_NAME]`
- Logs audit summaries (counts only, no raw PII) for compliance

### Main Modules
- `pii_masking.py` — `PIIMaskingMiddleware` class

### Dependencies
- `starlette` (ASGI)

### HTTP Endpoints
None (middleware).

### Imported by Main App
Yes — added as app-level middleware in `main.py`.

### Notes
- Pre-compiled regex patterns for performance
- Only processes requests with JSON content type

---

## 5. Redis-Gateway

**Type:** Microservice (standalone deployable)
**Purpose:** Idempotent order processing and artifact generation with Redis locking.

### Responsibilities
- Order verification — creates temporary Redis-locked verification tokens
- Order commit — processes trades with Redis idempotency locks, persists to PostgreSQL
- Artifact generation — streams reports directly to S3 via Boto3

### Main Modules
- `app/main.py` — FastAPI app entry point
- `app/api/routes/orders.py` — `/verify` and `/commit` endpoints
- `app/api/routes/artifacts.py` — `/generate` endpoint
- `app/services/idempotency.py` — `IdempotencyEngine` (Redis atomic locks)
- `app/services/cloud_storage.py` — S3 streaming via Boto3
- `app/services/redis_client.py` — async Redis connection pool
- `app/schemas/payload.py` — `CLAXAgentOutputContract`, `TradeVerificationResponse`
- `app.config.config.py` — twelve-factor configuration
- `app/core/security.py` — JWT authentication
- `test_a5.py` — integration test

### Dependencies
- `fastapi`, `redis.asyncio`, `sqlalchemy`, `boto3`
- `REDIS_URL`, `JWT_SECRET`, `DATABASE_URL`, `AWS_*` environment variables

### HTTP Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/orders/verify` | Create verification token |
| POST | `/api/v1/orders/commit` | Process and persist trade |
| POST | `/api/v1/artifacts/generate` | Stream report to S3 |

### Imported by Main App
No — runs as a separate container via `docker-compose up`.

### Notes
- Has its own `Dockerfile` and `docker-compose.yml`
- Runs on port 8000 with its own Redis instance
- Does not share code with the main Alfred FastAPI app

---

## 6. retry-reconciliation-worker

**Type:** Worker (standalone background process)
**Purpose:** Retries failed trade executions every 60 seconds.

### Responsibilities
- Scans `clax_trade_ledger` every 60 seconds for trades with status `RECONCILING`
- Acquires `FOR UPDATE SKIP LOCKED` row locks for atomic processing
- Retries downstream execution with 1s → 2s → 4s bounded backoff (3 attempts max)
- Marks trades as `SUCCESS`, `VETOED` (on 403/422), or `FAILED` (after exhausting retries)

### Main Modules
- `d5_reconciliation_worker.py` — `worker_loop()` (60s scan) + `process_trade_by_id()` (bounded retry)

### Dependencies
- `sqlalchemy[asyncio]`, `asyncpg`
- `DATABASE_URL` environment variable

### HTTP Endpoints
None (background worker).

### Imported by Main App
No — runs as `python d5_reconciliation_worker.py`.

### Notes
- Uses async SQLAlchemy for non-blocking database operations
- Implements `FOR UPDATE SKIP LOCKED` for concurrent worker safety
- Handles compliance vetoes (403/422) as terminal states

---

## Architecture Summary

### How the Components Work Together

```
┌─────────────────────────────────────────────────────────────┐
│                    Alfred FastAPI App                         │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │   Auth   │  │   Chat   │  │  Orders  │  │Compliance│   │
│  │  Router  │  │  Router  │  │  Router  │  │  Router  │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │              │          │
│  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐   │
│  │  Sanctions│  │  Trade   │  │  Trade   │  │   PII    │   │
│  │  Router  │  │  Status  │  │Prevention│  │Middleware│   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │              │          │
│  ┌────┴──────────────┴──────────────┴──────────────┴──────┐ │
│  │              Shared Infrastructure                      │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │ │
│  │  │ jwt_auth  │  │database_ │  │openclaw_ │             │ │
│  │  │          │  │ service  │  │ gateway  │             │ │
│  │  └──────────┘  └──────────┘  └──────────┘             │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ HTTP
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenClaw Gateway                             │
│              POST /v1/responses                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│               Standalone Services                             │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │  Redis-Gateway   │  │  Reconciliation  │                │
│  │  (Docker)        │  │  Worker          │                │
│  │  - Orders        │  │  - Retry logic   │                │
│  │  - Artifacts     │  │  - 60s scan      │                │
│  └──────────────────┘  └──────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

### Component Interactions

1. **Alfred FastAPI** is the main entry point. It:
   - Registers all API routers under `/api/v1`
   - Initializes the OpenClaw Gateway client on startup
   - Applies PII masking middleware to all requests
   - Uses JWT authentication for all protected endpoints

2. **OpenClaw Gateway** handles LLM inference:
   - The `openclaw_gateway` client sends chat messages via HTTP
   - Gateway processes requests and returns responses
   - Client handles connection pooling and health checks

3. **Redis-Gateway** runs independently:
   - Provides idempotent order processing with Redis locks
   - Generates artifacts streamed to S3
   - Deployed as a separate Docker container

4. **Reconciliation Worker** runs independently:
   - Scans for failed trades every 60 seconds
   - Retries with bounded backoff
   - Updates trade status in PostgreSQL

5. **Shared Infrastructure** provides cross-cutting concerns:
   - `jwt_auth` — single source of truth for authentication
   - `database_service` — connection pool for chat history
   - `pii_middleware` — compliance-ready PII redaction
