"""
Step 2 (team head item 3): same-day 8-K filings.
Identical disclosure text -> counted once, relationship recorded, nothing deleted.
Different text -> both kept, difference documented. No text -> undetermined, never guessed.
"""
import datetime as dt
import pytest

from schema.models import Issuer, Filing, TextChunk
from pipeline.events import MaterialEventEmitter, item_text_fingerprint

ISSUER = Issuer(issuer_id="issuer_US_CF", market="US", legal_name="CF Industries", ticker="CF", cik="1324404", fiscal_year_end="1231")
DAY = dt.date(2026, 8, 5)
RELEASE = "CF Industries Holdings, Inc. announced results for the quarter ended June 30, 2026. A copy of the press release is attached as Exhibit 99.1."


class BatchDB:
    def __init__(self): self.saved = []
    def save_material_events(self, events): self.saved.extend(events)


def f(acc, items=("2.02", "9.01"), day=DAY, accepted=None):
    return Filing(filing_id=f"filing_{acc.replace('-', '_')}", issuer_id=ISSUER.issuer_id, accession_number=acc, form_type="8-K",
                  filing_date=day, report_period=day, source_uri="u", source_hash="h", sec_items=list(items), accepted_at=accepted)


def text(filing, body, item="2.02", cid="a"):
    return TextChunk(chunk_id=f"{filing.filing_id}_{cid}", filing_id=filing.filing_id, section=f"Item {item}", text=body)


def run(filings, chunks):
    db = BatchDB()
    em = MaterialEventEmitter(db_manager=db)
    events = em.emit_events(ISSUER, filings, chunks)
    return em, events, db


AGENT = "0001104659-26-091275"
SELF = "0001324404-26-000017"


def test_identical_text_is_one_economic_event_and_nothing_is_deleted():
    a, b = f(AGENT, accepted=dt.datetime(2026, 8, 5, 12, 1)), f(SELF, accepted=dt.datetime(2026, 8, 5, 12, 9))
    em, events, db = run([a, b], [text(a, RELEASE), text(b, RELEASE)])
    assert len(events) == 2 and len(db.saved) == 2                       # both rows are still emitted and saved
    by_acc = {e.details["accession"]: e for e in events}
    assert by_acc[AGENT].details["relationship"] == "CANONICAL"
    assert by_acc[AGENT].details["also_filed_as"] == [SELF]
    assert by_acc[SELF].details["relationship"] == "DUPLICATE_SUBMISSION"
    assert by_acc[SELF].details["duplicate_of"] == by_acc[AGENT].event_id
    assert by_acc[SELF].details["canonical_accession"] == AGENT
    assert by_acc[SELF].details["same_day_group"] == sorted([AGENT, SELF])
    assert [e.details["accession"] for e in MaterialEventEmitter.economic_events(events)] == [AGENT]      # counted once


def test_canonical_is_the_one_accepted_first_whatever_the_input_order():
    early = dt.datetime(2026, 8, 5, 12, 1)
    late = dt.datetime(2026, 8, 5, 12, 9)
    for order in (0, 1):
        a, b = f(AGENT, accepted=late), f(SELF, accepted=early)           # now the self-filed one is first
        filings = [a, b] if order == 0 else [b, a]
        _, events, _ = run(filings, [text(a, RELEASE), text(b, RELEASE)])
        kept = MaterialEventEmitter.economic_events(events)
        assert [e.details["accession"] for e in kept] == [SELF]


def test_without_acceptance_time_the_accession_number_decides_and_it_is_stable():
    a, b = f(SELF), f(AGENT)
    _, e1, _ = run([a, b], [text(a, RELEASE), text(b, RELEASE)])
    _, e2, _ = run([b, a], [text(b, RELEASE), text(a, RELEASE)])
    assert [e.details["accession"] for e in MaterialEventEmitter.economic_events(e1)] == [AGENT]
    assert [e.details["accession"] for e in MaterialEventEmitter.economic_events(e2)] == [AGENT]


def test_different_text_keeps_both_and_documents_why():
    a, b = f(AGENT), f(SELF)
    _, events, _ = run([a, b], [text(a, RELEASE), text(b, RELEASE + " Supplemental tables are furnished as Exhibit 99.2.")])
    assert len(MaterialEventEmitter.economic_events(events)) == 2
    for e in events:
        assert e.details["relationship"] == "SEPARATE_FILING"
        assert "differs" in e.details["relationship_basis"]
        assert "duplicate_of" not in e.details


