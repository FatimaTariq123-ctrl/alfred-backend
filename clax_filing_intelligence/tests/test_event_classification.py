"""
Step 1 (team head item 2): 8-K events are classified from the SEC item numbers, never from a blanket default.
No database, no network: fake DB objects and a fake EDGAR Company only.
"""
import datetime as dt
import pytest

from schema.models import Issuer, Filing, TextChunk
from pipeline.events import MaterialEventEmitter, classify_8k_item, EIGHT_K_ITEMS
from pipeline.indexer import parse_sec_items, FilingIndexer

ISSUER = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF Industries", ticker="CF", cik="1324404", fiscal_year_end="1231")


class BatchDB:
    def __init__(self):
        self.batches = []

    def save_material_events(self, events):
        self.batches.append(list(events))


class SingleRowDB:
    def __init__(self):
        self.rows = []

    def save_material_event(self, event):
        self.rows.append(event)


def make_8k(n=1, items=None, form="8-K", day=None):
    acc = f"0001324404-26-{n:06d}"
    return Filing(filing_id=f"filing_{acc.replace('-', '_')}", issuer_id=ISSUER.issuer_id, accession_number=acc, form_type=form,
                  filing_date=day or dt.date(2026, 5, 6), report_period=day or dt.date(2026, 5, 6), source_uri="u", source_hash="h",
                  sec_items=items)


def chunk(filing, text, section="Item", cid="c1"):
    return TextChunk(chunk_id=f"{filing.filing_id}_{cid}", filing_id=filing.filing_id, section=section, text=text)


def emit(filings, chunks=None, db=None):
    em = MaterialEventEmitter(db_manager=db or BatchDB())
    return em, em.emit_events(ISSUER, filings, chunks or [])


# ---------------------------------------------------------------- item parsing
@pytest.mark.parametrize("raw,expected", [
    ("2.02,9.01", ["2.02", "9.01"]),
    ("Item 5.02, Item 9.01", ["5.02", "9.01"]),
    ("  2.02 ,  9.01  ", ["2.02", "9.01"]),
    (["2.02", "2.02", "9.01"], ["2.02", "9.01"]),
    ("5,7", []),                    # legacy pre-2004 numbering is not an item number here
    ("", []),
    (None, []),
])
def test_parse_sec_items(raw, expected):
    assert parse_sec_items(raw) == expected


# ---------------------------------------------------------------- mapping from the team head's table
@pytest.mark.parametrize("item,expected", [
    ("2.02", "RESULTS_OF_OPERATIONS"), ("5.02", "MANAGEMENT_CHANGE"), ("7.01", "REGULATION_FD"),
    ("5.07", "SHAREHOLDER_VOTE"), ("8.01", "OTHER_MATERIAL_EVENT"), ("1.01", "MATERIAL_AGREEMENT"),
    ("2.03", "NEW_DEBT_OR_FINANCING"),
])
def test_item_maps_to_expected_event(item, expected):
    f = make_8k(1, [item, "9.01"])
    _, events = emit([f])
    assert [e.event_type for e in events] == [expected]
    assert events[0].event_type != "MAJOR_ACQUISITION"
    assert events[0].details["item"] == item
    assert events[0].details["all_items"] == [item, "9.01"]          # the exhibit item is kept as evidence
    assert events[0].details["classification_basis"] == "SEC_ITEM"


def test_exhibit_item_alone_never_makes_a_typed_event():
    _, events = emit([make_8k(1, ["9.01"])])
    assert [e.event_type for e in events] == ["UNCLASSIFIED_8K"]
    assert events[0].details["classification_basis"] == "ONLY_EXHIBIT_ITEM"


# ---------------------------------------------------------------- multi-item filings
def test_multi_item_filing_keeps_every_item():
    f = make_8k(1, ["1.01", "2.03", "9.01"])
    _, events = emit([f])
    assert sorted(e.event_type for e in events) == ["MATERIAL_AGREEMENT", "NEW_DEBT_OR_FINANCING"]
    assert len({e.event_id for e in events}) == 2
    for e in events:
        assert e.details["all_items"] == ["1.01", "2.03", "9.01"]


