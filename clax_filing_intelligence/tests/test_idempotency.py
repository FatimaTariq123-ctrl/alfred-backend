import os
import hashlib
import time
from pathlib import Path
from datetime import date, datetime, timezone
from unittest.mock import MagicMock
import pytest

from common.ids import stable_id
from storage.object_store import ObjectStore
from storage.db import DatabaseManager, REQUIRED_TABLES
from schema.models import Filing, FilingAsset, FactObservation, Issuer, TextChunk, NormalizedMetric
from pipeline.retriever import FilingRetriever
from pipeline.parser import FilingParser
from pipeline.events import MaterialEventEmitter
from pipeline.normalizer import Normalizer


def test_stable_id():
    id1 = stable_id("test", "part1", "part2")
    id2 = stable_id("test", "part1", "part2")
    assert id1 == id2
    
    id3 = stable_id("test", "part1", "different")
    assert id1 != id3

    # Part containing | cannot collide with split pair
    id_pipe = stable_id("test", "a|b", "c")
    id_split = stable_id("test", "a", "b", "c")
    assert id_pipe != id_split


def test_object_store_never_overwrites(tmp_path):
    store = ObjectStore(base_path=tmp_path)
    data1 = b"original raw content"
    uri1, hash1 = store.store_asset("issuer1", "filing1", "doc.htm", data1)
    
    file_path1 = Path(uri1.replace("file://", ""))
    assert file_path1.exists()
    assert file_path1.read_bytes() == data1
    mtime1 = file_path1.stat().st_mtime

    time.sleep(0.01)
    # Same bytes again
    uri2, hash2 = store.store_asset("issuer1", "filing1", "doc.htm", data1)
    assert uri1 == uri2
    assert hash1 == hash2
    assert file_path1.stat().st_mtime == mtime1

    # Different bytes -> sibling path with hash12 suffix
    data2 = b"modified raw content"
    hash2_calc = hashlib.sha256(data2).hexdigest()
    uri3, hash3 = store.store_asset("issuer1", "filing1", "doc.htm", data2)

    assert uri3 != uri1
    assert hash2_calc[:12] in uri3
    assert file_path1.read_bytes() == data1  # Original untouched
    file_path3 = Path(uri3.replace("file://", ""))
    assert file_path3.read_bytes() == data2


def test_reset_database_guards_and_sql(monkeypatch):
    executed_sql = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed_sql.append(sql)
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            pass

    db = DatabaseManager.__new__(DatabaseManager)
    db.host = "localhost"
    db.get_connection = lambda: FakeConn()

    # 1. PermissionError without ALLOW_DB_RESET
    monkeypatch.setenv("CLAX_ENV", "dev")
    monkeypatch.delenv("ALLOW_DB_RESET", raising=False)
    with pytest.raises(PermissionError):
        db.reset_database()

    # 2. PermissionError when CLAX_ENV != dev
    monkeypatch.setenv("CLAX_ENV", "prod")
    monkeypatch.setenv("ALLOW_DB_RESET", "1")
    with pytest.raises(PermissionError):
        db.reset_database()

    # 3. PermissionError when host non-local
    db.host = "remotehost.internal"
    monkeypatch.setenv("CLAX_ENV", "dev")
    monkeypatch.setenv("ALLOW_DB_RESET", "1")
    with pytest.raises(PermissionError):
        db.reset_database()

    # 4. Valid reset
    db.host = "localhost"
    executed_sql.clear()
    db.reset_database()
    assert len(executed_sql) == 1
    sql = executed_sql[0]
    for table in REQUIRED_TABLES:
        assert table in sql
    assert "fie_company_state" in sql
    assert "RESTART IDENTITY" in sql
    assert "CASCADE" not in sql


