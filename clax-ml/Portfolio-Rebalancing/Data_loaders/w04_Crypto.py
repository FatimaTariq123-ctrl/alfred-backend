# Data_loaders/w04_Crypto.py
"""Crypto Data Loader - Alpaca API

Fetches daily OHLCV data for a crypto universe from Alpaca and saves a clean
CSV aligned with US stock market trading days (Mon-Fri, excluding US holidays).

This file is designed to be dropped into the existing pipeline and run as:

    python -m Data_loaders.w04_Crypto

The output is intended to feed into the feature engineering pipeline.
"""

import os
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ------------------ Logging Setup ------------------ #
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------ Environment / Config ------------------ #
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

CRYPTO_SYMBOLS = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "ADA/USD",
    "XRP/USD",
    "DOGE/USD",
]

OUTPUT_PATH = "outputs/04_Crypto_OHLCV.csv"

# ------------------ Helpers ------------------ #

def validate_api_keys():
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise ValueError(
            "Missing Alpaca API credentials.\n"
            "Please set ALPACA_API_KEY and ALPACA_SECRET_KEY in your .env file."
        )
    logger.info(" Alpaca API credentials found.")


def get_stock_date_range(stock_csv_path: str = "outputs/02_Yahoo_Stocks.csv"):
    """Return the date range covered by the existing stock price dataset."""
    try:
        df = pd.read_csv(stock_csv_path)
        # Handle both 'Date' and 'date' columns
        date_col = 'Date' if 'Date' in df.columns else 'date'
        df[date_col] = pd.to_datetime(df[date_col])
        start = df[date_col].min()
        end = df[date_col].max()
        logger.info(f"✅ Stock date range: {start.date()} → {end.date()}")
        return start, end
    except FileNotFoundError:
        logger.warning(
            "⚠️ Stock price file not found (%s). Falling back to 1-year range.", stock_csv_path
        )
        end = pd.Timestamp.now()
        start = end - timedelta(days=365)
        logger.info(f"📅 Default date range: {start.date()} → {end.date()}")
        return start, end


def get_stock_trading_dates(stock_csv_path: str = "outputs/02_Yahoo_Stocks.csv") -> pd.DatetimeIndex:
    """Return the set of trading dates present in the stock price dataset."""
    try:
        df = pd.read_csv(stock_csv_path)
        # Handle both 'Date' and 'date' columns
        date_col = 'Date' if 'Date' in df.columns else 'date'
        dates = pd.to_datetime(df[date_col]).dt.floor("D")
        dates = dates.dropna().unique()
        dates = pd.DatetimeIndex(dates).sort_values()
        logger.info(f"📅 Found {len(dates)} trading dates from stock data")
        return dates
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Stock price file not found: {stock_csv_path}. Cannot align crypto to stock trading days."
        )


def fetch_crypto_bars(client, symbol: str, start: datetime, end: datetime) -> pd.DataFrame | None:
    """Fetch crypto bars for a single symbol using the Alpaca data API."""
    try:
        # Alpaca API expects date strings in YYYY-MM-DD format
        start_str = start.strftime("%Y-%m-%d") if isinstance(start, datetime) else str(start)
        end_str = end.strftime("%Y-%m-%d") if isinstance(end, datetime) else str(end)

        logger.info(f"Fetching {symbol} from {start_str} to {end_str}...")

        # Use the new Alpaca data API call if available (alpaca-trade-api >= 3.0)
        # The REST client supports get_crypto_bars() on most recent versions.
        bars = client.get_crypto_bars(
            symbol,
            tradeapi.TimeFrame.Day,
            start=start_str,
            end=end_str,
        )

        df = bars.df.reset_index()
        if df.empty:
            logger.warning("No bars returned for %s", symbol)
            return None

        # Alpaca uses timestamp timezone-aware; normalize to date only
        df = df.rename(columns={"timestamp": "Date"})
        df["Date"] = pd.to_datetime(df["Date"]).dt.floor("D")
        df["Crypto"] = symbol

        return df

    except Exception as e:
        logger.error("Failed to fetch %s: %s", symbol, e)
        return None


