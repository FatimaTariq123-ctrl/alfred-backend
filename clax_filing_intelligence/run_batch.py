"""
Resilient Batch Runner for CLAX Filing Intelligence (§3, Batch Pipeline Orchestrator)

Fetches company universe from Alpaca provider (active, tradable US equities),
and executes the Filing Intelligence pipeline in parallel using a ThreadPoolExecutor
behind a global SEC TokenBucket rate limiter.

Guarantees:
- Configurable --workers (default 4, --workers 1 sequential fallback)
- Configurable --rate (default 8.0 req/s SEC TokenBucket ceiling)
- Configurable --limit (default 5, overrides MAX_COMPANIES setting)
- Process-wide database reset (TRUNCATE) once in main thread before worker pool execution
- Thread-safe DB operations via thread-isolated psycopg v3 connections
- Fault isolation: individual company failures produce an ERROR result without aborting the batch
- Structured logging with [worker=N ticker=XXX] context tags and stage duration tracking
- Original universe order preserved for summary printing and _batch_summary.json evidence
"""

import argparse
import json
import logging
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any, Optional

from config.settings import BASE_DIR, init_edgar_identity, MAX_COMPANIES
from config.policy import PolicyConfig, DEFAULT_POLICY
from universe.alpaca_universe import get_alpaca_company_universe
from orchestration import run_filing_intelligence
from storage.db import DatabaseManager
from common.rate_limiter import SEC_LIMITER
from common.logging_setup import setup_structured_logging, worker_ctx, ticker_ctx

logger = logging.getLogger("run_batch")
HANDOVERS_DIR = BASE_DIR / "handovers"


class SafeJSONEncoder(json.JSONEncoder):
    """
    JSON encoder that safely converts dates, datetimes, Decimals, and Pydantic models to serializable objects.
    """
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return super().default(obj)


def save_company_handover_file(ticker: str, handover_obj: Any):
    """
    Saves a company's full FIE_COMPANY_STATE handover object to handovers/{TICKER}_handover.json.
    """
    try:
        HANDOVERS_DIR.mkdir(parents=True, exist_ok=True)
        out_file = HANDOVERS_DIR / f"{ticker}_handover.json"

        if hasattr(handover_obj, "model_dump"):
            payload = handover_obj.model_dump(mode="json")
        elif isinstance(handover_obj, dict):
            payload = handover_obj
        else:
            payload = str(handover_obj)

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, cls=SafeJSONEncoder, ensure_ascii=False)

        logger.info(f"Saved full handover file: {out_file}")
    except Exception as e:
        logger.error(f"Failed to save handover file for {ticker}: {str(e)}")


def save_company_error_file(ticker: str, name: str, error_message: str):
    """
    Saves a company's failure details to handovers/{TICKER}_ERROR.json.
    """
    try:
        HANDOVERS_DIR.mkdir(parents=True, exist_ok=True)
        out_file = HANDOVERS_DIR / f"{ticker}_ERROR.json"
        payload = {
            "ticker": ticker,
            "name": name,
            "error_message": error_message,
            "timestamp": datetime.now().isoformat()
        }
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, cls=SafeJSONEncoder, ensure_ascii=False)

        logger.info(f"Saved error evidence file: {out_file}")
    except Exception as e:
        logger.error(f"Failed to save error file for {ticker}: {str(e)}")


