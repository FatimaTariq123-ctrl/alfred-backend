"""
Top-Level Pipeline Orchestrator (§18 Pseudocode)

Executes the 7-stage Filing Intelligence pipeline end-to-end:
Filing Indexer -> Window Resolver -> Retriever -> Parser -> Normalizer -> Version Resolver -> Event Emitter -> Quality Harness -> FIE Handover Contract
"""

import uuid
import logging
from datetime import date, datetime, timezone
from typing import List, Dict, Any, Optional

from config.policy import DEFAULT_POLICY
from schema.models import IngestionRun, QualityIssue
from storage.db import DatabaseManager
from storage.object_store import ObjectStore

from pipeline.indexer import FilingIndexer
from pipeline.window_resolver import WindowResolver
from pipeline.retriever import FilingRetriever
from pipeline.parser import FilingParser
from pipeline.normalizer import Normalizer
from pipeline.version_resolver import VersionResolver
from pipeline.events import MaterialEventEmitter
from adaptive.history_engine import AdaptiveHistoryEngine
from quality.harness import QualityHarness
from handover.contract import HandoverContractGenerator, FIECompanyState

from common.logging_setup import stage, setup_structured_logging

logger = logging.getLogger(__name__)


def run_filing_intelligence(
    ticker_or_cik: str,
    as_of_date: Optional[date] = None,
    mode: str = "normal",
    trigger_flags: Optional[List[str]] = None,
    db_manager: Optional[DatabaseManager] = None,
    object_store: Optional[ObjectStore] = None,
    stage_times: Optional[Dict[str, float]] = None
) -> FIECompanyState:
    """
    Main entry point for CLAX Filing Intelligence US (EDGAR) Connector.
    Mirrors top-level pseudocode in §18.
    Tracks timing per pipeline stage when stage_times dictionary is passed.
    """
    as_of = as_of_date or date.today()
    run_id = f"run_{ticker_or_cik.upper()}_{uuid.uuid4().hex[:8]}"
    timing_store = stage_times if stage_times is not None else {}

    logger.info(f"=== Starting CLAX Filing Intelligence Run [{run_id}] for {ticker_or_cik} (as_of={as_of.isoformat()}, mode={mode}) ===")

    db = db_manager or DatabaseManager()
    store = object_store or ObjectStore()

    import importlib.metadata
    try:
        edgartools_ver = importlib.metadata.version("edgartools")
    except importlib.metadata.PackageNotFoundError:
        edgartools_ver = "unknown"

    # Create IngestionRun provenance record (§11.1, C10)
    ingestion_run = IngestionRun(
        run_id=run_id,
        issuer_id=f"issuer_US_{ticker_or_cik.upper()}",
        as_of_date=as_of,
        policy_version=DEFAULT_POLICY.policy_version,
        edgartools_version=edgartools_ver,
        parser_version=DEFAULT_POLICY.parser_version,
        normalizer_version=DEFAULT_POLICY.normalizer_version,
        status="RUNNING",
        started_at=datetime.now(timezone.utc)
    )
    db.save_ingestion_run(ingestion_run)
    try:

        # Stage 1: Filing Indexer (§4.1)
        with stage("index", timing_store, logger):
            indexer = FilingIndexer(db_manager=db)
            index_res = indexer.get_full_filing_index(ticker_or_cik, as_of_date=as_of)
            if not isinstance(index_res, tuple) or len(index_res) != 2 or index_res[0] is None or index_res[1] is None:
                raise RuntimeError(f"Indexing returned no valid result for {ticker_or_cik}")
            issuer, full_index = index_res


        # Stage 2: Adaptive History & Window Resolver (§3.1, §4.2, §10)
        with stage("window_resolve", timing_store, logger):
            history_engine = AdaptiveHistoryEngine(policy=DEFAULT_POLICY, db_manager=db)
            history_decision = history_engine.evaluate_and_persist(
                issuer=issuer,
                run_id=run_id,
                requested_mode=mode,
                explicit_triggers=trigger_flags
            )

            window_resolver = WindowResolver(policy=DEFAULT_POLICY)
            window_out = window_resolver.resolve(
                issuer_id=issuer.issuer_id,
                market=issuer.market,
                as_of_date=as_of,
                analysis_mode=history_decision.mode.lower(),
                trigger_flags=history_decision.triggers,
                all_filings=full_index
            )

            if window_out.years_selected != history_decision.years_selected:
                raise RuntimeError(
                    f"WindowResolver years_selected ({window_out.years_selected}) does not match "
                    f"HistoryEngine years_selected ({history_decision.years_selected})"
                )

        selected_filings = window_out.required_filings
        logger.info(f"Selected {len(selected_filings)} filings for target analytical window ({history_decision.years_selected} years).")

        # Stage 3: Retriever (§4.2-4.3)
        with stage("retrieve", timing_store, logger):
            retriever = FilingRetriever(object_store=store, db_manager=db)
            assets = retriever.fetch_missing_assets(selected_filings)

        for conflict in getattr(retriever, "conflicts", []):
            db.save_quality_issue(QualityIssue(
                issue_id=f"issue_src_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                filing_id=conflict["filing_id"],
                rule_code="SOURCE_CHANGED",
                severity="WARNING",
                status="OPEN",
                details={
                    "message": "Downloaded source differs from the stored source; stored hash and raw file kept.",
                    "accession": conflict["accession"],
                    "stored_hash": conflict["stored_hash"],
                    "new_hash": conflict["new_hash"]
                }
            ))

        # Stage 4: Parser / Extractor (§4.1-4.3)
        with stage("parse", timing_store, logger):
            parser = FilingParser(object_store=store, db_manager=db)
            facts, chunks = parser.extract(selected_filings, assets)

        for entry in getattr(parser, "parse_report", []):
            has_errors = bool(entry.get("errors"))
            no_chunks = entry.get("chunks", 0) == 0
            fallback_used = bool(entry.get("used_fallback"))
            form = entry.get("form_type", "")
            no_facts = form in {"10-K", "10-Q", "10-K/A", "10-Q/A"} and entry.get("facts_kept", 0) == 0

            if has_errors or no_chunks or fallback_used or no_facts:
                reasons = []
                if has_errors: reasons.append(f"Parser errors: {entry.get('errors')}")
                if no_chunks: reasons.append("No text chunks extracted")
                if fallback_used: reasons.append("Used unclassified fallback text chunking")
                if no_facts: reasons.append(f"0 facts extracted for financial form {form}")

                details_dict = dict(entry)
                details_dict["reason"] = "; ".join(reasons)

                db.save_quality_issue(QualityIssue(
                    issue_id=f"issue_parse_{uuid.uuid4().hex[:12]}",
                    run_id=run_id,
                    filing_id=entry.get("filing_id"),
                    rule_code="EXTRACTION_ACCURACY",
                    severity="WARNING",
                    status="FLAGGED",
                    details=details_dict
                ))

        # Stage 5: Normalizer & Canonical Fact Key Hashing (§6.1, §8)
        with stage("normalize", timing_store, logger):
            normalizer = Normalizer(db_manager=db)
            normalized_facts, metrics, norm_issues = normalizer.normalize(
                issuer=issuer,
                filings=selected_filings,
                facts=facts,
                run_id=run_id,
                history_years=history_decision.years_selected
            )

        if getattr(db, "fact_value_conflicts", 0) > 0:
            db.save_quality_issue(QualityIssue(
                issue_id=f"issue_src_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                filing_id=selected_filings[0].filing_id if selected_filings else None,
                rule_code="SOURCE_CHANGED",
                severity="WARNING",
                status="OPEN",
                details={
                    "message": f"{db.fact_value_conflicts} fact values differ from the stored values for the same fact; stored values kept.",
                    "count": db.fact_value_conflicts,
                    "examples": list(db.fact_conflict_examples)
                }
            ))
            db.fact_value_conflicts = 0
            db.fact_conflict_examples = []

        # Stage 6: Version Resolver & Multi-Filing Restatement Logic (§7.1-7.3)
        with stage("version_resolve", timing_store, logger):
            version_resolver = VersionResolver(db_manager=db, policy=DEFAULT_POLICY)
            fact_versions, restatement_events = version_resolver.resolve(
                filings=selected_filings,
                facts=normalized_facts,
                metrics=metrics
            )

        # Stage 7: Material Event Stream Emitter (§9)
        with stage("events", timing_store, logger):
            event_emitter = MaterialEventEmitter(db_manager=db)
            all_events = event_emitter.emit_events(issuer=issuer, filings=selected_filings, chunks=chunks)
            all_events.extend(restatement_events)

        # Stage 8: Quality Validation Harness (§12, §14, §20.5)
        with stage("quality_harness", timing_store, logger):
            harness = QualityHarness(db_manager=db)
            quality_report = harness.validate(
                run_id=run_id,
                issuer=issuer,
                filings=selected_filings,
                facts=normalized_facts,
                versions=fact_versions,
                metrics=metrics,
                external_issues=norm_issues    # the normalizer's own findings (UNIT_CONSISTENCY, DIMENSION_AMBIGUITY,
                                                # PERIOD_MAPPING, MISSING_PERIOD) are persisted and counted here, not discarded
            )

        # Stage 9: Generate FIE Handover Output Contract (§20)
        with stage("handover", timing_store, logger):
            contract_gen = HandoverContractGenerator()
            handover_state = contract_gen.generate_contract(
                issuer=issuer,
                as_of_date=as_of,
                history_decision=history_decision,
                filings=selected_filings,
                metrics=metrics,
                versions=fact_versions,
                events=MaterialEventEmitter.economic_events(all_events),   # a duplicate submission is counted once
                quality_report=quality_report
            )

            try:
                db.save_fie_company_state(run_id, handover_state)
            except Exception as e:
                logger.error(f"Failed to persist FIE company state for run {run_id}: {e}")
                ingestion_run.status = "FAILED"
                ingestion_run.completed_at = datetime.now(timezone.utc)
                db.save_ingestion_run(ingestion_run)
                raise

        # Complete Ingestion Run record after handover persistence
        ingestion_run.status = "COMPLETED" if quality_report.is_valid else "FAILED"
        ingestion_run.completed_at = datetime.now(timezone.utc)
        db.save_ingestion_run(ingestion_run)

        logger.info(f"=== Completed Run [{run_id}] Handover Status: {handover_state.handover_status} (Confidence: {handover_state.confidence}) ===")
        return handover_state
    except Exception:
        # Any failure anywhere in the pipeline must close out the run honestly: a crash, Ctrl+C,
        # or network error must not leave ingestion_run.status at "RUNNING" forever (it previously
        # did, which is why production held abandoned RUNNING rows with no completed_at).
        ingestion_run.status = "FAILED"
        ingestion_run.completed_at = datetime.now(timezone.utc)
        try:
            db.save_ingestion_run(ingestion_run)
        except Exception:
            logger.exception(f"Could not mark run {run_id} as FAILED after it failed")
        raise