def filter_crypto_to_trading_days(
    df: pd.DataFrame,
    stock_trading_dates: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Filter crypto data to stock market trading days.

    If `stock_trading_dates` is provided, we align crypto rows to those exact dates.
    Otherwise, we fall back to a simple Mon-Fri + US federal holidays filter.
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.floor("D")

    # Remove timezone info (convert to UTC naive) to match stock dates
    if df["Date"].dt.tz is not None:
        df["Date"] = df["Date"].dt.tz_localize(None)

    if stock_trading_dates is not None:
        # Ensure stock trading dates are also timezone-naive for comparison
        stock_trading_dates = pd.to_datetime(stock_trading_dates).floor("D")
        if stock_trading_dates.tz is not None:
            stock_trading_dates = stock_trading_dates.tz_localize(None)

        before = len(df)
        # Use isin() to align crypto to stock trading dates
        df = df[df["Date"].isin(stock_trading_dates)]
        after = len(df)
        logger.info(
            "Filtered crypto to stock trading dates: %d → %d rows (removed %d non-trading rows)",
            before,
            after,
            before - after,
        )
        return df

    # Fallback: business days excluding US federal holidays.
    df["Weekday"] = df["Date"].dt.weekday
    cal = USFederalHolidayCalendar()
    holidays = cal.holidays(start=df["Date"].min(), end=df["Date"].max())

    before = len(df)
    df = df[(df["Weekday"] < 5) & (~df["Date"].isin(holidays))]
    after = len(df)

    logger.info(
        "Filtered crypto to trading days: %d → %d rows (removed %d weekend/holiday rows)",
        before,
        after,
        before - after,
    )

    return df.drop(columns=["Weekday"])


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize crypto DF to consistent columns for downstream pipeline."""
    if df is None or df.empty:
        return df

    # Alpaca returns open/high/low/close/volume names at times.
    # Ensure we have a consistent schema for later pipeline steps.
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })

    # Ensure we have the columns we need (Date, Crypto, Open, High, Low, Close, Volume)
    cols = ["Date", "Crypto", "Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns after standardization: {missing}")

    return df[cols].copy()


def run_pipeline(
    output_path: str = OUTPUT_PATH,
    symbols: list[str] | None = None,
    stock_csv_path: str = "outputs/02_Yahoo_Stocks.csv",
):
    """Main entrypoint to fetch crypto OHLCV and save aligned CSV."""
    validate_api_keys()

    symbols = symbols or CRYPTO_SYMBOLS
    start_date, end_date = get_stock_date_range(stock_csv_path=stock_csv_path)

    # Alpaca REST client (for both market data and assets)
    client = tradeapi.REST(
        ALPACA_API_KEY,
        ALPACA_SECRET_KEY,
        ALPACA_BASE_URL,
        api_version="v2",
    )

    all_dfs = []
    for symbol in symbols:
        df = fetch_crypto_bars(client, symbol, start_date, end_date)
        if df is None or df.empty:
            continue
        df = standardize_columns(df)
        all_dfs.append(df)
        time.sleep(0.2)  # polite pacing for the API

    if not all_dfs:
        raise RuntimeError("No crypto data was fetched. Check your Alpaca credentials and permissions.")

    crypto_df = pd.concat(all_dfs, axis=0, ignore_index=True)

    # Align crypto to the stock trading calendar so both datasets end on Fridays
    # and share a common set of trading dates.
    stock_dates = get_stock_trading_dates(stock_csv_path=stock_csv_path)
    crypto_df = filter_crypto_to_trading_days(crypto_df, stock_trading_dates=stock_dates)

    # Sort and save
    crypto_df = crypto_df.sort_values(["Crypto", "Date"]).reset_index(drop=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    crypto_df.to_csv(output_path, index=False)
    logger.info("Saved crypto OHLCV to %s (shape=%s)", output_path, crypto_df.shape)

    return crypto_df


if __name__ == "__main__":
    run_pipeline()