# Retry Reconciliation Worker

Background async worker that retries failed trade executions.

## What it does

Scans `clax_trade_ledger` every 60 seconds for trades with status `RECONCILING`. For each one:
1. Acquires a `FOR UPDATE SKIP LOCKED` row lock
2. Retries downstream execution with 1s → 2s → 4s bounded backoff (3 attempts max)
3. Marks trades as `SUCCESS`, `VETOED` (on 403/402), or `FAILED` (after exhausting retries)

## Status

**Standalone worker** — no HTTP endpoints. Runs as `python d5_reconciliation_worker.py`.

## Key files

- `d5_reconciliation_worker.py` — `worker_loop()` (60s scan) + `process_trade_by_id()` (bounded retry)

## Dependencies

Requires `sqlalchemy[asyncio]` and a `DATABASE_URL` environment variable.