def save_batch_summary_file(results: List[Dict[str, Any]]):
    """
    Saves the combined batch summary to handovers/_batch_summary.json.
    """
    try:
        HANDOVERS_DIR.mkdir(parents=True, exist_ok=True)
        out_file = HANDOVERS_DIR / "_batch_summary.json"

        summary_payload = [
            {
                "ticker": r["ticker"],
                "name": r["name"],
                "handover_status": r["handover_status"],
                "confidence": r["confidence"],
                "filings_processed": r["filings_processed"],
                "reconciled_facts": r["reconciled_facts"],
                "wall_time_sec": r.get("wall_time", 0.0),
                "stage_times_sec": r.get("stage_times", {}),
                "error_message": r["error_message"]
            }
            for r in results
        ]

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(summary_payload, f, indent=2, cls=SafeJSONEncoder, ensure_ascii=False)

        logger.info(f"Saved batch summary evidence file: {out_file}")
    except Exception as e:
        logger.error(f"Failed to save batch summary file: {str(e)}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="CLAX Filing Intelligence Batch Pipeline Runner (Alpaca Universe Feeder)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"Number of companies to process from Alpaca universe (default: {MAX_COMPANIES} from config/env)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent worker threads (default: 4)"
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=8.0,
        help="Global SEC TokenBucket rate limit ceiling in requests/sec (default: 8.0)"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="normal",
        choices=["normal", "extended", "forensic"],
        help="Analysis mode for historical window resolution (default: normal)"
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="As-of evaluation date (YYYY-MM-DD format, default: today)"
    )
    parser.add_argument(
        "--triggers",
        nargs="*",
        default=None,
        help="Explicit trigger flags (e.g. RESTATEMENT_DETECTED RECLASS_DETECTED)"
    )
    parser.add_argument(
        "--reset-db",
        action="store_true",
        default=False,
        help="Reset database (TRUNCATE all tables) before execution"
    )
    return parser.parse_args()


def run_batch_pipeline(
    limit: Optional[int] = None,
    workers: int = 4,
    rate: float = 8.0,
    mode: str = "normal",
    as_of_date: Optional[date] = None,
    trigger_flags: Optional[List[str]] = None,
    reset_db: bool = False
) -> List[Dict[str, Any]]:
    """
    Executes parallel batch ingestion and quality analysis for companies fetched from Alpaca universe.
    """
    setup_structured_logging()
    init_edgar_identity()

    # Configure global SEC rate limit
    SEC_LIMITER._rate = rate
    SEC_LIMITER._capacity = int(rate) if rate >= 1.0 else 1

    effective_limit = limit if limit is not None else MAX_COMPANIES
    logger.info(
        f"=== Initializing Batch Ingestion (Target Limit: {effective_limit} companies, "
        f"Workers: {workers}, SEC Ceiling: {rate:.1f} req/s) ==="
    )

    # Reset database ONLY if explicitly requested via CLI flag --reset-db
    if reset_db:
        main_db = DatabaseManager()
        main_db.reset_database()

    # 2. Fetch company universe from Alpaca
    universe = get_alpaca_company_universe(limit=effective_limit)
    logger.info(f"Retrieved {len(universe)} companies for batch run: {[c['ticker'] for c in universe]}")

    results_map: Dict[str, Dict[str, Any]] = {}

    def process_company(company: Dict[str, str], worker_id: int) -> Dict[str, Any]:
        ticker = company["ticker"]
        company_name = company["name"]

        worker_ctx.set(str(worker_id))
        ticker_ctx.set(ticker)

        t0 = time.monotonic()
        stage_times: Dict[str, float] = {}

        result_entry = {
            "ticker": ticker,
            "name": company_name,
            "handover_status": "UNKNOWN",
            "confidence": "N/A",
            "reconciled_facts": "N/A",
            "filings_processed": 0,
            "wall_time": 0.0,
            "stage_times": stage_times,
            "error_message": None
        }

        try:
            logger.info(f"Starting pipeline execution for {ticker} - {company_name}...")

            # Each worker thread gets its own isolated DB connection via DatabaseManager()
            thread_db = DatabaseManager()

            handover_state = run_filing_intelligence(
                ticker_or_cik=ticker,
                as_of_date=as_of_date,
                mode=mode,
                trigger_flags=trigger_flags,
                db_manager=thread_db,
                stage_times=stage_times
            )

            result_entry["handover_status"] = handover_state.handover_status
            result_entry["confidence"] = handover_state.confidence

            fin_state = handover_state.financial_state or {}
            result_entry["filings_processed"] = fin_state.get("provenance_filings_count", 0)

            # Query reconciled count from thread database connection
            cursor = thread_db.get_connection().cursor()
            cursor.execute("""
                SELECT COUNT(*) as cnt 
                FROM normalized_metric 
                WHERE issuer_id = %s AND metric_code IN ('REVENUE', 'NET_INCOME', 'OPERATING_INCOME') AND period LIKE 'FY%%';
            """, (f"issuer_US_{ticker}",))
            rec_row = cursor.fetchone()
            reconciled_cnt = rec_row['cnt'] if rec_row else 0
            result_entry["reconciled_facts"] = f"{reconciled_cnt} key facts"

            wall_sec = round(time.monotonic() - t0, 2)
            result_entry["wall_time"] = wall_sec

            logger.info(
                f"SUCCESS [{ticker}]: Status={handover_state.handover_status}, "
                f"Confidence={handover_state.confidence}, Filings={result_entry['filings_processed']}, "
                f"WallTime={wall_sec}s"
            )

            save_company_handover_file(ticker, handover_state)

        except Exception as e:
            wall_sec = round(time.monotonic() - t0, 2)
            result_entry["wall_time"] = wall_sec
            err_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"FAILURE [{ticker}]: Pipeline failed after {wall_sec}s - {err_msg}")
            logger.debug(traceback.format_exc())

            result_entry["handover_status"] = "ERROR"
            result_entry["error_message"] = err_msg

            save_company_error_file(ticker, company_name, err_msg)

        return result_entry

    # 3. Parallel Execution Loop
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(process_company, company, (i % workers) + 1): company["ticker"]
                for i, company in enumerate(universe)
            }
            for fut in as_completed(futures):
                res = fut.result()
                results_map[res["ticker"]] = res
    else:
        # Sequential fallback path (--workers 1)
        for idx, company in enumerate(universe, start=1):
            res = process_company(company, worker_id=1)
            results_map[res["ticker"]] = res

    # 4. Re-order results to match original universe order deterministically
    batch_results = [results_map[c["ticker"]] for c in universe if c["ticker"] in results_map]

    # 5. Save summary and print summary table
    save_batch_summary_file(batch_results)
    print_batch_summary(batch_results)

    return batch_results


