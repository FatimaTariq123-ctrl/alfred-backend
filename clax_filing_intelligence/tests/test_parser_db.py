import pytest
from unittest.mock import MagicMock
from datetime import date
from schema.models import Filing, TextChunk
from pipeline.parser import FilingParser
from storage.db import DatabaseManager


def test_save_text_chunks_sql_and_rollback():
    db = DatabaseManager.__new__(DatabaseManager)

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    db.get_connection = MagicMock(return_value=mock_conn)

    chunks = [
        TextChunk(
            chunk_id="chunk_1",
            filing_id="f_1",
            section="Item 1. Business",
            text="Text chunk 1",
            parser_version="1.2.0"
        ),
        TextChunk(
            chunk_id="chunk_2",
            filing_id="f_1",
            section="Item 1A. Risk Factors",
            text="Text chunk 2",
            parser_version="1.2.0"
        )
    ]

    # Test success path
    db.save_text_chunks(chunks)
    assert mock_cur.executemany.call_count == 1
    assert mock_conn.commit.call_count == 1

    # Test rollback path on exception
    mock_cur.executemany.side_effect = Exception("DB error")
    with pytest.raises(Exception):
        db.save_text_chunks(chunks)
    assert mock_conn.rollback.call_count == 1


def test_strip_html_tags_removes_ix_header_script_style():
    html = """
    <html>
      <head>
        <style>body { color: red; }</style>
        <script>console.log("hello");</script>
      </head>
      <body>
        <ix:header><ix:hidden>Secret Header</ix:hidden></ix:header>
        <p>Real Content Here</p>
      </body>
    </html>
    """
    cleaned = FilingParser._strip_html_tags(html)
    assert "Real Content Here" in cleaned
    assert "color: red" not in cleaned
    assert "console.log" not in cleaned
    assert "Secret Header" not in cleaned


def test_get_by_accession_number_called_once_per_filing(monkeypatch):
    lookup_count = 0

    def mock_lookup(self, filing):
        nonlocal lookup_count
        lookup_count += 1
        return None, []

    monkeypatch.setattr(FilingParser, "_lookup_filing", mock_lookup)

    parser = FilingParser()
    filing = Filing(
        filing_id="f_test_single_lookup",
        issuer_id="issuer_US_TEST",
        accession_number="0000000000-24-000099",
        form_type="10-K",
        filing_date=date(2024, 3, 15),
        report_period=date(2023, 12, 31),
        source_uri="s3://bucket/filing.htm",
        source_hash="hash999"
    )

    monkeypatch.setattr(parser.store, "fetch_asset", lambda uri: b"<html>test</html>")
    monkeypatch.setattr(parser.db, "save_text_chunks", lambda chunks: None)

    parser.extract([filing], [type("Asset", (), {"filing_id": filing.filing_id, "storage_uri": "uri"})()])
    assert lookup_count == 1
