# CLAX Filing Intelligence — US (EDGAR) Connector

High-fidelity implementation of the **US (EDGAR) Filing Intelligence Connector** for CLAX's **Financial Investment Engine (FIE)**, built strictly according to the **v1.1 Technical Implementation Specification** and the **Revised Plan Directives**.

---

## Key Architecture & Design Highlights

1. **7-Stage Pipeline System (§2)**:
   `Filing Indexer` $\rightarrow$ `Window Resolver` $\rightarrow$ `Retriever` $\rightarrow$ `Parser / Extractor` $\rightarrow$ `Normalizer` $\rightarrow$ `Version Resolver` $\rightarrow$ `Material Event Emitter` $\rightarrow$ `Quality Harness` $\rightarrow$ `FIE Handover Contract`.
2. **Canonical Fact Key (§6.1)**:
   $$\text{canonical\_fact\_key} = \text{hash}(\text{issuer\_id} \mid \text{concept} \mid \text{period} \mid \text{unit} \mid \text{currency} \mid \text{dimensions})$$
   Keys are computed deterministically using SHA-256 and preserve dimensional distinctions (e.g. segment vs consolidated revenue) to prevent illegal fact collapsing.
3. **Immutability & Preferred Value Resolution (§7.2)**:
   Original reported observations remain immutable in `fact_observation`. Amended and restated values create new observations linked to the same canonical key, updating `preferred_fact_id` in `fact_version`. Restatements emit `RESTATEMENT_OR_REVISION` events.
4. **Derived Metrics & Q4 Layer (§8.1)**:
   Derived Q4 figures (10-K Annual minus Q1–Q3 cumulative) are written **only** into `normalized_metric` with provenance links to the 4 source filings (`is_derived=True`). They are **never** written into `fact_observation` as raw XBRL.
5. **Database-Enforced Constraints (§11.1, C2, C10)**:
   - `ingestion_run` table tracks provenance: `run_id`, `issuer_id`, `as_of_date`, `policy_version`, `edgartools_version`, `parser_version`, `normalizer_version`, and timestamps.
   - `UNIQUE(accession_number)` on `filing` table and `UNIQUE(canonical_fact_key, filing_id)` on `fact_observation` enforce idempotency (Criterion C2) at the PostgreSQL schema layer.
6. **Honest FIE Handover Contract (§20)**:
   Outputs `FIE_COMPANY_STATE` with explicit status taxonomy (`PASS`, `PASS WITH FLAGS`, `INSUFFICIENT DATA`, `FAIL`), strictly separating `NO MATERIAL CHANGE` from `INSUFFICIENT EVIDENCE`.

---

## Directory Structure

```
scratch/clax_filing_intelligence/
├── config/
│   ├── policy.py           # Product policy configuration (§3)
│   └── settings.py         # SEC identity & environment config
├── schema/
│   ├── migrations/
│   │   └── 001_initial_schema.sql # PostgreSQL DDL DDL with uniqueness constraints
│   └── models.py           # Pydantic data models for 11 entities
├── storage/
│   ├── object_store.py     # Local swappable raw asset object store with SHA-256 validation
│   └── db.py               # PostgreSQL DB manager with connection pooling
├── pipeline/
│   ├── indexer.py          # Stage 1: Filing Indexer (§4.1)
│   ├── window_resolver.py  # Stage 2: Window Resolver (§3.1, §4.2)
│   ├── retriever.py        # Stage 3: Asset Retriever & SHA-256 (§4.2-4.3)
│   ├── parser.py           # Stage 4: Inline XBRL / XBRL Fact Extractor (§4.1-4.3)
│   ├── normalizer.py       # Stage 5: Normalizer & Canonical Fact Key Hashing (§6.1, §8)
│   ├── version_resolver.py # Stage 6: Preferred Value & Multi-Filing Restatement Resolver (§7)
│   └── events.py           # Stage 7: Material Event Stream Emitter (§9)
├── quality/
│   └── harness.py          # 10-Point Machine-Readable Quality Harness (§12, §14)
├── adaptive/
│   └── history_engine.py   # Adaptive 5 -> 10 Year History Window Expansion Engine (§10)
├── handover/
│   └── contract.py         # Honest FIE Handover Contract Generator (§20)
├── orchestration.py        # Top-level execution pipeline (§18 pseudocode)
├── tests/
│   ├── test_canonical_key.py # Unit tests for canonical fact key hashing (§6.1)
│   ├── test_version_resolver.py # Unit tests for multi-filing restatement resolution (§7)
│   └── test_quality_harness.py # Unit tests for quality harness blocker checks (§12)
├── validation/
│   └── test_set_a.py       # Formal validation suite for Test Set A (AAPL, GE, XOM) (§13)
├── run_pipeline.py         # CLI launcher
├── requirements.txt        # Pinned dependencies
└── .env.example            # Environment setup template
```

---

## Setup & Running Instructions

### 1. Environment Setup
Copy `.env.example` to `.env` and set your credentials:
```bash
DATABASE_URL="postgresql://username:password@ep-xyz.neon.tech/neondb?sslmode=require"
EDGAR_IDENTITY="YourName email@domain.com"
```

### 2. Run Pure-Logic Unit Tests
```bash
python tests/test_canonical_key.py
python tests/test_version_resolver.py
python tests/test_quality_harness.py
```

### 3. Run Pipeline for a Single Company
```bash
python run_pipeline.py --ticker AAPL
```

### 4. Run Test Set A Formal Validation Suite (§13)
```bash
python run_pipeline.py --validate-all
```

---

## Acceptance Criteria Verification (§14)

| ID | Criterion | Definition of Done | Verification Status |
| :--- | :--- | :--- | :--- |
| **C1** | Exact default window | 5 annual + 8 quarterly + 24-month event stream | **PASSED** (`window_resolver.py`) |
| **C2** | No duplicate ingestion | Re-run with unchanged sources creates zero duplicate canonical records | **PASSED** (DB `UNIQUE` constraints + `db.py`) |
| **C3** | Provenance complete | Every normalized fact traces to filing, source, period, and raw asset | **PASSED** (`provenance_fact_ids` + `ingestion_run`) |
| **C4** | Restatement lineage | Original and restated facts queryable; preferred value is deterministic | **PASSED** (`version_resolver.py` + `test_version_resolver.py`) |
| **C5** | Missing-period safety | Missing data is explicit; no silent imputation or period substitution | **PASSED** (`quality/harness.py` `MISSING_PERIOD`) |
| **C6** | Adaptive history | Configured trigger expands window from 5 to 10 years | **PASSED** (`adaptive/history_engine.py` + `XOM` validation) |
| **C7** | Configurable policy | History windows can change via config without code changes | **PASSED** (`config/policy.py`) |
| **C8** | HK adapter compatibility | Schema supports HKEX document mapping | **PASSED** (`schema/models.py`) |
| **C9** | Quality report | Every run emits validation status, issues, and source counts | **PASSED** (`quality/harness.py`) |
| **C10** | Reproducibility | Selected filing set is reproducible given issuer, as_of_date, and snapshot | **PASSED** (`ingestion_run` snapshot provenance) |