def test_missing_text_is_undetermined_and_reported_never_guessed():
    a, b = f(AGENT), f(SELF)
    em, events, _ = run([a, b], [text(a, RELEASE)])                       # no chunk for b
    assert len(MaterialEventEmitter.economic_events(events)) == 2
    assert {e.details["relationship"] for e in events} == {"UNDETERMINED"}
    assert [n["rule_code"] for n in em.notes] == ["EVENT_SAME_DAY_UNDETERMINED"]


def test_different_items_or_different_days_are_not_compared():
    a = f("0001104659-26-000001", items=("2.02", "9.01"))
    b = f("0001104659-26-000002", items=("5.02", "9.01"))
    c = f("0001104659-26-000003", items=("2.02", "9.01"), day=dt.date(2026, 8, 6))
    _, events, _ = run([a, b, c], [text(a, RELEASE), text(b, RELEASE, "5.02"), text(c, RELEASE)])
    assert all("relationship" not in e.details for e in events)
    assert len(MaterialEventEmitter.economic_events(events)) == 3


def test_three_filings_two_identical_one_different():
    a, b, c = f("0001104659-26-000001"), f("0001104659-26-000002"), f("0001324404-26-000003")
    _, events, _ = run([a, b, c], [text(a, RELEASE), text(b, RELEASE), text(c, "A different announcement under item 2.02.")])
    rel = {e.details["accession"]: e.details["relationship"] for e in events}
    assert rel == {"0001104659-26-000001": "CANONICAL", "0001104659-26-000002": "DUPLICATE_SUBMISSION", "0001324404-26-000003": "SEPARATE_FILING"}
    assert len(MaterialEventEmitter.economic_events(events)) == 2


def test_multi_item_duplicates_are_matched_item_by_item():
    a, b = f(AGENT, items=("1.01", "2.03", "9.01")), f(SELF, items=("1.01", "2.03", "9.01"))
    chunks = [text(x, f"agreement text {i}", item=i, cid=i) for x in (a, b) for i in ("1.01", "2.03")]
    _, events, _ = run([a, b], chunks)
    dups = [e for e in events if e.details.get("duplicate_of")]
    assert len(dups) == 2
    ids = {e.event_id for e in events}
    assert all(d.details["duplicate_of"] in ids and d.details["duplicate_of"] != d.event_id for d in dups)
    assert {d.details["item"] for d in dups} == {"1.01", "2.03"}


def test_the_exhibit_item_text_does_not_break_the_match():
    a, b = f(AGENT), f(SELF)
    ca = [text(a, RELEASE), text(a, "Exhibit 99.1 press release - signed by A", item="9.01", cid="x")]
    cb = [text(b, RELEASE), text(b, "Exhibit 99.1 press release - signed by B, a different signature page", item="9.01", cid="x")]
    _, events, _ = run([a, b], ca + cb)
    assert len(MaterialEventEmitter.economic_events(events)) == 1


def test_fingerprint_ignores_case_and_spacing_but_not_numbers():
    c1 = [TextChunk(chunk_id="1", filing_id="x", section="Item 2.02", text="Net sales were  $1,986 million.")]
    c2 = [TextChunk(chunk_id="2", filing_id="y", section="Item 2.02", text="net SALES were $1,986\nmillion.")]
    c3 = [TextChunk(chunk_id="3", filing_id="z", section="Item 2.02", text="Net sales were $1,987 million.")]
    assert item_text_fingerprint(c1, ("2.02",)) == item_text_fingerprint(c2, ("2.02",))
    assert item_text_fingerprint(c1, ("2.02",)) != item_text_fingerprint(c3, ("2.02",))
    assert item_text_fingerprint([], ("2.02",)) is None


def test_rerun_gives_identical_events_and_ids():
    a, b = f(AGENT, accepted=dt.datetime(2026, 8, 5, 12, 1)), f(SELF, accepted=dt.datetime(2026, 8, 5, 12, 9))
    ch = [text(a, RELEASE), text(b, RELEASE)]
    _, first, _ = run([a, b], ch)
    _, second, _ = run([a, b], ch)
    assert [(e.event_id, e.details.get("duplicate_of")) for e in first] == [(e.event_id, e.details.get("duplicate_of")) for e in second]


