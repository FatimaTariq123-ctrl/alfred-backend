"""
Step 5 (team head item 8): a VALUE_CHANGE revision gets a reason, not just a blanket
"RESTATEMENT_OR_REVISION" label -- SCALE_DIFFERENCE, AMENDED_FILING, RECAST_COMPARATIVE, or RESTATEMENT
(the fallback for a genuine, mechanically unexplained change). "Context" (a dimension mismatch) is not a
category here because canonical_fact_key already hashes dimensions, so two differently-dimensioned facts
never share a key to begin with.

Also fixes a real bug: the handover counted an "AMENDED" FactVersion (an amendment that did not change
this fact's value) as a restatement, inflating restatements_count and comparability_status for every
amendment regardless of whether anything in it actually changed.
"""
import datetime as dt

from schema.models import Issuer, Filing, FactObservation, FactVersion, NormalizedMetric, HistoryDecision
from pipeline.version_resolver import VersionResolver, classify_value_change_reason
from quality.harness import QualityReport
from handover.contract import HandoverContractGenerator


class MockDB:
    def __init__(self):
        self.versions = []
        self.events = []

    def save_fact_versions(self, versions):
        self.versions.extend(versions)

    def save_material_events(self, events):
        self.events.extend(events)

    def save_normalized_metric(self, metric):
        pass


ISSUER_ID = "issuer_US_CF"


def filing(acc, form, filing_date, amendment=False):
    return Filing(filing_id=f"filing_{acc}", issuer_id=ISSUER_ID, accession_number=acc, form_type=form,
                 filing_date=filing_date, report_period=filing_date, source_uri="u", source_hash="h", amendment_flag=amendment)


def fact(fid, filing_id, concept, value, key="k1", end=None, instant=None):
    return FactObservation(fact_id=fid, canonical_fact_key=key, filing_id=filing_id, concept=concept, value=value,
                           unit="USD", currency="USD", period_end=end, instant_date=instant)


def resolve(filings, facts, metrics=None):
    db = MockDB()
    vr = VersionResolver(db_manager=db)
    versions, events = vr.resolve(filings, facts, metrics or [])
    return versions, events, db, vr


# ---------------------------------------------------------------- classify_value_change_reason, pure logic
def test_scale_difference_1000x():
    f = filing("a2", "10-K", dt.date(2026, 2, 1))
    obs = fact("x", f.filing_id, "c", 3249000.0, end=dt.date(2025, 12, 31))
    assert classify_value_change_reason(3249000000.0, 3249000.0, obs, f) == "SCALE_DIFFERENCE"


def test_scale_difference_reciprocal_100x():
    f = filing("a2", "10-K", dt.date(2026, 2, 1))
    obs = fact("x", f.filing_id, "c", 350.0, end=dt.date(2025, 12, 31))
    assert classify_value_change_reason(3.5, 350.0, obs, f) == "SCALE_DIFFERENCE"


def test_amended_filing_category():
    f = filing("a2", "10-K/A", dt.date(2026, 2, 1), amendment=True)
    obs = fact("x", f.filing_id, "c", 150.0, end=dt.date(2025, 12, 31))
    assert classify_value_change_reason(100.0, 150.0, obs, f) == "AMENDED_FILING"


def test_recast_comparative_category():
    f = filing("a2", "10-K", dt.date(2026, 2, 1))  # filed Feb 2026
    obs = fact("x", f.filing_id, "c", 150.0, end=dt.date(2024, 6, 30))  # a comparative over a year old, not this filing's own period
    assert classify_value_change_reason(100.0, 150.0, obs, f) == "RECAST_COMPARATIVE"


def test_a_filings_own_primary_period_is_not_mistaken_for_a_comparative():
    """The exact bug the real CF run exposed: a 10-K is normally filed 45-60 days after its own fiscal year
    end (SEC's deadline for large accelerated filers). With too tight a tolerance, every filing's OWN current-
    period fact looked like a stale comparative and all 29 of CF's real revisions landed in RECAST_COMPARATIVE,
    zero in RESTATEMENT. A gap of ~50 days (normal filing lag) must NOT trigger RECAST_COMPARATIVE."""
    f = filing("a2", "10-K", dt.date(2026, 2, 20))  # filed ~51 days after FY end -- a completely normal 10-K lag
    obs = fact("x", f.filing_id, "c", 133842000.0, end=dt.date(2025, 12, 31))  # this filing's own fiscal year end
    assert classify_value_change_reason(105005000.0, 133842000.0, obs, f) == "RESTATEMENT"