def print_batch_summary(results: List[Dict[str, Any]]):
    """
    Prints a formatted summary table of batch execution results and overall totals.
    """
    print("\n" + "=" * 118)
    print("                      CLAX FILING INTELLIGENCE - BATCH RUNNER SUMMARY                      ")
    print("=" * 118)

    headers = f"{'Ticker':<8} | {'Company Name':<30} | {'Handover Status':<20} | {'Confidence':<10} | {'Filings':<8} | {'Reconciled':<12} | {'Time (s)':<8}"
    print(headers)
    print("-" * 118)

    status_counts = {
        "PASS": 0,
        "PASS WITH FLAGS": 0,
        "INSUFFICIENT DATA": 0,
        "FAIL": 0,
        "ERROR": 0
    }

    for res in results:
        status = res["handover_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

        name_truncated = (res['name'][:27] + "...") if len(res['name']) > 30 else res['name']
        row = (
            f"{res['ticker']:<8} | "
            f"{name_truncated:<30} | "
            f"{res['handover_status']:<20} | "
            f"{res['confidence']:<10} | "
            f"{res['filings_processed']:<8} | "
            f"{res['reconciled_facts']:<12} | "
            f"{res.get('wall_time', 0.0):<8.2f}"
        )
        print(row)
        if res["error_message"]:
            print(f"         └─ Error: {res['error_message']}")

    print("-" * 118)
    print("BATCH TOTALS:")
    total_companies = len(results)
    print(f"  Total Companies Processed : {total_companies}")
    print(f"  PASS                      : {status_counts.get('PASS', 0)}")
    print(f"  PASS WITH FLAGS           : {status_counts.get('PASS WITH FLAGS', 0)}")
    print(f"  INSUFFICIENT DATA         : {status_counts.get('INSUFFICIENT DATA', 0)}")
    print(f"  FAIL                      : {status_counts.get('FAIL', 0)}")
    print(f"  ERROR                     : {status_counts.get('ERROR', 0)}")
    print("=" * 118 + "\n")


def main():
    args = parse_args()
    as_of_val = None
    if args.as_of:
        try:
            as_of_val = datetime.strptime(args.as_of, "%Y-%m-%d").date()
        except ValueError:
            logger.error("Invalid --as-of date format. Use YYYY-MM-DD.")
            sys.exit(1)

    run_batch_pipeline(
        limit=args.limit,
        workers=args.workers,
        rate=args.rate,
        mode=args.mode,
        as_of_date=as_of_val,
        trigger_flags=args.triggers,
        reset_db=args.reset_db
    )


if __name__ == "__main__":
    main()
