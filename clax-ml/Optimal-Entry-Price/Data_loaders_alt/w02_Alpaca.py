# Data_loaders_alt/w02_Alpaca.py
# -----------------------------
import os
import time
import logging
from datetime import timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi
from tqdm import tqdm

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------ API Setup (Alpaca) ------------------ #
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY", "")
API_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
BASE_URL = "https://paper-api.alpaca.markets"

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL)

# ------------------ Helpers ------------------ #
def _bars_to_frames(bars_df):
    if bars_df is None or bars_df.empty:
        return []

    frames = []
    
    # Handle MultiIndex case (symbol, date format from Alpaca)
    if isinstance(bars_df.index, pd.MultiIndex):
        for symbol, g in bars_df.groupby(level=0):
            df = g.reset_index()
            # Rename possible date column names (timestamp, index, or already 'date')
            if 'timestamp' in df.columns:
                df.rename(columns={"timestamp": "date"}, inplace=True)
            elif df.index.name == 'timestamp' or 'index' in df.columns:
                if 'index' in df.columns:
                    df.rename(columns={"index": "date"}, inplace=True)
            # If index is datetime, make it a column
            if not 'date' in df.columns and hasattr(df.index, 'name'):
                df.reset_index(inplace=True)
                for col in df.columns:
                    if pd.api.types.is_datetime64_any_dtype(df[col]):
                        df.rename(columns={col: "date"}, inplace=True)
                        break
            df["Ticker"] = symbol
            frames.append(df)
    
    # Handle symbol column case
    elif "symbol" in bars_df.columns:
        for symbol, g in bars_df.groupby("symbol"):
            df = g.copy().reset_index()
            if 'timestamp' in df.columns:
                df.rename(columns={"timestamp": "date"}, inplace=True)
            # Find any datetime column and call it 'date' if not already
            if 'date' not in df.columns:
                for col in df.columns:
                    if pd.api.types.is_datetime64_any_dtype(df[col]):
                        df.rename(columns={col: "date"}, inplace=True)
                        break
            df["Ticker"] = symbol
            frames.append(df)
    
    # Handle simple case with index as date
    else:
        df = bars_df.reset_index()
        if 'timestamp' in df.columns:
            df.rename(columns={"timestamp": "date"}, inplace=True)
        # Find any datetime column and call it 'date' if not already
        if 'date' not in df.columns:
            for col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    df.rename(columns={col: "date"}, inplace=True)
                    break
        df["Ticker"] = "UNKNOWN"
        frames.append(df)

    return frames


def _select_price_cols(df):
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    for k, v in rename_map.items():
        if k in df.columns:
            df.rename(columns={k: v}, inplace=True)
    keep = ["date", "Open", "High", "Low", "Close", "Volume", "Ticker"]
    return df[[c for c in keep if c in df.columns]]


# ------------------ Core Functions ------------------ #
def get_top_liquid_stocks(symbols, top_n=50, liquidity_days=252, batch_size=200):
    """
    Fetches volume data via Alpaca and returns the top N most liquid stocks.
    """
    logger.info("Identifying top %d most liquid stocks from %d tickers...", top_n, len(symbols))
    start_time = time.time()
    end_date = pd.Timestamp.today(tz="UTC")
    start_date = end_date - timedelta(days=liquidity_days + 50)

    avg_volumes = {s: 0 for s in symbols}

    for i in tqdm(range(0, len(symbols), batch_size), desc="Liquidity Batches"):
        batch = symbols[i:i + batch_size]
        try:
            bars = api.get_bars(
                batch,
                tradeapi.TimeFrame.Day,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                adjustment="all",
            ).df
        except Exception as e:
            logger.warning("Alpaca liquidity batch failed: %s", e)
            continue

        if bars is None or bars.empty:
            continue

        if isinstance(bars.index, pd.MultiIndex):
            for symbol, g in bars.groupby(level=0):
                if "volume" in g.columns:
                    avg_volumes[symbol] = g["volume"].mean()
        else:
            if "symbol" in bars.columns and "volume" in bars.columns:
                grouped = bars.groupby("symbol")["volume"].mean()
                for symbol, vol in grouped.items():
                    avg_volumes[symbol] = vol

        time.sleep(0.25)

    sorted_symbols = sorted(avg_volumes.items(), key=lambda item: item[1], reverse=True)
    top_liquid_symbols = [symbol for symbol, _ in sorted_symbols[:top_n]]

    logger.info("Identified Top %d Liquid Stocks (e.g., %s...) in %.2f seconds.",
                top_n, top_liquid_symbols[:5], time.time() - start_time)
    return top_liquid_symbols


