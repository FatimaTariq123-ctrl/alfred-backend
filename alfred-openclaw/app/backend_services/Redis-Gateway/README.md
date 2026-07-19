# Redis Gateway

Standalone FastAPI microservice for idempotent order processing and artifact generation.

## What it does

- **Order verification** — creates temporary Redis-locked verification tokens
- **Order commit** — processes trades with Redis idempotency locks, persists to PostgreSQL
- **Artifact generation** — streams reports directly to S3 via Boto3 (stateless, no local temp files)

## Status

**Standalone deployable** — has its own `Dockerfile`, `docker-compose.yml`, `requirements.txt`. Runs as a separate container on port 8000 with its own Redis instance.

## Key files

- `app/main.py` — FastAPI app entry point
- `app/api/routes/orders.py` — `/verify` and `/commit` endpoints
- `app/api/routes/artifacts.py` — `/generate` endpoint
- `app/services/idempotency.py` — `IdempotencyEngine` (Redis atomic locks)
- `app/services/cloud_storage.py` — S3 streaming via Boto3
- `app/schemas/payload.py` — `CLAXAgentOutputContract`, `TradeVerificationResponse`

## How to run

```bash
docker-compose up
```

## Not imported by the main app

This service runs independently. It does not share code with `alfred-openclaw/main.py`.