def test_cf_like_mix_has_no_blanket_acquisition():
    patterns = [["2.02", "9.01"], ["5.02"], ["7.01", "9.01"], ["5.07"], ["8.01", "9.01"], ["1.01", "2.03", "9.01"]]
    filings = [make_8k(n + 1, patterns[n % len(patterns)]) for n in range(30)]
    _, events = emit(filings)
    expected_events = sum(len([i for i in patterns[n % len(patterns)] if i != "9.01"]) for n in range(30))
    assert len(events) == expected_events
    assert all(e.event_type != "MAJOR_ACQUISITION" for e in events)
    assert all(e.event_type in {v[0] for v in EIGHT_K_ITEMS.values()} for e in events)


# ---------------------------------------------------------------- acquisition only with a real basis
def test_acquisition_type_exists_only_for_item_2_01():
    _, events = emit([make_8k(1, ["2.01", "9.01"])])
    assert [e.event_type for e in events] == ["ACQUISITION_OR_DISPOSITION"]
    others = [i for i in EIGHT_K_ITEMS if i != "2.01"]
    assert all(classify_8k_item(i)["event_type"] != "ACQUISITION_OR_DISPOSITION" for i in others)


def test_explicit_acquisition_wording_annotates_but_does_not_retype():
    f = make_8k(1, ["1.01", "9.01"])
    c = chunk(f, "On May 5 the Company entered into an Agreement and Plan of Merger under which it will acquire Example Corp.")
    _, events = emit([f], [c])
    assert [e.event_type for e in events] == ["MATERIAL_AGREEMENT"]
    assert events[0].details["acquisition_evidence"] and "Merger" in events[0].details["acquisition_evidence"]
    assert "acquisition_related" in events[0].thesis_tags


def test_results_release_mentioning_an_acquisition_is_still_results():
    f = make_8k(1, ["2.02", "9.01"])
    c = chunk(f, "Net sales rose after the acquisition of Example Corp. closed in the quarter.")
    _, events = emit([f], [c])
    assert [e.event_type for e in events] == ["RESULTS_OF_OPERATIONS"]
    assert "acquisition_evidence" not in events[0].details


# ---------------------------------------------------------------- fallbacks
def test_items_are_read_from_the_filing_text_when_the_index_has_none():
    f = make_8k(1, None)
    c = chunk(f, "Departure of Directors or Certain Officers.", section="Item 5.02 Departure of Directors or Certain Officers")
    em, events = emit([f], [c])
    assert [e.event_type for e in events] == ["MANAGEMENT_CHANGE"]
    assert events[0].details["item_source"] == "FILING_TEXT"
    assert em.notes == []


def test_no_items_anywhere_is_unclassified_and_reported_not_acquisition():
    em, events = emit([make_8k(1, None)])
    assert [e.event_type for e in events] == ["UNCLASSIFIED_8K"]
    assert events[0].severity == "LOW"
    assert [n["rule_code"] for n in em.notes] == ["EVENT_UNCLASSIFIED_8K"]


def test_unknown_item_is_kept_and_flagged():
    em, events = emit([make_8k(1, ["1.99"])])
    assert events[0].event_type == "OTHER_MATERIAL_EVENT" and events[0].details["unmapped_item"] is True
    assert [n["rule_code"] for n in em.notes] == ["EVENT_UNMAPPED_8K_ITEM"]


def test_item_4_02_is_a_high_severity_restatement_signal():
    _, events = emit([make_8k(1, ["4.02"])])
    assert events[0].event_type == "NON_RELIANCE_ON_FINANCIALS" and events[0].severity == "HIGH"
    assert "restatement" in events[0].thesis_tags


# ---------------------------------------------------------------- determinism and no double counting
def test_same_input_gives_same_ids_and_no_duplicates():
    f = make_8k(1, ["2.02", "2.02", "9.01"])                       # a repeated item must not give two events
    _, first = emit([f])
    _, second = emit([f])
    assert len(first) == 1
    assert [e.event_id for e in first] == [e.event_id for e in second]


def test_different_items_of_one_filing_get_different_ids():
    _, events = emit([make_8k(1, ["5.02", "7.01"])])
    assert len({e.event_id for e in events}) == 2


