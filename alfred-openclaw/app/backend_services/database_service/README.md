# Database Service

PostgreSQL connection pool utility using `psycopg2`.

## What it does

Creates and manages a `SimpleConnectionPool` (1–30 connections) to the Neon PostgreSQL database. Includes a `pre_warm_pool()` function for startup optimization.

## Status

**Partially active** — imported by orphaned route files (`compliance_routes.py`, `trade_execution_routes.py`) and via lazy import in `chat.py` for `/chat/history`.

## Key files

- `database_pool.py` — `db_pool` instance and `pre_warm_pool()` function

## Dependencies

Requires `psycopg2` and `psycopg2-binary` (not currently installed in the dev venv).
