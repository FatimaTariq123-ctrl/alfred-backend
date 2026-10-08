# Phase 0 Reconnaissance Report

## Contradictions / Nuances to Evidence Ledger
- **E6 (`fiscal_year` dtype)**: In `edgartools` 5.58.0, `fiscal_year` is `int64` (not `float64`), with string periods like `'FY'` and `'Q4'`.
- **E17 (Test Suite Baseline)**: Confirmed exactly 4 passed, 1 failed (`test_quality_harness_blocker_detection` due to `TypeError: QualityHarness.validate() got an unexpected keyword argument 'issuer_id'`).

---

## 1. Package Versions
```text
Name: edgartools
Version: 5.58.0

Name: psycopg
Version: 3.3.6

Name: pydantic
Version: 2.13.4
```

---

## 2. Existing Test Suite Results (Baseline)
```text
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\malik ali\.gemini\antigravity\scratch\clax_filing_intelligence
plugins: anyio-4.14.2, asyncio-1.4.0, respx-0.23.1
collected 5 items

tests\test_canonical_key.py ...                                          [ 60%]
tests\test_quality_harness.py F                                          [ 80%]
tests\test_version_resolver.py .                                         [100%]

================================== FAILURES ===================================
___________________ test_quality_harness_blocker_detection ____________________

>       report = harness.validate(
            run_id=run_id,
            issuer_id=issuer_id,
            filings=[filing],
            facts=[],
            versions=[],
            metrics=[]
        )
E       TypeError: QualityHarness.validate() got an unexpected keyword argument 'issuer_id'. Did you mean 'issuer'?

=========================== short test summary info ===========================
FAILED tests/test_quality_harness.py::test_quality_harness_blocker_detection
========================= 1 failed, 4 passed in 2.20s =========================
```

---

## 3. EDGAR Tools XBRL Fact Inspection (AAPL 10-K & 10-Q)
- **Columns of `xbrl.facts.to_dataframe()`**: `['fact_key', 'fact_id', 'concept', 'context_ref', 'value', 'unit_ref', 'currency', 'decimals', 'numeric_value', 'period_type', 'period_start', 'period_end', 'entity_identifier', 'entity_scheme', 'period_key', 'fiscal_period', 'fiscal_year', 'is_dimensioned', 'label', 'original_label', 'balance', 'preferred_sign', 'statement_type', 'statement_role', 'statement_types', 'statement_roles', 'weight', 'period_instant', 'dim_us-gaap_RevenueRemainingPerformanceObligationExpectedTimingOfSatisfactionStartDateAxis', 'dimension', 'member', 'dimension_label', 'dimension_member_label', 'full_dimension_label', 'dim_us-gaap_StatementClassOfStockAxis', 'dim_srt_ProductOrServiceAxis', 'dim_us-gaap_StatementEquityComponentsAxis', 'dim_us-gaap_AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareByAntidilutiveSecuritiesAxis', 'dim_us-gaap_FinancialInstrumentAxis', 'dim_us-gaap_FairValueByFairValueHierarchyLevelAxis', 'dim_us-gaap_LossContingenciesByNatureOfContingencyAxis', 'dim_us-gaap_DerivativeInstrumentRiskAxis', 'dim_us-gaap_HedgingDesignationAxis', 'dim_us-gaap_ConcentrationRiskByBenchmarkAxis', 'dim_us-gaap_ConcentrationRiskByTypeAxis', 'dim_srt_MajorCustomersAxis', 'dim_us-gaap_PropertyPlantAndEquipmentByTypeAxis', 'dim_us-gaap_UnrecordedUnconditionalPurchaseObligationByCategoryOfItemPurchasedAxis', 'dim_srt_RangeAxis', 'dim_us-gaap_ShortTermDebtTypeAxis', 'dim_us-gaap_DebtInstrumentAxis', 'dim_us-gaap_LongtermDebtTypeAxis', 'dim_us-gaap_AwardTypeAxis', 'dim_us-gaap_PlanNameAxis', 'dim_srt_ConsolidationItemsAxis', 'dim_us-gaap_StatementBusinessSegmentsAxis', 'dim_srt_StatementGeographicalAxis']`
- **Columns starting with `dim_` (24 columns)**: `['dim_us-gaap_RevenueRemainingPerformanceObligationExpectedTimingOfSatisfactionStartDateAxis', 'dim_us-gaap_StatementClassOfStockAxis', 'dim_srt_ProductOrServiceAxis', 'dim_us-gaap_StatementEquityComponentsAxis', 'dim_us-gaap_AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareByAntidilutiveSecuritiesAxis', 'dim_us-gaap_FinancialInstrumentAxis', 'dim_us-gaap_FairValueByFairValueHierarchyLevelAxis', 'dim_us-gaap_LossContingenciesByNatureOfContingencyAxis', 'dim_us-gaap_DerivativeInstrumentRiskAxis', 'dim_us-gaap_HedgingDesignationAxis', 'dim_us-gaap_ConcentrationRiskByBenchmarkAxis', 'dim_us-gaap_ConcentrationRiskByTypeAxis', 'dim_srt_MajorCustomersAxis', 'dim_us-gaap_PropertyPlantAndEquipmentByTypeAxis', 'dim_us-gaap_UnrecordedUnconditionalPurchaseObligationByCategoryOfItemPurchasedAxis', 'dim_srt_RangeAxis', 'dim_us-gaap_ShortTermDebtTypeAxis', 'dim_us-gaap_DebtInstrumentAxis', 'dim_us-gaap_LongtermDebtTypeAxis', 'dim_us-gaap_AwardTypeAxis', 'dim_us-gaap_PlanNameAxis', 'dim_srt_ConsolidationItemsAxis', 'dim_us-gaap_StatementBusinessSegmentsAxis', 'dim_srt_StatementGeographicalAxis']`
- **`is_dimensioned` exists**: `True`
- **dtypes**: `fiscal_year`: `int64`, `fiscal_period`: `str` (`<ArrowStringArray>`)
- **Ledger Verification**: E5 confirmed (24 `dim_*` columns present). E6 noted (in 5.58.0 `fiscal_year` is `int64`). E7 confirmed (instants carry `period_instant`).