def test_genuine_restatement_is_the_fallback():
    f = filing("a2", "10-K", dt.date(2026, 2, 1))
    obs = fact("x", f.filing_id, "c", 133842000.0, end=dt.date(2025, 12, 31))  # within 45 days of the filing, not amended, not a scale ratio
    assert classify_value_change_reason(105005000.0, 133842000.0, obs, f) == "RESTATEMENT"


def test_a_comparative_further_in_the_past_is_recast_not_a_plain_restatement():
    f = filing("a2", "10-K", dt.date(2026, 2, 1))
    obs = fact("x", f.filing_id, "c", 133842000.0, end=dt.date(2024, 9, 30))  # over a year before the filing: a true stale comparative
    assert classify_value_change_reason(105005000.0, 133842000.0, obs, f) == "RECAST_COMPARATIVE"


def test_scale_check_runs_before_amendment_and_recast_checks():
    """A 1000x-off value inside an amended filing is still a scale artifact, not "the amendment restated it"."""
    f = filing("a2", "10-K/A", dt.date(2026, 2, 1), amendment=True)
    obs = fact("x", f.filing_id, "c", 3249000.0, end=dt.date(2020, 1, 1))  # also old enough to look like a recast
    assert classify_value_change_reason(3249000000.0, 3249000.0, obs, f) == "SCALE_DIFFERENCE"


# ---------------------------------------------------------------- wired into resolve(): events carry the category
def test_resolve_tags_each_restatement_event_with_a_category():
    f1 = filing("a1", "10-K", dt.date(2025, 2, 1))
    f2 = filing("a2", "10-K", dt.date(2026, 2, 1))
    facts = [fact("x1", f1.filing_id, "us-gaap:DepreciationDepletionAndAmortization", 3249000000.0, key="k_dda"),
            fact("x2", f2.filing_id, "us-gaap:DepreciationDepletionAndAmortization", 3249000.0, key="k_dda")]
    versions, events, db, vr = resolve([f1, f2], facts)
    assert len(events) == 1 and events[0].details["revision_category"] == "SCALE_DIFFERENCE"
    assert vr.last_summary["revision_SCALE_DIFFERENCE"] == 1
    assert vr.last_summary["revision_RESTATEMENT"] == 0


def test_resolve_counts_multiple_categories_independently():
    f1 = filing("a1", "10-K", dt.date(2024, 2, 1))
    f2 = filing("a2", "10-K", dt.date(2025, 2, 1))
    f3 = filing("a3", "10-K/A", dt.date(2025, 3, 1), amendment=True)
    facts = [
        fact("s1", f1.filing_id, "c", 3000.0, key="k_scale"), fact("s2", f2.filing_id, "c", 3.0, key="k_scale"),
        fact("m1", f1.filing_id, "c", 100.0, key="k_amend"), fact("m2", f3.filing_id, "c", 150.0, key="k_amend"),
        fact("r1", f1.filing_id, "c", 105005000.0, key="k_real"), fact("r2", f2.filing_id, "c", 133842000.0, key="k_real"),
    ]
    _, events, _, vr = resolve([f1, f2, f3], facts)
    cats = {e.details["revision_category"] for e in events}
    assert cats == {"SCALE_DIFFERENCE", "AMENDED_FILING", "RESTATEMENT"}
    assert vr.last_summary["revision_SCALE_DIFFERENCE"] == 1
    assert vr.last_summary["revision_AMENDED_FILING"] == 1
    assert vr.last_summary["revision_RESTATEMENT"] == 1


# ---------------------------------------------------------------- the handover bug fix
def hd():
    return HistoryDecision(decision_id="h1", issuer_id=ISSUER_ID, run_id="r1", mode="NORMAL", years_selected=5, policy_version="v1.1")


def report():
    return QualityReport(run_id="r1", issuer_id=ISSUER_ID, total_filings_evaluated=1, total_facts_evaluated=1,
                         total_issues=0, blocker_count=0, warning_count=0, info_count=0, is_valid=True, issues=[])


