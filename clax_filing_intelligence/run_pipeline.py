"""
CLAX Filing Intelligence - CLI Launcher

Usage:
  python run_pipeline.py --ticker AAPL
  python run_pipeline.py --ticker GE --as_of 2024-12-31
  python run_pipeline.py --ticker XOM --trigger cycle_sensitivity
  python run_pipeline.py --validate-all
"""

import argparse
import json
import sys
from datetime import datetime, date

from orchestration import run_filing_intelligence
from validation.test_set_a import run_full_test_set_a


def main():
    parser = argparse.ArgumentParser(description="CLAX Filing Intelligence US (EDGAR) Connector CLI")
    parser.add_argument("--ticker", type=str, help="Issuer ticker symbol (e.g. AAPL, GE, XOM)")
    parser.add_argument("--as_of", type=str, help="As of date (YYYY-MM-DD)", default=None)
    parser.add_argument("--mode", type=str, choices=["normal", "extended", "forensic"], default="normal")
    parser.add_argument("--trigger", type=str, help="Optional expansion trigger flag", default=None)
    parser.add_argument("--validate-all", action="store_true", help="Run full Test Set A validation suite")

    args = parser.parse_args()

    if args.validate_all:
        run_full_test_set_a()
        sys.exit(0)

    if not args.ticker:
        print("Please specify a ticker with --ticker or run full validation with --validate-all")
        parser.print_help()
        sys.exit(1)

    as_of_date = datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else date.today()
    triggers = [args.trigger] if args.trigger else []

    handover_state = run_filing_intelligence(
        ticker_or_cik=args.ticker,
        as_of_date=as_of_date,
        mode=args.mode,
        trigger_flags=triggers
    )

    print("\n" + "=" * 60)
    print(f"   FIE COMPANY STATE HANDOVER PACKAGE: {args.ticker.upper()}")
    print("=" * 60)
    print(json.dumps(handover_state.model_dump(), indent=2))
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
