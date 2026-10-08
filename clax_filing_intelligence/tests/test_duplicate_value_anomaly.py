"""
Step 10 fix 3 (team head's "Additional Ingestion Fixes", EXP blocker): a filer-side XBRL tagging
error -- the same concept+dimensions carrying the identical value under two different periods inside
one filing, where one period is a stale/duplicate context and the other matches the filing's own
reporting period -- must not be allowed to collide with a genuinely different historical fact and
produce a false restatement event. The real EXP case: filing 0000950170-24-087945 (a 2024-07-30
10-Q covering 2024-06-30) has TWO undimensioned us-gaap:NetIncomeLoss facts both valued 133,842,000:
one correctly tagged 2024-04-01..2024-06-30 (this filing's own quarter), one incorrectly tagged
2022-04-01..2022-06-30 (identical to this filing's own period label for a much older quarter) --
which collided with the real Q2-2022 fact (105,005,000) from an earlier filing and produced a false
HIGH-severity restatement.
"""
import datetime as dt

from schema.models import Issuer, Filing, FactObservation
from pipeline.normalizer import Normalizer
from pipeline.version_resolver import VersionResolver


class FakeDB:
    def __init__(self):
        self.saved_facts = []
        self.saved_metrics = []

    def save_fact_observations(self, facts):
        self.saved_facts.extend(facts)
        return facts

    def save_normalized_metrics(self, metrics):
        self.saved_metrics.extend(metrics)


class MockVRDB:
    def __init__(self):
        self.versions = []
        self.events = []

    def save_fact_versions(self, versions):
        self.versions.extend(versions)

    def save_material_events(self, events):
        self.events.extend(events)

    def save_normalized_metric(self, metric):
        pass


ISSUER = Issuer(issuer_id="issuer_US_EXP", market="US", legal_name="EXP", ticker="EXP", cik="1", fiscal_year_end="1231")


def filing(acc, report_period, filing_date):
    return Filing(filing_id=f"filing_{acc}", issuer_id=ISSUER.issuer_id, accession_number=acc, form_type="10-Q",
                 filing_date=filing_date, report_period=report_period, source_uri="u", source_hash="h")


def fact(fid, filing_id, concept, value, start, end, dims=None):
    return FactObservation(fact_id=fid, canonical_fact_key=f"k_{fid}", filing_id=filing_id, concept=concept, value=value,
                           unit="USD", currency="USD", period_start=start, period_end=end, dimensions=dims)


def normalize(filings, facts):
    n = Normalizer(db_manager=FakeDB())
    return n, *n.normalize(issuer=ISSUER, filings=filings, facts=facts, run_id="r1", history_years=1)


# ---------------------------------------------------------------- the real EXP shape
FILING_A = filing("0000950170-24-007463", dt.date(2023, 12, 31), dt.date(2024, 1, 25))   # the ORIGINAL 2022-Q2 fact's filing
FILING_B = filing("0000950170-24-087945", dt.date(2024, 6, 30), dt.date(2024, 7, 30))     # the filing with the anomaly

