import json
import re
from datetime import date
from storage.db import DatabaseManager
from schema.models import Issuer, Filing, FactObservation, NormalizedMetric, FactVersion
from quality.harness import QualityHarness
from adaptive.history_engine import AdaptiveHistoryEngine
from handover.contract import HandoverContractGenerator

db = DatabaseManager()
conn = db._conn
cursor = conn.cursor()

# Get latest run_id for MSFT
cursor.execute("SELECT run_id FROM ingestion_run WHERE issuer_id = 'issuer_US_MSFT' ORDER BY started_at DESC LIMIT 1;")
latest_run_id = cursor.fetchone()['run_id']

# Get issuer
cursor.execute("SELECT * FROM issuer WHERE ticker = 'MSFT';")
issuer_row = cursor.fetchone()
issuer = Issuer(**issuer_row)

cursor.execute("SELECT * FROM filing WHERE issuer_id = 'issuer_US_MSFT';")
filing_rows = cursor.fetchall()
filings = [Filing(**r) for r in filing_rows]
filing_ids = [f['filing_id'] for f in filing_rows]
filing_map = {f.filing_id: f for f in filings}

cursor.execute("SELECT * FROM fact_observation WHERE filing_id = ANY(%s);", (filing_ids,))
facts = [FactObservation(**r) for r in cursor.fetchall()]

cursor.execute("SELECT * FROM normalized_metric WHERE issuer_id = 'issuer_US_MSFT';")
metrics = [NormalizedMetric(**r) for r in cursor.fetchall()]

cursor.execute("SELECT * FROM fact_version WHERE original_fact_id = ANY(%s);", ([f.fact_id for f in facts],))
versions = [FactVersion(**r) for r in cursor.fetchall()]

harness = QualityHarness(db)
reconciled_count, blocker = harness._reconcile_against_companyfacts(latest_run_id, issuer, filings, facts, metrics, filing_map)
quality_report = harness.validate(run_id=latest_run_id, issuer=issuer, filings=filings, facts=facts, versions=versions, metrics=metrics)

history_engine = AdaptiveHistoryEngine(db_manager=db)
history_decision = history_engine.evaluate_and_persist(issuer=issuer, run_id=latest_run_id, requested_mode='normal')

contract_gen = HandoverContractGenerator()
handover_state = contract_gen.generate_contract(
    issuer=issuer,
    as_of_date=date.today(),
    history_decision=history_decision,
    filings=filings,
    metrics=metrics,
    versions=versions,
    events=[],
    quality_report=quality_report
)

handover_dict = handover_state.model_dump(mode="json")

with open('msft_handover_utf8.json', 'w', encoding='utf-8') as f:
    json.dump(handover_dict, f, indent=2)

concept_map = {
    'REVENUE': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet', 'Revenues'],
    'NET_INCOME': ['NetIncomeLoss']
}
fy_years = [int(re.search(r'(20\d\d)', str(m.period)).group(1)) for m in metrics if str(m.period).startswith('FY') and re.search(r'(20\d\d)', str(m.period))]
max_fy = max(fy_years) if fy_years else None
target_metrics = [m for m in metrics if m.metric_code in concept_map and m.value is not None and str(m.period).startswith('FY') and re.search(r'(20\d\d)', str(m.period)) and (max_fy is None or int(re.search(r'(20\d\d)', str(m.period)).group(1)) < max_fy)]

print("=== EVAL RESULTS ===")
print(f"RECONCILED_COUNT: {reconciled_count}")
print(f"TOTAL_EVALUATED: {len(target_metrics)}")
print(f"MATCH_RATE: {reconciled_count} / {len(target_metrics)}")
