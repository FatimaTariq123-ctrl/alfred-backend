# Data_loaders/w01_SP500_Tickers_and_Membership.py
# -------------
import os
import logging
import random
from datetime import date
from typing import List
from io import StringIO

import pandas as pd
import requests
import alpaca_trade_api as tradeapi
from dotenv import load_dotenv
from tqdm import tqdm

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------ Alpaca API Setup ------------------ #
load_dotenv()
API_KEY: str = os.getenv("ALPACA_API_KEY", "")
API_SECRET: str = os.getenv("ALPACA_SECRET_KEY", "")
BASE_URL: str = "https://paper-api.alpaca.markets"

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL)

# ------------------ Data Fetching ------------------ #
def fetch_sp500_tickers() -> List[str]:
    """
    Fetch the current S&P 500 tickers from Wikipedia and verify with Alpaca.
    """
    logger.info("--- Starting S&P 500 Ticker Fetching ---")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    logger.info("Fetching S&P 500 list from Wikipedia...")
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    tables = pd.read_html(StringIO(response.text))
    # The correct table with tickers is the first one on the page (index 0)
    raw_tickers: List[str] = tables[0]["Symbol"].str.replace('.', '-', regex=False).tolist()
    logger.info("Successfully fetched %d tickers from Wikipedia.", len(raw_tickers))

    # --- Verify tickers using Alpaca --- #
    logger.info("Verifying tickers with Alpaca...")
    tradable_tickers = verify_tickers_with_alpaca(raw_tickers)
    logger.info("Verified %d tradable tickers via Alpaca.", len(tradable_tickers))

    # Safety: if Alpaca returns 0 tickers, fall back to Wikipedia list
    if len(tradable_tickers) == 0:
        logger.warning(
            "Alpaca verification returned 0 tradable tickers. "
            "Falling back to raw Wikipedia tickers (%d symbols).",
            len(raw_tickers),
        )
        tradable_tickers = raw_tickers

    _save_tickers_to_csv(tradable_tickers)
    logger.info("--- S&P 500 Ticker Fetching Complete ---")
    return tradable_tickers


def verify_tickers_with_alpaca(tickers: List[str]) -> List[str]:
    """
    Verify which tickers are valid and tradable using Alpaca.

    Returns an empty list if Alpaca credentials are missing or if every
    verification call fails. The caller is responsible for falling back
    to the raw Wikipedia tickers in that case.
    """
    # Quick sanity check on credentials so we can log a clear root cause
    if not API_KEY or not API_SECRET:
        logger.warning(
            "Alpaca API credentials are missing or empty. "
            "Skipping Alpaca verification and relying on Wikipedia tickers."
        )
        return []

    verified: List[str] = []
    first_error_logged = False

    for symbol in tqdm(tickers, desc="Verifying Tickers"):
        try:
            asset = api.get_asset(symbol)
            if getattr(asset, "tradable", False):
                verified.append(symbol)
            else:
                logger.debug("Ticker %s not tradable according to Alpaca.", symbol)
        except Exception as e:
            # Log the first failure loudly so users see why verification may fail
            if not first_error_logged:
                logger.warning(
                    "Alpaca verification failed for ticker %s. "
                    "This may indicate invalid credentials, wrong base URL, or "
                    "connectivity issues. Example error: %s",
                    symbol,
                    str(e),
                )
                first_error_logged = True
            else:
                logger.debug("Ticker %s failed verification: %s", symbol, str(e))

    return verified


def _save_tickers_to_csv(tickers: List[str], filename: str = "outputs/01_SP500_Tickers_list.csv") -> None:
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    pd.DataFrame(tickers, columns=["Symbol"]).to_csv(filename, index=False)
    logger.info("Saved tickers list to %s", filename)


# ------------------ Membership Matrix ------------------ #
def build_membership_matrix(
    tickers: List[str],
    filename: str = "outputs/01_SP500_membership_matrix.csv",
    churn_rate: float = 0.02
) -> pd.DataFrame:
    """
    Build or extend a membership matrix.
    Simulates churn by randomly dropping some tickers each run.
    """
    logger.info("--- Building Membership Matrix ---")
    # Default: all tradable = 1
    membership_status = {t: 1 for t in tickers}

    # Simulate churn only when we have tickers
    dropped: List[str] = []
    if tickers:
        logger.info("Simulating churn with a rate of %.2f...", churn_rate)
        num_churn = max(1, int(len(tickers) * churn_rate))
        dropped = random.sample(tickers, num_churn)
        for d in dropped:
            membership_status[d] = 0
        logger.info("Simulated churn: %d tickers dropped today.", len(dropped))
    else:
        logger.warning(
            "Received an empty ticker list for membership matrix. "
            "Skipping churn simulation; resulting membership row will be empty."
        )

    today = pd.to_datetime(date.today())
    today_row = pd.DataFrame([membership_status], index=[today])

    if os.path.exists(filename):
        logger.info("Existing membership matrix found. Appending new data.")
        existing = pd.read_csv(filename, index_col=0, parse_dates=True)
        combined = pd.concat([existing, today_row], axis=0)
        combined = combined.reindex(columns=sorted(set(combined.columns)), fill_value=0)
    else:
        logger.info("No existing membership matrix found. Creating a new one.")
        combined = today_row

    _save_membership_matrix(combined, filename)
    logger.info("--- Membership Matrix Building Complete ---")
    return combined


def _save_membership_matrix(matrix: pd.DataFrame, filename: str) -> None:
    """
    Save membership matrix with proper Date column to avoid empty first column.
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    # Reset index and name it 'Date'
    matrix_reset = matrix.reset_index().rename(columns={'index': 'Date'})
    matrix_reset.to_csv(filename, index=False)

    logger.info("Saved membership matrix to %s with shape %s", filename, matrix.shape)


# ------------------ Main Pipeline ------------------ #
def run_pipeline() -> None:
    logger.info("====== Starting Data Loader 01: S&P 500 Tickers & Membership ======")
    tickers = fetch_sp500_tickers()
    membership_matrix = build_membership_matrix(tickers)
    logger.info("Latest Membership Status:")
    print(membership_matrix.tail())
    logger.info("====== Finished Data Loader 01 ======")


if __name__ == "__main__":
    run_pipeline()