---

## 4. Section Items Keys (`filing.obj().items`)
- **10-K items**: `['Item 1', 'Item 1A', 'Item 1B', 'Item 1C', 'Item 2', 'Item 3', 'Item 4', 'Item 5', 'Item 6', 'Item 7', 'Item 7A', 'Item 8', 'Item 9', 'Item 9A', 'Item 9B', 'Item 9C', 'Item 10', 'Item 11', 'Item 12', 'Item 13', 'Item 14', 'Item 15', 'Item 16']`
- **10-Q items**: `['Part I, Item 1', 'Part I, Item 2', 'Part I, Item 3', 'Part I, Item 4', 'Part II, Item 1', 'Part II, Item 1A', 'Part II, Item 2', 'Part II, Item 3', 'Part II, Item 4', 'Part II, Item 5', 'Part II, Item 6']`
- **8-K items**: `['Item 5.02']` (and other 8-K items like `Item 2.02`, `Item 4.01`, etc.)
- **Ledger Verification**: Confirms E15 (10-Q keys start with `Part I, Item ...` / `Part II, Item ...`, 8-K keys start with `Item X.YY`).

---

## 5. Issuer Fiscal Year End Attribute
- **`Company("AAPL").fiscal_year_end`**: `'0926'` (September fiscal year end).
- **WI-6 Impact**: `Company` exposes `fiscal_year_end` directly.

---

## 6. Form Types & Amendment Flag Logic
- **Distinct Forms for AAPL**: `['10-K', '10-K/A', '10-K405', '10-Q', '10-Q/A', '144', '144/A', '25', '25-NSE', '3', '3/A', '4', '4/A', '424B2', '424B3', '424B5', '5', '8-A12B', '8-K', '8-K/A', 'CERT', 'CERTNYS', 'CORRESP', 'DEF 14A', 'DEFA14A', 'DEFR14A', 'DFAN14A', 'FWP', 'IRANNOTICE', 'NO ACT', 'NT 10-K', 'NT 10-Q', 'PRE 14A', 'PX14A6G', 'PX14A6N', 'S-3', 'S-3/A', 'S-3ASR', 'S-4', 'S-4/A', 'S-8', 'S-8 POS', 'SC 13D', 'SC 13D/A', 'SC 13G', 'SC 13G/A', 'SC TO-I', 'SC TO-I/A', 'SCHEDULE 13G', 'SCHEDULE 13G/A', 'SD', 'UPLOAD']`
- **Current Indexer Logic (`form.endswith("/A") or form.endswith("A")`)**:
  - Form `DEF 14A` -> `is_amendment=True`, `base_form='DEF 14'` (INCORRECT!)
  - Form `DEFA14A` -> `is_amendment=True`, `base_form='DEFA14'` (INCORRECT!)
- **Ledger Verification**: Confirms E9. Indexer must use `form.endswith("/A")` only and `base_form = form[:-2]`.

---

## 7. Selected Filings Older Than 6 Years Before As-Of Date
- **Total Index Filings**: 2256
- **Selected Filings**: 34
- **Filings older than 6 years before 2026-09-30 (before 2020-09-30)**: 4 filings
  1. `0001193125-10-012091` | Form: `10-K/A` | FilingDate: `2010-01-25` | ReportPeriod: `2009-09-26`
  2. `0001193125-09-087629` | Form: `10-Q/A` | FilingDate: `2009-04-27` | ReportPeriod: `2009-03-28`
  3. `0001047469-98-001822` | Form: `10-K/A` | FilingDate: `1998-01-23` | ReportPeriod: `1997-09-26`
  4. `0000320193-97-000021` | Form: `10-Q/A` | FilingDate: `1997-10-07` | ReportPeriod: `1997-10-07`

---

## 8. Local PostgreSQL Database Status
- **Host**: `localhost`
- **Port**: `5432`
- **Database Name**: `clax_fie`
- **PostgreSQL Version**: `PostgreSQL 17.11 on x86_64-windows, compiled by msvc-19.44.35228, 64-bit`
- **Current User**: `postgres`
- **Schema `public` CREATE Privilege**: `True`
- **Tables and Row Counts**:
  - `fact_observation`: 44,503 rows
  - `fact_version`: 28,176 rows
  - `filing`: 5,470 rows
  - `filing_asset`: 85 rows
  - `history_decision`: 2 rows
  - `ingestion_run`: 2 rows
  - `issuer`: 3 rows
  - `material_event`: 382 rows
  - `normalized_metric`: 65 rows
  - `quality_issue`: 0 rows
  - `text_chunk`: 3,676 rows
- **`psycopg` status**: `psycopg` 3.3.6 working on Python 3.14.6.

---

## 9. Backup Status
- `pg_dump` is **NOT AVAILABLE** on `%PATH%`.
- Existing tables contain active local data (e.g. 44k fact observations). No destructive SQL (`TRUNCATE`/`DELETE`/`DROP`) will be executed unless explicitly requested with `ALLOW_DB_RESET=1` and `--reset-db`.