def test_db_save_filing_and_fact_observation_sql():
    executed_queries = []

    class FakeCursor:
        def __init__(self):
            self.fetchone_result = None

        def execute(self, sql, params=None):
            executed_queries.append((sql, params))

        def fetchone(self):
            return self.fetchone_result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    class FakeConn:
        def __init__(self, cursor_obj):
            self.cur = cursor_obj
        def cursor(self):
            return self.cur
        def commit(self):
            pass

    cursor_obj = FakeCursor()
    fake_conn = FakeConn(cursor_obj)

    db = DatabaseManager.__new__(DatabaseManager)
    db.fact_value_conflicts = 0
    db.fact_conflict_examples = []
    db.get_connection = lambda: fake_conn

    filing = Filing(
        filing_id="filing_1",
        issuer_id="issuer_1",
        accession_number="0001-23-001",
        form_type="10-K",
        filing_date=date(2023, 10, 1),
        report_period=date(2023, 9, 30),
        source_uri="http://example.com/1",
        source_hash="hash1"
    )

    db.save_filing(filing)
    filing_sql = executed_queries[0][0]
    assert "CASE" in filing_sql
    assert "COALESCE" in filing_sql
    assert "source_hash = EXCLUDED.source_hash" not in filing_sql

    executed_queries.clear()
    fact = FactObservation(
        fact_id="fact_new",
        canonical_fact_key="ckey_1",
        filing_id="filing_1",
        concept="us-gaap:Revenues",
        value=100.0,
    )

    # Insert case: row returned
    cursor_obj.fetchone_result = {"fact_id": "fact_inserted"}
    res_id = db.save_fact_observation(fact)
    fact_sql = executed_queries[0][0]
    assert "DO NOTHING" in fact_sql
    assert "DO UPDATE" not in fact_sql
    assert res_id == "fact_inserted"

    # Conflict case: DO NOTHING returns no row, select returns stored row with different value
    executed_queries.clear()
    cursor_obj.fetchone_result = None
    # Next call to fetchone (inside select) returns stored fact with value 200.0
    def side_effect_execute(sql, params=None):
        executed_queries.append((sql, params))
        if "SELECT fact_id" in sql:
            cursor_obj.fetchone_result = {"fact_id": "fact_stored", "value": 200.0}

    cursor_obj.execute = side_effect_execute
    res_id2 = db.save_fact_observation(fact)
    assert res_id2 == "fact_stored"
    assert db.fact_value_conflicts == 1
    assert len(db.fact_conflict_examples) == 1
    assert db.fact_conflict_examples[0]["stored_value"] == 200.0
    assert db.fact_conflict_examples[0]["new_value"] == 100.0