# ---------------------------------------------------------------- the investigation script (offline part)
def _load_investigation():
    import importlib.util, pathlib, sys
    scripts = pathlib.Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("investigate_same_day_8k", scripts / "investigate_same_day_8k.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_investigation_verdicts():
    m = _load_investigation()
    base = {"primary": "p1", "exhibits": [("EX-99.1", "x1")], "filers": [("CF INDUSTRIES HOLDINGS", "1324404", "001-32597")]}
    assert m.compare_documents(base, dict(base))["verdict"] == "IDENTICAL_CONTENT"
    other_cover = {**base, "primary": "p2", "filers": [("CF INDUSTRIES INC", "883", "001-1")]}
    r = m.compare_documents(base, other_cover)
    assert r["verdict"] == "SAME_EXHIBITS_DIFFERENT_MAIN_DOCUMENT" and r["same_filers"] is False
    assert m.compare_documents(base, {**base, "exhibits": [("EX-99.1", "x2")]})["verdict"] == "SAME_MAIN_DOCUMENT_DIFFERENT_EXHIBITS"
    assert m.compare_documents(base, {**base, "primary": "p2", "exhibits": [("EX-99.1", "x2")]})["verdict"] == "DIFFERENT_CONTENT"
    assert m.compare_documents({**base, "primary": None}, {**base, "primary": None})["same_main_document"] is False


def test_content_hash_ignores_spacing_and_case():
    m = _load_investigation()
    assert m.content_hash("Net  SALES\nrose") == m.content_hash("net sales rose")
    assert m.content_hash("") is None and m.content_hash(None) is None


def test_investigation_script_runs_end_to_end_against_a_fake_edgar(monkeypatch, capsys):
    """The whole main() path with edgartools replaced by fakes that have the real attribute names."""
    import sys, types
    import edgar
    import config.settings as settings
    m = _load_investigation()

    class Att:
        def __init__(self, seq, doc, dtype, body):
            self.sequence_number, self.document, self.document_type, self._body = seq, doc, dtype, body
            self.extension, self.size = ".htm", len(body)
        def text(self): return self._body

    class Obj:
        items = ["Item 2.02", "Item 9.01"]
        def __getitem__(self, k): return RELEASE if "2.02" in k else "exhibit list"

    def mk_edgar_filing(acc, cover):
        hdr = types.SimpleNamespace(acceptance_datetime=dt.datetime(2026, 8, 5, 12, 1 if acc == AGENT else 9), filers=[
            types.SimpleNamespace(company_information=types.SimpleNamespace(name="CF INDUSTRIES HOLDINGS, INC.", cik="0001324404"),
                                  filing_information=types.SimpleNamespace(file_number="001-32597"))])
        return types.SimpleNamespace(accession_number=acc, header=hdr, obj=lambda: Obj(),
                                     attachments=[Att("1", "main.htm", "8-K", cover + RELEASE), Att("2", "ex991.htm", "EX-99.1", "press release table")])

    edgar_filings = {AGENT: mk_edgar_filing(AGENT, "cover A "), SELF: mk_edgar_filing(SELF, "cover B ")}

    class Rec:
        def __init__(self, acc): self.accession_number, self.filing_date, self.items = acc, dt.date(2026, 8, 5), "2.02,9.01"
        acceptance_datetime = None

    class Co:
        def __init__(self, t): pass
        def get_filings(self, form=None): return [Rec(AGENT), Rec(SELF)]

    monkeypatch.setattr(edgar, "Company", Co)
    monkeypatch.setattr(edgar, "get_by_accession_number", lambda acc: edgar_filings[acc])
    monkeypatch.setattr(settings, "init_edgar_identity", lambda: None)
    monkeypatch.setattr(sys, "argv", ["investigate_same_day_8k.py", "--ticker", "CF", "--as_of", "2026-10-06"])
    m.main()
    out = capsys.readouterr().out
    assert "1 same-day groups" in out
    assert "SAME_EXHIBITS_DIFFERENT_MAIN_DOCUMENT" in out          # the cover pages differ, the exhibit is the same
    assert "CANONICAL" in out and "DUPLICATE_SUBMISSION" in out    # the item text is identical, so the pipeline counts it once
    assert f"counted as an economic event: ['{AGENT}']" in out