def test_amended_with_unchanged_value_is_not_counted_as_a_restatement():
    """The exact bug: version_reason == "AMENDED" is set for an UNCHANGED classification (the amendment did
    not change this fact's value at all). It must not inflate restatements_count."""
    f = filing("a1", "10-K", dt.date(2026, 1, 1))
    versions = [FactVersion(canonical_key="k1", original_fact_id="x1", preferred_fact_id="x2", version_reason="AMENDED")]
    gen = HandoverContractGenerator()
    state = gen.generate_contract(issuer=Issuer(issuer_id=ISSUER_ID, market="US", legal_name="CF", ticker="CF"),
                                  as_of_date=dt.date(2026, 10, 6), history_decision=hd(), filings=[f], metrics=[],
                                  versions=versions, events=[], quality_report=report())
    assert state.accounting_quality["restatements_count"] == 0
    assert state.accounting_quality["restatement_status"] == "NO_RESTATEMENTS_DETECTED"
    assert state.accounting_quality["comparability_status"] == "COMPARABLE"


def test_restated_version_is_still_counted():
    f = filing("a1", "10-K", dt.date(2026, 1, 1))
    versions = [FactVersion(canonical_key="k1", original_fact_id="x1", preferred_fact_id="x2", version_reason="RESTATED")]
    gen = HandoverContractGenerator()
    state = gen.generate_contract(issuer=Issuer(issuer_id=ISSUER_ID, market="US", legal_name="CF", ticker="CF"),
                                  as_of_date=dt.date(2026, 10, 6), history_decision=hd(), filings=[f], metrics=[],
                                  versions=versions, events=[], quality_report=report())
    assert state.accounting_quality["restatements_count"] == 1


def test_handover_breaks_down_restatements_by_category_and_only_genuine_ones_drive_comparability():
    f = filing("a1", "10-K", dt.date(2026, 1, 1))
    from schema.models import MaterialEvent
    versions = [
        FactVersion(canonical_key="k1", original_fact_id="x1", preferred_fact_id="x2", version_reason="RESTATED"),
        FactVersion(canonical_key="k2", original_fact_id="y1", preferred_fact_id="y2", version_reason="RESTATED"),
    ]
    events = [
        MaterialEvent(event_id="e1", issuer_id=ISSUER_ID, filing_id=f.filing_id, event_type="RESTATEMENT_OR_REVISION",
                     event_date=f.filing_date, severity="LOW", thesis_tags=[], details={"revision_category": "SCALE_DIFFERENCE"}),
        MaterialEvent(event_id="e2", issuer_id=ISSUER_ID, filing_id=f.filing_id, event_type="RESTATEMENT_OR_REVISION",
                     event_date=f.filing_date, severity="HIGH", thesis_tags=[], details={"revision_category": "RESTATEMENT"}),
    ]
    gen = HandoverContractGenerator()
    state = gen.generate_contract(issuer=Issuer(issuer_id=ISSUER_ID, market="US", legal_name="CF", ticker="CF"),
                                  as_of_date=dt.date(2026, 10, 6), history_decision=hd(), filings=[f], metrics=[],
                                  versions=versions, events=events, quality_report=report())
    assert state.accounting_quality["restatements_count"] == 2            # total value changes, unchanged meaning
    assert state.accounting_quality["restatements_by_category"] == {"SCALE_DIFFERENCE": 1, "RESTATEMENT": 1}
    assert state.accounting_quality["genuine_restatements_count"] == 1    # only the RESTATEMENT-category one
    assert state.accounting_quality["comparability_status"] == "RESTATED"  # a genuine one exists, so still RESTATED


def test_only_scale_or_amended_categories_downgrades_comparability_to_reclassified_not_restated():
    f = filing("a1", "10-K", dt.date(2026, 1, 1))
    from schema.models import MaterialEvent
    versions = [FactVersion(canonical_key="k1", original_fact_id="x1", preferred_fact_id="x2", version_reason="RESTATED")]
    events = [MaterialEvent(event_id="e1", issuer_id=ISSUER_ID, filing_id=f.filing_id, event_type="RESTATEMENT_OR_REVISION",
                            event_date=f.filing_date, severity="LOW", thesis_tags=[], details={"revision_category": "SCALE_DIFFERENCE"})]
    gen = HandoverContractGenerator()
    state = gen.generate_contract(issuer=Issuer(issuer_id=ISSUER_ID, market="US", legal_name="CF", ticker="CF"),
                                  as_of_date=dt.date(2026, 10, 6), history_decision=hd(), filings=[f], metrics=[],
                                  versions=versions, events=events, quality_report=report())
    assert state.accounting_quality["genuine_restatements_count"] == 0
    assert state.accounting_quality["comparability_status"] == "RECLASSIFIED"
