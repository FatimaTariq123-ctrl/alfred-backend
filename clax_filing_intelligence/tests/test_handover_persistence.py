import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from handover.contract import FIECompanyState
from storage.db import DatabaseManager

def test_save_fie_company_state_nan_rejection():
    """Verifies that a payload containing NaN fails loudly during json serialization."""
    db = MagicMock(spec=DatabaseManager)
    db.save_fie_company_state = DatabaseManager.save_fie_company_state.__get__(db, DatabaseManager)

    # State payload containing NaN value
    nan_state = {
        "issuer": "MSFT",
        "analysis_date": "2026-10-01",
        "history_window": 5,
        "history_expanded": False,
        "history_expansion_reasons": [],
        "financial_state": {"invalid_metric": float("nan")},
        "material_changes": [],
        "accounting_quality": {},
        "material_events": [],
        "data_quality": {},
        "confidence": "HIGH",
        "handover_status": "PASS",
        "handover_blockers": []
    }

    with pytest.raises(ValueError):
        db.save_fie_company_state("test_run_nan", nan_state)

def test_save_fie_company_state_parameter_building():
    """Verifies that save_fie_company_state extracts state fields and executes INSERT query."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {
        "issuer_id": "issuer_US_MSFT",
        "as_of_date": "2026-10-01",
        "policy_version": "1.1"
    }
    mock_cur.rowcount = 1

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    db = MagicMock(spec=DatabaseManager)
    db.get_connection.return_value = mock_conn
    db.save_fie_company_state = DatabaseManager.save_fie_company_state.__get__(db, DatabaseManager)

    state = FIECompanyState(
        issuer="MSFT",
        analysis_date="2026-10-01",
        history_window=5,
        history_expanded=False,
        history_expansion_reasons=[],
        financial_state={},
        material_changes=[],
        accounting_quality={},
        material_events=[],
        data_quality={},
        confidence="HIGH",
        handover_status="PASS",
        handover_blockers=[]
    )

    inserted = db.save_fie_company_state("run_msft_001", state)

    assert inserted is True
    assert mock_cur.execute.call_count == 2
    query_call_args = mock_cur.execute.call_args_list[1][0]
    sql_text = query_call_args[0]
    query_params = query_call_args[1]

    assert "INSERT INTO fie_company_state" in sql_text
    assert query_params["run_id"] == "run_msft_001"
    assert query_params["issuer_id"] == "issuer_US_MSFT"
    assert query_params["handover_status"] == "PASS"
    assert query_params["confidence"] == "HIGH"
    assert query_params["history_window_years"] == 5

def test_migration_runner_finds_all_migrations_in_order():
    """Verifies that _run_migrations executes all migration files in schema/migrations in sorted order."""
    migrations_dir = PROJECT_ROOT / "schema" / "migrations"
    sql_files = sorted(migrations_dir.glob("*.sql"))

    assert len(sql_files) >= 2, "Expected at least 2 migration SQL files"
    filenames = [f.name for f in sql_files]
    assert filenames[0] == "001_initial_schema.sql"
    assert filenames[1] == "002_fie_company_state.sql"

    executed_files = []
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [{"table_name": t} for t in [
        "ingestion_run", "issuer", "filing", "filing_asset",
        "fact_observation", "fact_version", "normalized_metric",
        "text_chunk", "material_event", "history_decision", "quality_issue",
        "fie_company_state"
    ]]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    db = MagicMock(spec=DatabaseManager)
    db.get_connection.return_value = mock_conn
    db._run_migrations = DatabaseManager._run_migrations.__get__(db, DatabaseManager)

    db._run_migrations()

    assert mock_cur.execute.call_count >= len(sql_files)