ORIGINAL_2022 = fact("orig2022", FILING_A.filing_id, "us-gaap:NetIncomeLoss", 105005000.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
STALE_IN_B = fact("stale_b", FILING_B.filing_id, "us-gaap:NetIncomeLoss", 133842000.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
CURRENT_IN_B = fact("current_b", FILING_B.filing_id, "us-gaap:NetIncomeLoss", 133842000.0, dt.date(2024, 4, 1), dt.date(2024, 6, 30))


def test_the_stale_duplicate_is_flagged_not_the_current_one():
    n, normalized_facts, _, issues = normalize([FILING_A, FILING_B], [ORIGINAL_2022, STALE_IN_B, CURRENT_IN_B])
    by_id = {f.fact_id: f for f in normalized_facts}
    assert by_id["stale_b"].excluded_from_versioning is True
    assert by_id["stale_b"].exclusion_reason == "DUPLICATE_VALUE_WRONG_PERIOD"
    assert by_id["current_b"].excluded_from_versioning is False
    assert by_id["orig2022"].excluded_from_versioning is False
    assert any(i.rule_code == "DUPLICATE_VALUE_WRONG_PERIOD" and i.fact_id == "stale_b" for i in issues)


def test_stored_fact_is_never_deleted_or_mutated_only_flagged():
    n, normalized_facts, _, _ = normalize([FILING_A, FILING_B], [ORIGINAL_2022, STALE_IN_B, CURRENT_IN_B])
    ids = {f.fact_id for f in normalized_facts}
    assert ids == {"orig2022", "stale_b", "current_b"}   # all three still present, nothing dropped
    stale = next(f for f in normalized_facts if f.fact_id == "stale_b")
    assert stale.value == 133842000.0 and stale.period_start == dt.date(2022, 4, 1)   # value/period unchanged


def test_no_false_restatement_once_fed_through_version_resolver():
    n, normalized_facts, _, _ = normalize([FILING_A, FILING_B], [ORIGINAL_2022, STALE_IN_B, CURRENT_IN_B])
    vr = VersionResolver(db_manager=MockVRDB())
    versions, events = vr.resolve([FILING_A, FILING_B], normalized_facts, [])
    high_events = [e for e in events if e.severity == "HIGH"]
    assert high_events == []        # the false HIGH restatement is gone
    assert vr.last_summary["VALUE_CHANGE"] == 0


def test_ambiguous_case_zero_matches_is_not_touched():
    """Neither copy matches the filing's own period: do not guess which one is wrong."""
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    a = fact("a", f.filing_id, "c", 100.0, dt.date(2022, 1, 1), dt.date(2022, 3, 31))
    b = fact("b", f.filing_id, "c", 100.0, dt.date(2021, 1, 1), dt.date(2021, 3, 31))
    n, normalized_facts, _, issues = normalize([f], [a, b])
    assert all(not fo.excluded_from_versioning for fo in normalized_facts)
    assert not any(i.rule_code == "DUPLICATE_VALUE_WRONG_PERIOD" for i in issues)


def test_ambiguous_case_two_matches_is_not_touched():
    """Both copies match the filing's own period (plausible, e.g. a genuine duplicate submission
    content): do not guess which one is wrong."""
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    a = fact("a", f.filing_id, "c", 100.0, dt.date(2024, 4, 1), dt.date(2024, 6, 30))
    b = fact("b", f.filing_id, "c", 100.0, dt.date(2024, 4, 2), dt.date(2024, 6, 29))
    n, normalized_facts, _, issues = normalize([f], [a, b])
    assert all(not fo.excluded_from_versioning for fo in normalized_facts)


def test_different_values_are_never_flagged():
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    a = fact("a", f.filing_id, "c", 100.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
    b = fact("b", f.filing_id, "c", 200.0, dt.date(2024, 4, 1), dt.date(2024, 6, 30))
    n, normalized_facts, _, issues = normalize([f], [a, b])
    assert all(not fo.excluded_from_versioning for fo in normalized_facts)


def test_different_concepts_are_never_compared():
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    a = fact("a", f.filing_id, "us-gaap:X", 100.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
    b = fact("b", f.filing_id, "us-gaap:Y", 100.0, dt.date(2024, 4, 1), dt.date(2024, 6, 30))
    n, normalized_facts, _, issues = normalize([f], [a, b])
    assert all(not fo.excluded_from_versioning for fo in normalized_facts)


def test_different_filings_are_never_compared_only_within_one_filing():
    """Two genuinely different filings legitimately reporting the same value for the same period
    (e.g. an unchanged metric) must never be flagged -- this check only looks WITHIN one filing."""
    f1 = filing("acc1", dt.date(2023, 12, 31), dt.date(2024, 1, 25))
    f2 = filing("acc2", dt.date(2024, 3, 31), dt.date(2024, 4, 25))
    a = fact("a", f1.filing_id, "c", 100.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
    b = fact("b", f2.filing_id, "c", 100.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
    n, normalized_facts, _, issues = normalize([f1, f2], [a, b])
    assert all(not fo.excluded_from_versioning for fo in normalized_facts)


def test_different_dimensions_are_never_compared():
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    a = fact("a", f.filing_id, "c", 100.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30), dims={"ax": "v1"})
    b = fact("b", f.filing_id, "c", 100.0, dt.date(2024, 4, 1), dt.date(2024, 6, 30), dims={"ax": "v2"})
    n, normalized_facts, _, issues = normalize([f], [a, b])
    assert all(not fo.excluded_from_versioning for fo in normalized_facts)


def test_three_copies_one_current_two_stale_flags_both_stale():
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    current = fact("cur", f.filing_id, "c", 100.0, dt.date(2024, 4, 1), dt.date(2024, 6, 30))
    stale1 = fact("s1", f.filing_id, "c", 100.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
    stale2 = fact("s2", f.filing_id, "c", 100.0, dt.date(2021, 4, 1), dt.date(2021, 6, 30))
    n, normalized_facts, _, issues = normalize([f], [current, stale1, stale2])
    by_id = {fo.fact_id: fo for fo in normalized_facts}
    assert by_id["cur"].excluded_from_versioning is False
    assert by_id["s1"].excluded_from_versioning is True
    assert by_id["s2"].excluded_from_versioning is True


def test_instant_facts_are_also_covered():
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    a = FactObservation(fact_id="a", canonical_fact_key="ka", filing_id=f.filing_id, concept="us-gaap:Assets",
                        value=500.0, unit="USD", currency="USD", instant_date=dt.date(2022, 6, 30))
    b = FactObservation(fact_id="b", canonical_fact_key="kb", filing_id=f.filing_id, concept="us-gaap:Assets",
                        value=500.0, unit="USD", currency="USD", instant_date=dt.date(2024, 6, 30))
    n, normalized_facts, _, issues = normalize([f], [a, b])
    by_id = {fo.fact_id: fo for fo in normalized_facts}
    assert by_id["a"].excluded_from_versioning is True
    assert by_id["b"].excluded_from_versioning is False


def test_zero_value_duplicates_across_periods_are_never_flagged():
    """A real CF pattern: an equity-rollforward line item like AdditionalPaidInCapitalMember often
    reports exactly $0 for several different fiscal years inside the SAME 10-K. That is routine and
    must never be treated as a duplicate-value-wrong-period anomaly."""
    f = filing("acc1", dt.date(2024, 12, 31), dt.date(2025, 2, 20))
    a = fact("a", f.filing_id, "us-gaap:ProfitLoss", 0.0, dt.date(2022, 1, 1), dt.date(2022, 12, 31), dims={"ax": "AdditionalPaidInCapitalMember"})
    b = fact("b", f.filing_id, "us-gaap:ProfitLoss", 0.0, dt.date(2023, 1, 1), dt.date(2023, 12, 31), dims={"ax": "AdditionalPaidInCapitalMember"})
    c = fact("c", f.filing_id, "us-gaap:ProfitLoss", 0.0, dt.date(2024, 1, 1), dt.date(2024, 12, 31), dims={"ax": "AdditionalPaidInCapitalMember"})
    n, normalized_facts, _, issues = normalize([f], [a, b, c])
    assert all(not fo.excluded_from_versioning for fo in normalized_facts)
    assert not any(i.rule_code == "DUPLICATE_VALUE_WRONG_PERIOD" for i in issues)


def test_nonzero_duplicate_is_still_flagged_alongside_zero_duplicates_in_the_same_filing():
    """The zero-value exclusion must not blind the check to a genuine non-zero anomaly sitting in the
    same filing as routine zero repeats."""
    f = filing("acc1", dt.date(2024, 6, 30), dt.date(2024, 7, 30))
    zero_a = fact("za", f.filing_id, "us-gaap:ProfitLoss", 0.0, dt.date(2022, 1, 1), dt.date(2022, 12, 31), dims={"ax": "APIC"})
    zero_b = fact("zb", f.filing_id, "us-gaap:ProfitLoss", 0.0, dt.date(2023, 1, 1), dt.date(2023, 12, 31), dims={"ax": "APIC"})
    current = fact("cur", f.filing_id, "us-gaap:NetIncomeLoss", 100.0, dt.date(2024, 4, 1), dt.date(2024, 6, 30))
    stale = fact("stale", f.filing_id, "us-gaap:NetIncomeLoss", 100.0, dt.date(2022, 4, 1), dt.date(2022, 6, 30))
    n, normalized_facts, _, issues = normalize([f], [zero_a, zero_b, current, stale])
    by_id = {fo.fact_id: fo for fo in normalized_facts}
    assert by_id["za"].excluded_from_versioning is False and by_id["zb"].excluded_from_versioning is False
    assert by_id["stale"].excluded_from_versioning is True and by_id["cur"].excluded_from_versioning is False