def fetch_bars_alpaca(symbols, start="2015-01-01", end=None, batch_size=200):
    if end is None:
        end = pd.Timestamp.today(tz="UTC").strftime("%Y-%m-%d")

    all_frames = []
    for i in tqdm(range(0, len(symbols), batch_size), desc="Fetching Alpaca Batches"):
        batch = symbols[i:i + batch_size]
        try:
            bars = api.get_bars(
                batch,
                tradeapi.TimeFrame.Day,
                start=start,
                end=end,
                adjustment="all",
            ).df
        except Exception as e:
            logger.error("Error fetching batch %d: %s", (i // batch_size) + 1, e)
            time.sleep(1)
            continue

        if bars is None or bars.empty:
            logger.warning("Alpaca returned empty data for batch %d; skipping.", (i // batch_size) + 1)
            time.sleep(0.5)
            continue

        frames = _bars_to_frames(bars)
        for df in frames:
            df = _select_price_cols(df)
            if df is not None and not df.empty:
                all_frames.append(df)
        time.sleep(0.5)

    return all_frames


def run_pipeline():
    """
    Fetches Alpaca data for top 50 liquid S&P 500 stocks.
    Note: FRED + yfinance extras are handled separately in w02b_Extras.py
    """
    logger.info("====== Starting Data Loader 02 (Alpaca): Market Data Fetching ======")
    start_time = time.time()

    # === 1. Load S&P500 tickers from CSV ===
    logger.info("Step 1/3: Loading S&P500 tickers from CSV...")
    load_tickers_start = time.time()
    sp500_df = pd.read_csv("outputs/01_SP500_Tickers_list.csv")
    initial_sp500_symbols = sp500_df["Symbol"].tolist()
    logger.info("Loaded %d S&P500 tickers in %.2f seconds.",
                len(initial_sp500_symbols), time.time() - load_tickers_start)

    # === 2. Identify Top 50 Most Liquid Stocks ===
    logger.info("Step 2/3: Identifying Top 50 Most Liquid Stocks...")
    identify_liquid_start = time.time()
    sp500_symbols = get_top_liquid_stocks(initial_sp500_symbols)
    logger.info("Identified top liquid stocks in %.2f seconds.", time.time() - identify_liquid_start)

    # === 3. Fetch Alpaca bars for equities ===
    logger.info("Step 3/3: Fetching Alpaca bars in batches...")
    fetch_data_start = time.time()
    stock_frames = fetch_bars_alpaca(sp500_symbols)
    logger.info("Fetched Alpaca data in %.2f seconds.", time.time() - fetch_data_start)

    # === 4. Save Alpaca stock data ===
    logger.info("Saving Alpaca stock data to CSV files...")
    save_csv_start = time.time()
    Path("outputs").mkdir(parents=True, exist_ok=True)

    if stock_frames:
        stocks_df = pd.concat(stock_frames, axis=0)
        if stocks_df is None or stocks_df.empty:
            logger.error("Stocks DataFrame is empty; not saving outputs/02_Yahoo_Stocks.csv.")
        else:
            stocks_df.to_csv("outputs/02_Yahoo_Stocks.csv", index=False)
            logger.info("Saved Stocks CSV with shape %s", stocks_df.shape)

        # --- Save Top 50 universe by 20-day avg dollar volume ---
        try:
            if stocks_df is None or stocks_df.empty:
                raise ValueError("Stocks DataFrame is empty; cannot compute Top 50 universe.")
            stocks_df["DollarVolume"] = stocks_df["Volume"] * stocks_df["Close"]
            latest_date = stocks_df["date"].max()
            recent_dates = sorted(stocks_df["date"].unique(), reverse=True)[:20]
            recent_data = stocks_df[stocks_df["date"].isin(recent_dates)].copy()

            if recent_data.empty:
                logger.warning("No recent data available to compute Top 50 universe.")
            else:
                avg_dollar_volumes = (
                    recent_data.groupby("Ticker")["DollarVolume"]
                    .mean()
                    .reset_index()
                    .rename(columns={"DollarVolume": "AvgDollarVolume"})
                )
                top_50 = avg_dollar_volumes.nlargest(50, "AvgDollarVolume")
                top_50["Date"] = latest_date
                top_50 = top_50[["Date", "Ticker", "AvgDollarVolume"]]
                top_50.to_csv("outputs/02_top50_universe.csv", index=False)
                logger.info("Saved Top 50 universe to outputs/02_top50_universe.csv with %d tickers.", len(top_50))
        except Exception as e:
            logger.warning("Failed to compute/save Top 50 universe: %s", e)
    else:
        logger.error("No stock data to save (all Alpaca downloads failed or returned empty).")

    if not stock_frames:
        logger.warning("No Alpaca stock data fetched or saved in this run!")
    
    logger.info("Saved Alpaca CSVs in %.2f seconds.", time.time() - save_csv_start)
    logger.info("====== Alpaca data fetching pipeline completed in %.2f seconds. ======", time.time() - start_time)
    logger.info("Note: Run w02b_Extras.py separately to fetch FRED + yfinance extras data.")


if __name__ == "__main__":
    run_pipeline()