def test_retriever_idempotency_and_conflicts(tmp_path):
    store = ObjectStore(base_path=tmp_path)

    fake_db_assets = {}
    fake_db_hashes = {}
    saved_filings = []
    saved_assets = []

    class FakeDB:
        def get_filing_assets(self, filing_id):
            return fake_db_assets.get(filing_id, [])
        def get_filing_hash(self, filing_id):
            return fake_db_hashes.get(filing_id)
        def save_filing(self, filing):
            fake_db_hashes[filing.filing_id] = filing.source_hash
            saved_filings.append(filing)
            return True
        def save_filing_asset(self, asset):
            saved_assets.append(asset)
            fake_db_assets.setdefault(asset.filing_id, []).append(asset)

    db = FakeDB()
    retriever = FilingRetriever(object_store=store, db_manager=db)

    downloads_count = 0
    def fake_download(filing):
        nonlocal downloads_count
        downloads_count += 1
        return b"<html>payload</html>", "text/html", "htm"

    retriever._download_filing_payload_with_retry = fake_download

    filing1 = Filing(
        filing_id="filing_100",
        issuer_id="issuer_1",
        accession_number="0000100-23-000001",
        form_type="10-K",
        filing_date=date(2023, 10, 1),
        report_period=date(2023, 9, 30),
        source_uri="http://example.com/100",
        source_hash=""
    )

    # (b) First retrieval: no asset -> 1 download, filing hash set
    assets1 = retriever.fetch_missing_assets([filing1])
    assert downloads_count == 1
    assert len(assets1) == 1
    hash1 = assets1[0].hash
    assert fake_db_hashes["filing_100"] == hash1

    # (a) Second retrieval: valid asset existing -> 0 new downloads, returned
    assets2 = retriever.fetch_missing_assets([filing1])
    assert downloads_count == 1
    assert assets2[0].asset_id == assets1[0].asset_id

    # (c) Asset file missing on disk -> 1 new download triggered
    fake_asset = assets1[0]
    os.remove(fake_asset.storage_uri.replace("file://", ""))
    assets3 = retriever.fetch_missing_assets([filing1])
    assert downloads_count == 2

    # (d) & (g) Stored non-empty filing hash differs from new download hash -> conflict added, hash unchanged
    filing2 = Filing(
        filing_id="filing_200",
        issuer_id="issuer_1",
        accession_number="0000200-23-000002",
        form_type="10-K",
        filing_date=date(2023, 10, 1),
        report_period=date(2023, 9, 30),
        source_uri="http://example.com/200",
        source_hash=""
    )
    fake_db_hashes["filing_200"] = "preset_different_hash"
    assets4 = retriever.fetch_missing_assets([filing2])
    assert downloads_count == 3
    assert len(retriever.conflicts) == 1
    assert retriever.conflicts[0]["stored_hash"] == "preset_different_hash"
    assert fake_db_hashes["filing_200"] == "preset_different_hash"

    # (e) Asset ID is stable for same filing, type, and hash
    asset_id_a = stable_id("asset", "filing_200", "IXBRL", "hash_xyz")
    asset_id_b = stable_id("asset", "filing_200", "IXBRL", "hash_xyz")
    assert asset_id_a == asset_id_b

    # (f) Valid existing asset with empty stored filing hash -> reused with 0 downloads & filing hash set from asset
    filing3 = Filing(
        filing_id="filing_300",
        issuer_id="issuer_1",
        accession_number="0000300-23-000003",
        form_type="10-K",
        filing_date=date(2023, 10, 1),
        report_period=date(2023, 9, 30),
        source_uri="http://example.com/300",
        source_hash=""
    )
    # Store asset payload first
    s_uri, s_hash = store.store_asset("issuer_1", "filing_300", "doc.htm", b"content3")
    existing_asset3 = FilingAsset(
        asset_id=stable_id("asset", "filing_300", "IXBRL", s_hash),
        filing_id="filing_300",
        asset_type="IXBRL",
        storage_uri=s_uri,
        mime_type="text/html",
        hash=s_hash,
        retrieved_at=datetime.now(timezone.utc)
    )
    fake_db_assets["filing_300"] = [existing_asset3]
    fake_db_hashes["filing_300"] = ""

    assets5 = retriever.fetch_missing_assets([filing3])
    assert downloads_count == 3  # 0 new downloads!
    assert fake_db_hashes["filing_300"] == s_hash


def test_deterministic_ids_for_chunks_events_metrics():
    # 1. Chunks
    chunks1 = FilingParser._chunk_text("filing_1", "Item 1", "Some long text content for chunking", max_chunk_size=20)
    chunks2 = FilingParser._chunk_text("filing_1", "Item 1", "Some long text content for chunking", max_chunk_size=20)
    assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]

    chunks_diff = FilingParser._chunk_text("filing_1", "Item 1", "Different text content altogether", max_chunk_size=20)
    assert chunks1[0].chunk_id != chunks_diff[0].chunk_id

    # 2. Events
    issuer = Issuer(issuer_id="issuer_1", market="US", legal_name="Co", ticker="CO", cik="123", fiscal_year_end="1231")
    filing = Filing(filing_id="filing_1", issuer_id="issuer_1", accession_number="123-45", form_type="8-K", filing_date=date(2023, 1, 1), report_period=date(2023, 1, 1), source_uri="u", source_hash="h")
    chunk = TextChunk(chunk_id="chunk_123", filing_id="filing_1", section="Item 1", text="An accounting policy change was adopted", source_span={"char_start": 0, "char_end": 10})

    emitter = MaterialEventEmitter(db_manager=MagicMock())
    events1 = emitter.emit_events(issuer, [filing], [chunk])
    events2 = emitter.emit_events(issuer, [filing], [chunk])
    assert [e.event_id for e in events1] == [e.event_id for e in events2]

    # 3. Metrics
    id_metric1 = stable_id("metric", "issuer_1", "REVENUE", "FY2023", False)
    id_metric2 = stable_id("metric", "issuer_1", "REVENUE", "FY2023", False)
    assert id_metric1 == id_metric2

    id_derived1 = stable_id("metric", "issuer_1", "REVENUE", "Q4-2023 (DERIVED)", True)
    id_derived2 = stable_id("metric", "issuer_1", "REVENUE", "Q4-2023 (DERIVED)", True)
    assert id_derived1 == id_derived2