# ---------------------------------------------------------------- other forms untouched
def test_periodic_report_text_scan_still_works_and_8k_is_not_keyword_scanned():
    tenk = make_8k(1, None, form="10-K")
    c1 = chunk(tenk, "Following the resignation of independent registered public accounting firm we appointed...", cid="a")
    k8 = make_8k(2, ["2.02"])
    c2 = chunk(k8, "auditor change mentioned in passing", cid="b")
    _, events = emit([tenk, k8], [c1, c2])
    types = sorted(e.event_type for e in events)
    assert types == ["AUDITOR_CHANGE", "RESULTS_OF_OPERATIONS"]


# ---------------------------------------------------------------- saving
def test_events_are_saved_in_one_batch():
    db = BatchDB()
    emit([make_8k(1, ["2.02"]), make_8k(2, ["5.02"])], db=db)
    assert len(db.batches) == 1 and len(db.batches[0]) == 2


def test_falls_back_to_single_row_saves_when_no_batch_method():
    db = SingleRowDB()
    emit([make_8k(1, ["2.02"]), make_8k(2, ["5.02"])], db=db)
    assert len(db.rows) == 2


def test_nothing_saved_when_no_events():
    db = BatchDB()
    emit([make_8k(1, None, form="10-Q")], db=db)
    assert db.batches == []


# ---------------------------------------------------------------- the indexer hands the items over
def test_indexer_attaches_edgar_items_to_8k_records_only(monkeypatch):
    class FakeItem:
        def __init__(self, form, acc, items, d):
            self.form, self.accession_number, self.items = form, acc, items
            self.filing_date = d
            self.period_of_report = d

    class FakeCompany:
        cik = 1324404
        name = "CF Industries"
        fiscal_year_end = "1231"

        def __init__(self, ticker):
            pass

        def get_filings(self):
            return [FakeItem("8-K", "0001324404-26-000017", "2.02,9.01", dt.date(2026, 8, 5)),
                    FakeItem("8-K", "0001324404-26-000018", "", dt.date(2026, 8, 6)),
                    FakeItem("10-K", "0001324404-26-000007", "", dt.date(2026, 2, 25))]

    class IndexDB:
        def save_issuer(self, issuer): pass
        def save_filings(self, filings): return True

    import edgar
    monkeypatch.setattr(edgar, "Company", FakeCompany)
    idx = FilingIndexer(db_manager=IndexDB())
    _, filings = idx.get_full_filing_index("CF", dt.date(2026, 10, 6))
    by_acc = {f.accession_number: f for f in filings}
    assert by_acc["0001324404-26-000017"].sec_items == ["2.02", "9.01"]
    assert by_acc["0001324404-26-000018"].sec_items == []              # 8-K with no items in the index -> text fallback later
    assert by_acc["0001324404-26-000007"].sec_items is None            # not an 8-K


# ---------------------------------------------------------------- the acceptance script (offline part)
def test_verify_script_logic_with_a_fake_company():
    import importlib.util, pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "verify_8k_items.py"
    spec = importlib.util.spec_from_file_location("verify_8k_items", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Item:
        def __init__(self, acc, d, items):
            self.accession_number, self.filing_date, self.items = acc, d, items

    class Co:
        def get_filings(self, form=None):
            assert form == "8-K"
            return [Item("0001104659-26-091275", "2026-08-05", "2.02,9.01"),
                    Item("0001324404-26-000017", "2026-08-05", "2.02,9.01"),      # same-day pair
                    Item("0001324404-26-000011", "2026-05-06", "5.07"),
                    Item("0001324404-20-000001", "2020-01-01", "2.02")]           # outside the window
    fs = mod.filings_from_company(Co(), dt.date(2026, 10, 6), 24)
    assert [f.accession_number for f in fs] == ["0001324404-26-000011", "0001104659-26-091275", "0001324404-26-000017"]
    events, by_filing, notes = mod.classify(fs, "CF")
    assert sorted(e.event_type for e in events) == ["RESULTS_OF_OPERATIONS", "RESULTS_OF_OPERATIONS", "SHAREHOLDER_VOTE"]
    # the same-day pair cannot be compared here (this script has the EDGAR index only, no filing text): reported, not guessed
    assert [n["rule_code"] for n in notes] == ["EVENT_SAME_DAY_UNDETERMINED"]
