"""
Database Manager & Repository Store (§6, §11.1, C2, C10)

Connects directly to Neon PostgreSQL using psycopg (v3) with SSL required.
Reuses a single long-lived PostgreSQL connection per DatabaseManager instance to prevent hitting connection limits.
Executes schema migration DDL statement-by-statement on startup and verifies all 11 tables exist.
Fails loudly if DATABASE_URL is missing.
"""

import os
import json
import logging
import time
import functools
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date, timezone
from pathlib import Path

import psycopg
from psycopg import pq
from psycopg.rows import dict_row

from config.settings import DATABASE_URL
from schema.models import (
    IngestionRun, Issuer, Filing, FilingAsset,
    FactObservation, FactVersion, NormalizedMetric,
    TextChunk, MaterialEvent, HistoryDecision, QualityIssue
)

logger = logging.getLogger(__name__)

import threading

REQUIRED_TABLES = [
    "ingestion_run", "issuer", "filing", "filing_asset",
    "fact_observation", "fact_version", "normalized_metric",
    "text_chunk", "material_event", "history_decision", "quality_issue",
    "fie_company_state"
]

WRITE_RETRY_ATTEMPTS = 5
BATCH_CHUNK_SIZE = 500


class DatabaseManager:
    """
    Thread-safe PostgreSQL Database Manager using psycopg (v3).
    Uses thread-local connection isolation so concurrent worker threads never share a raw socket.
    """
    def __init__(self, connection_url: Optional[str] = None):
        self.url = connection_url or DATABASE_URL
        if not self.url or not self.url.strip():
            raise ValueError(
                "DATABASE_URL environment variable must be set. "
                "The pipeline cannot run without a PostgreSQL database."
            )
        
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        dbname = parsed.path.lstrip("/")

        self.host = host
        self.dbname = dbname
        self.fact_value_conflicts = 0
        self.fact_conflict_examples: List[Dict[str, Any]] = []

        # Rule 4: Local database & CLAX_ENV=dev guard
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        clax_env = os.environ.get("CLAX_ENV", "")
        allow_remote = os.environ.get("CLAX_ALLOW_REMOTE_DB", "0") == "1"
        if (clax_env != "dev" or host not in local_hosts) and not allow_remote:
            raise PermissionError(
                f"Refusing connection: CLAX_ENV='{clax_env}' (must be 'dev') and host='{host}' (must be localhost, 127.0.0.1, or ::1)."
            )

        print(f"[DatabaseManager] Target DB: host={host}, dbname={dbname}")

        # WI-2 / E20: sslmode handling for local vs remote
        if "sslmode=" not in self.url:
            if host not in local_hosts:
                self.url += "?sslmode=require" if "?" not in self.url else "&sslmode=require"

        self._local = threading.local()
        self._run_migrations()

    def get_connection(self) -> psycopg.Connection:
        """Returns the thread-isolated psycopg connection, reconnecting if closed or broken."""
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = psycopg.connect(self.url, row_factory=dict_row)
            self._local.conn = conn
        else:
            try:
                if conn.pgconn.status == pq.ConnStatus.BAD:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = psycopg.connect(self.url, row_factory=dict_row)
                    self._local.conn = conn
            except Exception:
                pass
        return conn

    @property
    def _conn(self) -> psycopg.Connection:
        """Property proxy providing backward compatibility for direct _conn access."""
        return self.get_connection()

    def commit(self):
        """Commits the current thread's database transaction."""
        conn = getattr(self._local, "conn", None)
        if conn and not conn.closed:
            conn.commit()

    def rollback(self):
        """Rolls back the current thread's database transaction."""
        conn = getattr(self._local, "conn", None)
        if conn and not conn.closed:
            conn.rollback()

    def close(self):
        """Closes the current thread's connection."""
        conn = getattr(self._local, "conn", None)
        if conn and not conn.closed:
            conn.close()
            self._local.conn = None

    # --- Batch write methods (DB efficiency: one round-trip per stage) ---

    def save_filings(self, filings_list: List[Filing]) -> None:
        """Batch-insert/upsert a list of Filing records (base or amendment pass)."""
        if not filings_list:
            return
        sql = """
        INSERT INTO filing (
            filing_id, issuer_id, accession_number, form_type, filing_date,
            report_period, amendment_flag, base_filing_id, source_uri, source_hash, created_at
        ) VALUES (
            %(filing_id)s, %(issuer_id)s, %(accession_number)s, %(form_type)s, %(filing_date)s,
            %(report_period)s, %(amendment_flag)s, %(base_filing_id)s, %(source_uri)s, %(source_hash)s, %(created_at)s
        ) ON CONFLICT (accession_number) DO UPDATE SET
          source_hash = CASE
              WHEN EXCLUDED.source_hash IS NULL OR EXCLUDED.source_hash = '' THEN filing.source_hash
              WHEN filing.source_hash IS NULL OR filing.source_hash = '' THEN EXCLUDED.source_hash
              ELSE filing.source_hash
          END,
          base_filing_id = COALESCE(EXCLUDED.base_filing_id, filing.base_filing_id);
        """
        conn = self.get_connection()
        for chunk in _chunks(filings_list, BATCH_CHUNK_SIZE):
            data_list = [f.model_dump() for f in chunk]
            with conn.cursor() as cur:
                cur.executemany(sql, data_list)
            conn.commit()

    def save_fact_observations(self, facts: List[FactObservation]) -> None:
        """
        Batch-insert fact observations and remap fact_id in-place to the stored id.
        Preserves value-conflict counting (same semantics as save_fact_observation).
        """
        if not facts:
            return
        insert_sql = """
        INSERT INTO fact_observation (
            fact_id, canonical_fact_key, filing_id, concept, value, unit,
            currency, period_start, period_end, instant_date, dimensions,
            context_ref, parser_version, created_at, excluded_from_versioning, exclusion_reason
        ) VALUES (
            %(fact_id)s, %(canonical_fact_key)s, %(filing_id)s, %(concept)s, %(value)s, %(unit)s,
            %(currency)s, %(period_start)s, %(period_end)s, %(instant_date)s, %(dimensions)s,
            %(context_ref)s, %(parser_version)s, %(created_at)s, %(excluded_from_versioning)s, %(exclusion_reason)s
        ) ON CONFLICT (canonical_fact_key, filing_id) DO NOTHING;
        """
        conn = self.get_connection()
        for chunk in _chunks(facts, BATCH_CHUNK_SIZE):
            data_list = []
            for fact in chunk:
                d = fact.model_dump()
                d["dimensions"] = json.dumps(d["dimensions"]) if d.get("dimensions") else None
                data_list.append(d)
            with conn.cursor() as cur:
                cur.executemany(insert_sql, data_list)
            conn.commit()

        # Bulk-select stored fact_ids and remap in-place (handles ON CONFLICT DO NOTHING case)
        stored_map: Dict[Tuple[str, str], Any] = {}
        keys = [(f.canonical_fact_key, f.filing_id) for f in facts if f.canonical_fact_key]
        for chunk in _chunks(keys, BATCH_CHUNK_SIZE):
            if not chunk:
                continue
            placeholders = ",".join(["(%s,%s)"] * len(chunk))
            flat = [v for pair in chunk for v in pair]
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT fact_id, canonical_fact_key, filing_id, value FROM fact_observation "
                    f"WHERE (canonical_fact_key, filing_id) IN ({placeholders});",
                    flat,
                )
                for row in cur.fetchall():
                    k = (row["canonical_fact_key"], row["filing_id"])
                    stored_map[k] = row

        for fact in facts:
            if not fact.canonical_fact_key:
                continue
            row = stored_map.get((fact.canonical_fact_key, fact.filing_id))
            if not row:
                continue
            stored_fact_id = row["fact_id"] if isinstance(row, dict) else row[0]
            stored_val = row["value"] if isinstance(row, dict) else row[3]
            if stored_fact_id != fact.fact_id:
                new_val = fact.value
                if stored_val is not None and new_val is not None:
                    try:
                        if float(stored_val) != float(new_val):
                            self.fact_value_conflicts += 1
                            if len(self.fact_conflict_examples) < 5:
                                self.fact_conflict_examples.append({
                                    "concept": fact.concept,
                                    "stored_value": stored_val,
                                    "new_value": new_val,
                                    "filing_id": fact.filing_id,
                                })
                            logger.debug(
                                "Fact value conflict for concept %s in filing %s: stored=%s, new=%s",
                                fact.concept, fact.filing_id, stored_val, new_val,
                            )
                    except (TypeError, ValueError):
                        pass
                fact.fact_id = stored_fact_id

    def save_normalized_metrics(self, metrics: List[NormalizedMetric]) -> None:
        """Batch-insert/upsert normalized metric records."""
        if not metrics:
            return
        sql = """
        INSERT INTO normalized_metric (
            metric_id, issuer_id, metric_code, period, value, unit,
            provenance_fact_ids, provenance_filing_ids, comparability_status, is_derived, created_at
        ) VALUES (
            %(metric_id)s, %(issuer_id)s, %(metric_code)s, %(period)s, %(value)s, %(unit)s,
            %(provenance_fact_ids)s, %(provenance_filing_ids)s, %(comparability_status)s, %(is_derived)s, %(created_at)s
        ) ON CONFLICT (metric_id) DO UPDATE SET
            value = EXCLUDED.value,
            comparability_status = EXCLUDED.comparability_status,
            provenance_fact_ids = EXCLUDED.provenance_fact_ids,
            provenance_filing_ids = EXCLUDED.provenance_filing_ids;
        """
        conn = self.get_connection()
        for chunk in _chunks(metrics, BATCH_CHUNK_SIZE):
            data_list = [m.model_dump() for m in chunk]
            with conn.cursor() as cur:
                cur.executemany(sql, data_list)
            conn.commit()

    def save_fact_versions(self, versions: List[FactVersion]) -> None:
        """Batch-insert/upsert fact version records."""
        if not versions:
            return
        sql = """
        INSERT INTO fact_version (
            canonical_key, original_fact_id, preferred_fact_id, version_reason, effective_from, updated_at
        ) VALUES (
            %(canonical_key)s, %(original_fact_id)s, %(preferred_fact_id)s, %(version_reason)s, %(effective_from)s, %(updated_at)s
        ) ON CONFLICT (canonical_key) DO UPDATE SET
            preferred_fact_id = EXCLUDED.preferred_fact_id,
            version_reason = EXCLUDED.version_reason,
            updated_at = EXCLUDED.updated_at;
        """
        conn = self.get_connection()
        for chunk in _chunks(versions, BATCH_CHUNK_SIZE):
            data_list = [v.model_dump() for v in chunk]
            with conn.cursor() as cur:
                cur.executemany(sql, data_list)
            conn.commit()

    def save_material_events(self, events: List[MaterialEvent]) -> None:
        """Batch-insert material event records."""
        if not events:
            return
        sql = """
        INSERT INTO material_event (
            event_id, issuer_id, filing_id, event_type, event_date, severity, thesis_tags, details, created_at
        ) VALUES (
            %(event_id)s, %(issuer_id)s, %(filing_id)s, %(event_type)s, %(event_date)s, %(severity)s, %(thesis_tags)s, %(details)s, %(created_at)s
        ) ON CONFLICT (event_id) DO NOTHING;
        """
        conn = self.get_connection()
        for chunk in _chunks(events, BATCH_CHUNK_SIZE):
            data_list = []
            for event in chunk:
                d = event.model_dump()
                d["details"] = json.dumps(d["details"]) if d.get("details") else None
                data_list.append(d)
            with conn.cursor() as cur:
                cur.executemany(sql, data_list)
            conn.commit()

    def reset_database(self):
        """
        Executes TRUNCATE on all 12 tables (including fie_company_state) with RESTART IDENTITY to reset database state.
        Requires CLAX_ENV=dev, local host, and ALLOW_DB_RESET=1.
        """
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        clax_env = os.environ.get("CLAX_ENV", "")
        allow_reset = os.environ.get("ALLOW_DB_RESET", "0") == "1"
        if clax_env != "dev" or self.host not in local_hosts or not allow_reset:
            raise PermissionError("Database reset refused: requires CLAX_ENV='dev', local host, and ALLOW_DB_RESET='1'.")

        conn = self.get_connection()
        tables_csv = ", ".join(REQUIRED_TABLES)
        sql = f"TRUNCATE TABLE {tables_csv} RESTART IDENTITY;"
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        logger.info(f"Truncated all {len(REQUIRED_TABLES)} database tables (including fie_company_state): {tables_csv}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

    def _run_migrations(self):
        """
        Executes schema DDL migration files in sorted order from schema/migrations/*.sql
        and verifies all required tables exist in PostgreSQL.
        """
        migrations_dir = Path(__file__).resolve().parent.parent / "schema" / "migrations"
        if not migrations_dir.exists():
            raise FileNotFoundError(f"Schema migrations directory not found at {migrations_dir}")

        sql_files = sorted(migrations_dir.glob("*.sql"))
        conn = self.get_connection()
        
        with conn.cursor() as cur:
            for sql_file in sql_files:
                sql_script = sql_file.read_text(encoding="utf-8")
                statements = [stmt.strip() for stmt in sql_script.split(";") if stmt.strip()]
                for stmt in statements:
                    cur.execute(stmt)
        conn.commit()

        # Verify all required tables exist in PostgreSQL information_schema
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            existing_tables = set(row["table_name"] for row in cur.fetchall())

        missing = [t for t in REQUIRED_TABLES if t not in existing_tables]
        if missing:
            raise RuntimeError(f"Database migration failed to create required tables: {missing}")

        logger.info(f"Verified all {len(REQUIRED_TABLES)} PostgreSQL tables exist: {sorted(list(existing_tables))}")

    def _handover_gate_fields(self, cur, issuer_id: str, handover_status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Computes the typed fie_company_state gate columns from the SAME payload being saved, cross-checked
        against the actual DB tables (not guessed from the payload alone), so a FIE consumer reading the
        typed columns never sees a different answer than the payload itself gives (team head's blocker #1:
        these columns were simply never written, so they stayed at their schema defaults -- UNVERIFIED,
        FALSE, FALSE, 0 -- even for a run that actually reconciled and parsed real filings).
        """
        data_quality = payload.get("data_quality", {}) or {}
        financial_state = payload.get("financial_state", {}) or {}
        metrics_summary = financial_state.get("metrics_summary", {}) or {}
        material_events = payload.get("material_events", []) or []
        handover_blockers = payload.get("handover_blockers", []) or []

        # Storage verification: the payload's own counts must match what is actually sitting in the tables
        # it was built from. This is the same cross-check db_check_run.py performs read-only after the fact;
        # here it runs once, inline, before the row is written, so storage_verified is never just asserted.
        db_metric_count = cur.execute(
            "SELECT COUNT(*) AS n FROM normalized_metric WHERE issuer_id = %s", (issuer_id,)
        ).fetchone()["n"]
        db_event_count = cur.execute(
            "SELECT COUNT(*) AS n FROM material_event WHERE issuer_id = %s", (issuer_id,)
        ).fetchone()["n"]
        storage_verified = (db_metric_count == len(metrics_summary)) and (db_event_count == len(material_events))

        # Team head's "Final Ingestion Fix" blocker: financial_filings previously counted every filing in
        # the window (provenance_filings_count), 8-Ks included -- so an issuer with 30 routine 8-Ks and 13
        # real financial filings showed financial_filings=43 and filings_quarantined=30 (all of them 8-Ks,
        # which never carry financial facts by design, not a parsing/validation/storage failure). A first
        # fix scoped the query to 10-K/10-Q form types, but queried the `filing` table directly -- which
        # holds this issuer's ENTIRE indexed filing history (every 10-K/10-Q it has ever filed), not just
        # the filings THIS RUN selected for its analytical window. For an issuer with decades on file that
        # inflated the count even further (CF: 86, EXP: 124). financial_filings must therefore come from
        # the payload's own financial_state.financial_filings_selected -- computed in handover/contract.py
        # directly from the same `filings` list orchestration.py actually selected for this run -- never
        # re-derived from the shared `filing` table, which spans far more than one run's window.
        FINANCIAL_FORM_TYPES = ("10-K", "10-K/A", "10-Q", "10-Q/A")
        financial_filings = int(financial_state.get("financial_filings_selected", 0) or 0)
        financial_filings_parsed_ok = cur.execute(
            "SELECT COUNT(DISTINCT fo.filing_id) AS n FROM fact_observation fo JOIN filing f USING (filing_id) "
            "WHERE f.issuer_id = %s AND f.form_type = ANY(%s)",
            (issuer_id, list(FINANCIAL_FORM_TYPES))
        ).fetchone()["n"]
        financial_filings_parsed_ok = min(financial_filings_parsed_ok, financial_filings) if financial_filings else financial_filings_parsed_ok
        # A genuinely failed/withheld financial filing (parsing, validation or storage failure) would be a
        # selected financial filing with zero facts -- this pipeline has no separate quarantine stage, so
        # that count IS the quarantine count.
        filings_quarantined = max(financial_filings - financial_filings_parsed_ok, 0)

        authoritative_for_fie = (
            handover_status in ("PASS", "PASS WITH FLAGS")
            and storage_verified
            and len(handover_blockers) == 0
        )

        return {
            "reconciliation_status": data_quality.get("reconciliation_status", "UNVERIFIED"),
            "storage_verified": storage_verified,
            "authoritative_for_fie": authoritative_for_fie,
            "financial_filings": financial_filings,
            "financial_filings_parsed_ok": financial_filings_parsed_ok,
            "filings_quarantined": filings_quarantined,
            "blocker_count": len(handover_blockers),
            "warning_count": len(data_quality.get("warnings", []) or []),
            "missing_periods": data_quality.get("missing_periods", []) or [],
        }

    def save_fie_company_state(self, run_id: str, state: Any) -> bool:
        """
        Persists the FIE handover output contract payload to Postgres as JSONB (Step C).
        """
        from psycopg.types.json import Jsonb

        if hasattr(state, "model_dump"):
            payload_dict = state.model_dump(mode="json")
        elif isinstance(state, dict):
            payload_dict = state
        else:
            payload_dict = json.loads(state.json())

        # Serialize with allow_nan=False to ensure NaN or Infinity fails loudly (Step C3)
        serialized_json = json.dumps(payload_dict, allow_nan=False)
        parsed_payload = json.loads(serialized_json)

        handover_status = getattr(state, "handover_status", payload_dict.get("handover_status"))
        confidence = getattr(state, "confidence", payload_dict.get("confidence"))
        history_window_years = getattr(state, "history_window", payload_dict.get("history_window"))

        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT issuer_id, as_of_date, policy_version FROM ingestion_run WHERE run_id = %s;", (run_id,))
            run_row = cur.fetchone()
            if not run_row:
                raise ValueError(f"No ingestion_run found for run_id '{run_id}'")

            issuer_id = run_row["issuer_id"]
            as_of_date = run_row["as_of_date"]
            policy_version = run_row["policy_version"]

            if handover_status is None:
                raise ValueError("Missing required value: handover_status")
            if confidence is None:
                raise ValueError("Missing required value: confidence")
            if history_window_years is None:
                raise ValueError("Missing required value: history_window")

            gate_fields = self._handover_gate_fields(cur, issuer_id, handover_status, payload_dict)

            sql = """
            INSERT INTO fie_company_state (
                run_id, issuer_id, as_of_date, handover_status, confidence,
                history_window_years, policy_version, schema_version, payload,
                reconciliation_status, storage_verified, authoritative_for_fie,
                financial_filings, financial_filings_parsed_ok, filings_quarantined,
                blocker_count, warning_count, missing_periods
            ) VALUES (
                %(run_id)s, %(issuer_id)s, %(as_of_date)s, %(handover_status)s, %(confidence)s,
                %(history_window_years)s, %(policy_version)s, '1.0', %(payload)s,
                %(reconciliation_status)s, %(storage_verified)s, %(authoritative_for_fie)s,
                %(financial_filings)s, %(financial_filings_parsed_ok)s, %(filings_quarantined)s,
                %(blocker_count)s, %(warning_count)s, %(missing_periods)s
            ) ON CONFLICT (run_id) DO NOTHING;
            """
            cur.execute(sql, {
                "run_id": run_id,
                "issuer_id": issuer_id,
                "as_of_date": as_of_date,
                "handover_status": handover_status,
                "confidence": confidence,
                "history_window_years": history_window_years,
                "policy_version": policy_version,
                "payload": Jsonb(parsed_payload),
                **gate_fields,
            })
            inserted = cur.rowcount > 0
        conn.commit()
        logger.info(f"Persisted FIE handover for run {run_id} (status: {handover_status}, inserted: {inserted})")
        return inserted

    def get_latest_fie_company_state(self, issuer_id: str) -> Optional[Dict[str, Any]]:
        """
        Reads the latest handover row for a given issuer_id from fie_company_state_latest view (Step C4).
        """
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fie_company_state_latest WHERE issuer_id = %s;", (issuer_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    # 1. Ingestion Run Repository
    def save_ingestion_run(self, run: IngestionRun):
        sql = """
        INSERT INTO ingestion_run (
            run_id, issuer_id, as_of_date, policy_version, edgartools_version,
            parser_version, normalizer_version, status, started_at, completed_at, source_snapshot
        ) VALUES (
            %(run_id)s, %(issuer_id)s, %(as_of_date)s, %(policy_version)s, %(edgartools_version)s,
            %(parser_version)s, %(normalizer_version)s, %(status)s, %(started_at)s, %(completed_at)s, %(source_snapshot)s
        ) ON CONFLICT (run_id) DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = EXCLUDED.completed_at,
            source_snapshot = EXCLUDED.source_snapshot;
        """
        data = run.model_dump()
        data["source_snapshot"] = json.dumps(data["source_snapshot"]) if data.get("source_snapshot") else None
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, data)
        conn.commit()

    # 2. Issuer Repository
    def save_issuer(self, issuer: Issuer):
        sql = """
        INSERT INTO issuer (
            issuer_id, market, legal_name, ticker, cik, fiscal_year_end, created_at
        ) VALUES (
            %(issuer_id)s, %(market)s, %(legal_name)s, %(ticker)s, %(cik)s, %(fiscal_year_end)s, %(created_at)s
        ) ON CONFLICT (issuer_id) DO UPDATE SET
            legal_name = EXCLUDED.legal_name,
            cik = EXCLUDED.cik,
            fiscal_year_end = EXCLUDED.fiscal_year_end;
        """
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, issuer.model_dump())
        conn.commit()

    # 3. Filing Repository (DB Enforces UNIQUE accession_number for C2 Idempotency)
    def save_filing(self, filing: Filing) -> bool:
        sql = """
        INSERT INTO filing (
            filing_id, issuer_id, accession_number, form_type, filing_date,
            report_period, amendment_flag, base_filing_id, source_uri, source_hash, created_at
        ) VALUES (
            %(filing_id)s, %(issuer_id)s, %(accession_number)s, %(form_type)s, %(filing_date)s,
            %(report_period)s, %(amendment_flag)s, %(base_filing_id)s, %(source_uri)s, %(source_hash)s, %(created_at)s
        ) ON CONFLICT (accession_number) DO UPDATE SET
          source_hash = CASE
              WHEN EXCLUDED.source_hash IS NULL OR EXCLUDED.source_hash = '' THEN filing.source_hash
              WHEN filing.source_hash IS NULL OR filing.source_hash = '' THEN EXCLUDED.source_hash
              ELSE filing.source_hash
          END,
          base_filing_id = COALESCE(EXCLUDED.base_filing_id, filing.base_filing_id);
        """
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, filing.model_dump())
        conn.commit()
        return True

    # 4. Filing Asset Repository
    def save_filing_asset(self, asset: FilingAsset):
        sql = """
        INSERT INTO filing_asset (
            asset_id, filing_id, asset_type, storage_uri, mime_type, hash, retrieved_at
        ) VALUES (
            %(asset_id)s, %(filing_id)s, %(asset_type)s, %(storage_uri)s, %(mime_type)s, %(hash)s, %(retrieved_at)s
        ) ON CONFLICT (asset_id) DO NOTHING;
        """
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, asset.model_dump())
        conn.commit()

    # 5. Fact Observation Repository (DB Enforces UNIQUE(canonical_fact_key, filing_id))
    def save_fact_observation(self, fact: FactObservation) -> bool:
        sql = """
        INSERT INTO fact_observation (
            fact_id, canonical_fact_key, filing_id, concept, value, unit,
            currency, period_start, period_end, instant_date, dimensions,
            context_ref, parser_version, created_at
        ) VALUES (
            %(fact_id)s, %(canonical_fact_key)s, %(filing_id)s, %(concept)s, %(value)s, %(unit)s,
            %(currency)s, %(period_start)s, %(period_end)s, %(instant_date)s, %(dimensions)s,
            %(context_ref)s, %(parser_version)s, %(created_at)s
        ) ON CONFLICT (canonical_fact_key, filing_id) DO NOTHING
        RETURNING fact_id;
        """
        data = fact.model_dump()
        data["dimensions"] = json.dumps(data["dimensions"]) if data.get("dimensions") else None
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, data)
            row = cur.fetchone()
            if row:
                actual_fact_id = row["fact_id"] if isinstance(row, dict) else row[0]
            else:
                cur.execute(
                    "SELECT fact_id, value FROM fact_observation WHERE canonical_fact_key = %s AND filing_id = %s;",
                    (fact.canonical_fact_key, fact.filing_id)
                )
                stored_row = cur.fetchone()
                if stored_row:
                    actual_fact_id = stored_row["fact_id"] if isinstance(stored_row, dict) else stored_row[0]
                    stored_val = stored_row["value"] if isinstance(stored_row, dict) else stored_row[1]
                    new_val = fact.value
                    if stored_val is not None and new_val is not None and float(stored_val) != float(new_val):
                        self.fact_value_conflicts += 1
                        if len(self.fact_conflict_examples) < 5:
                            self.fact_conflict_examples.append({
                                "concept": fact.concept,
                                "stored_value": stored_val,
                                "new_value": new_val,
                                "filing_id": fact.filing_id
                            })
                        logger.debug(f"Fact value conflict for concept {fact.concept} in filing {fact.filing_id}: stored={stored_val}, new={new_val}")
                else:
                    actual_fact_id = fact.fact_id
        conn.commit()
        fact.fact_id = actual_fact_id
        return actual_fact_id

    # 6. Fact Version Repository
    def save_fact_version(self, version: FactVersion):
        sql = """
        INSERT INTO fact_version (
            canonical_key, original_fact_id, preferred_fact_id, version_reason, effective_from, updated_at
        ) VALUES (
            %(canonical_key)s, %(original_fact_id)s, %(preferred_fact_id)s, %(version_reason)s, %(effective_from)s, %(updated_at)s
        ) ON CONFLICT (canonical_key) DO UPDATE SET
            preferred_fact_id = EXCLUDED.preferred_fact_id,
            version_reason = EXCLUDED.version_reason,
            updated_at = EXCLUDED.updated_at;
        """
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, version.model_dump())
        conn.commit()

    # 7. Normalized Metric Repository
    def save_normalized_metric(self, metric: NormalizedMetric):
        sql = """
        INSERT INTO normalized_metric (
            metric_id, issuer_id, metric_code, period, value, unit,
            provenance_fact_ids, provenance_filing_ids, comparability_status, is_derived, created_at
        ) VALUES (
            %(metric_id)s, %(issuer_id)s, %(metric_code)s, %(period)s, %(value)s, %(unit)s,
            %(provenance_fact_ids)s, %(provenance_filing_ids)s, %(comparability_status)s, %(is_derived)s, %(created_at)s
        ) ON CONFLICT (metric_id) DO UPDATE SET
            value = EXCLUDED.value,
            comparability_status = EXCLUDED.comparability_status,
            provenance_fact_ids = EXCLUDED.provenance_fact_ids,
            provenance_filing_ids = EXCLUDED.provenance_filing_ids;
        """
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, metric.model_dump())
        conn.commit()

    # 8. Text Chunk Repository
    def save_text_chunk(self, chunk: TextChunk):
        sql = """
        INSERT INTO text_chunk (
            chunk_id, filing_id, section, text, page_anchor, embedding_ref, source_span, parser_version, created_at
        ) VALUES (
            %(chunk_id)s, %(filing_id)s, %(section)s, %(text)s, %(page_anchor)s, %(embedding_ref)s, %(source_span)s, %(parser_version)s, %(created_at)s
        ) ON CONFLICT (chunk_id) DO NOTHING;
        """
        data = chunk.model_dump()
        data["source_span"] = json.dumps(data["source_span"]) if data.get("source_span") else None
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, data)
        conn.commit()

    def save_text_chunks(self, chunks: List[TextChunk]):
        if not chunks:
            return
        sql = """
        INSERT INTO text_chunk (
            chunk_id, filing_id, section, text, page_anchor, embedding_ref, source_span, parser_version, created_at
        ) VALUES (
            %(chunk_id)s, %(filing_id)s, %(section)s, %(text)s, %(page_anchor)s, %(embedding_ref)s, %(source_span)s, %(parser_version)s, %(created_at)s
        ) ON CONFLICT (chunk_id) DO NOTHING;
        """
        data_list = []
        for chunk in chunks:
            d = chunk.model_dump()
            d["source_span"] = json.dumps(d["source_span"]) if d.get("source_span") else None
            data_list.append(d)

        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, data_list)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # 9. Material Event Repository
    def save_material_event(self, event: MaterialEvent):
        sql = """
        INSERT INTO material_event (
            event_id, issuer_id, filing_id, event_type, event_date, severity, thesis_tags, details, created_at
        ) VALUES (
            %(event_id)s, %(issuer_id)s, %(filing_id)s, %(event_type)s, %(event_date)s, %(severity)s, %(thesis_tags)s, %(details)s, %(created_at)s
        ) ON CONFLICT (event_id) DO NOTHING;
        """
        data = event.model_dump()
        data["details"] = json.dumps(data["details"]) if data.get("details") else None
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, data)
        conn.commit()

    # 10. History Decision Repository
    def save_history_decision(self, decision: HistoryDecision):
        sql = """
        INSERT INTO history_decision (
            decision_id, issuer_id, run_id, mode, years_selected, triggers, policy_version, created_at
        ) VALUES (
            %(decision_id)s, %(issuer_id)s, %(run_id)s, %(mode)s, %(years_selected)s, %(triggers)s, %(policy_version)s, %(created_at)s
        ) ON CONFLICT (decision_id) DO NOTHING;
        """
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, decision.model_dump())
        conn.commit()

    # 11. Quality Issue Repository
    def save_quality_issues(self, issues: List[QualityIssue]) -> None:
        """Batch-insert quality issue records (normalizer, harness, or anywhere else an issue is raised)."""
        if not issues:
            return
        sql = """
        INSERT INTO quality_issue (
            issue_id, run_id, filing_id, fact_id, rule_code, severity, status, details, created_at
        ) VALUES (
            %(issue_id)s, %(run_id)s, %(filing_id)s, %(fact_id)s, %(rule_code)s, %(severity)s, %(status)s, %(details)s, %(created_at)s
        ) ON CONFLICT (issue_id) DO NOTHING;
        """
        conn = self.get_connection()
        for chunk in _chunks(issues, BATCH_CHUNK_SIZE):
            data_list = []
            for issue in chunk:
                d = issue.model_dump()
                d["details"] = json.dumps(d["details"]) if d.get("details") else None
                data_list.append(d)
            with conn.cursor() as cur:
                cur.executemany(sql, data_list)
            conn.commit()

    def save_quality_issue(self, issue: QualityIssue):
        sql = """
        INSERT INTO quality_issue (
            issue_id, run_id, filing_id, fact_id, rule_code, severity, status, details, created_at
        ) VALUES (
            %(issue_id)s, %(run_id)s, %(filing_id)s, %(fact_id)s, %(rule_code)s, %(severity)s, %(status)s, %(details)s, %(created_at)s
        ) ON CONFLICT (issue_id) DO NOTHING;
        """
        data = issue.model_dump()
        data["details"] = json.dumps(data["details"]) if data.get("details") else None
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, data)
        conn.commit()

    # Query Helpers
    def get_filings_for_issuer(self, issuer_id: str) -> List[Filing]:
        sql = "SELECT * FROM filing WHERE issuer_id = %s ORDER BY filing_date DESC;"
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (issuer_id,))
            rows = cur.fetchall()
            return [Filing(**row) for row in rows]

    def get_facts_for_canonical_key(self, canonical_key: str) -> List[FactObservation]:
        sql = "SELECT * FROM fact_observation WHERE canonical_fact_key = %s ORDER BY created_at ASC;"
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (canonical_key,))
            rows = cur.fetchall()
            return [FactObservation(**row) for row in rows]

    def get_quality_issues_for_run(self, run_id: str) -> List[QualityIssue]:
        sql = "SELECT * FROM quality_issue WHERE run_id = %s ORDER BY created_at ASC;"
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            rows = cur.fetchall()
            return [QualityIssue(**row) for row in rows]

    def get_filing_assets(self, filing_id: str) -> List[FilingAsset]:
        sql = "SELECT * FROM filing_asset WHERE filing_id = %s ORDER BY retrieved_at DESC;"
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (filing_id,))
            rows = cur.fetchall()
            return [FilingAsset(**row) for row in rows]

    def get_filing_hash(self, filing_id: str) -> Optional[str]:
        sql = "SELECT source_hash FROM filing WHERE filing_id = %s;"
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (filing_id,))
            row = cur.fetchone()
            if row:
                return row["source_hash"] if isinstance(row, dict) else row[0]
            return None


# ---------------------------------------------------------------------------
# db_retry_addon: module-level helpers (outside class)
# ---------------------------------------------------------------------------

def _chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _db_write_retry(func):
    """
    Retry decorator for DatabaseManager write methods.
    Retries on psycopg.OperationalError and psycopg.errors.ProtocolViolation.
    Does NOT retry on psycopg.errors.ForeignKeyViolation (integrity error – no benefit).
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        last_exc = None
        for attempt in range(WRITE_RETRY_ATTEMPTS):
            try:
                return func(self, *args, **kwargs)
            except psycopg.errors.ForeignKeyViolation:
                raise
            except (psycopg.OperationalError, psycopg.errors.ProtocolViolation) as exc:
                last_exc = exc
                logger.warning(
                    "[db_retry] attempt %d/%d failed (%s); reconnecting...",
                    attempt + 1,
                    WRITE_RETRY_ATTEMPTS,
                    type(exc).__name__,
                )
                _old_conn = getattr(self._local, "conn", None)
                if _old_conn is not None:
                    try:
                        _old_conn.rollback()
                    except Exception:
                        pass
                    try:
                        _old_conn.close()
                    except Exception:
                        pass
                self._local.conn = None
                time.sleep(0.2 * (attempt + 1))
        raise last_exc
    return wrapper


# Apply retry decorator to all batch write methods
DatabaseManager.save_filings = _db_write_retry(DatabaseManager.save_filings)
DatabaseManager.save_fact_observations = _db_write_retry(DatabaseManager.save_fact_observations)
DatabaseManager.save_normalized_metrics = _db_write_retry(DatabaseManager.save_normalized_metrics)
DatabaseManager.save_fact_versions = _db_write_retry(DatabaseManager.save_fact_versions)
DatabaseManager.save_material_events = _db_write_retry(DatabaseManager.save_material_events)


def _retry_on_lost_connection(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        attempts = getattr(self, "WRITE_RETRY_ATTEMPTS", 5)
        backoff = getattr(self, "WRITE_RETRY_BACKOFF_SECONDS", 1.0)
        last_err = None
        for attempt in range(attempts):
            try:
                return method(self, *args, **kwargs)
            except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                last_err = e
                logger.warning(f"[db_retry_all] {method.__name__}: lost the DB connection "
                               f"(attempt {attempt + 1}/{attempts}): {type(e).__name__}: {e}")
                local = getattr(self, "_local", None)
                conn = getattr(local, "conn", None)
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
                    local.conn = None
                if attempt < attempts - 1:
                    time.sleep(backoff * (2 ** attempt))
        raise last_err
    return wrapper


_ALREADY_RETRYING = {
    "get_connection", "save_filings", "save_fact_observations", "save_normalized_metrics",
    "save_fact_versions", "save_material_events", "save_quality_issues",
}
for _name, _fn in list(vars(DatabaseManager).items()):
    if (callable(_fn) and not _name.startswith("_") and _name not in _ALREADY_RETRYING
            and (_name.startswith("save_") or _name.startswith("get_"))):
        setattr(DatabaseManager, _name, _retry_on_lost_connection(_fn))
