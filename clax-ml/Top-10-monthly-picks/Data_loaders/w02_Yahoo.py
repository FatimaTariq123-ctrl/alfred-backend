# Data_loaders/w02_Yahoo.py
# --------------------
import os
import time
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import timedelta
import logging
from tqdm import tqdm

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

def _normalize_yahoo_symbol(symbol: str) -> str:
    """
    Normalize symbols for Yahoo Finance.

    Examples:
    - BRK-B -> BRK.B
    - BF-B  -> BF.B

    Keeps non-equity symbols (indices, FX, futures) unchanged.
    """
    if not isinstance(symbol, str):
        return symbol
    # Leave indices, FX pairs, and futures untouched
    if symbol.startswith("^") or "=" in symbol:
        return symbol
    return symbol.replace("-", ".")

def run_pipeline():
    """
    Fetches Yahoo Finance data for top 50 liquid S&P 500 stocks and extra symbols.
    """
    logger.info("====== Starting Data Loader 02: Yahoo Finance Data Fetching ======")
    start_time = time.time()

    # === 1. Load S&P500 tickers from CSV ===
    logger.info("Step 1/6: Loading S&P500 tickers from CSV...")
    load_tickers_start = time.time()
    sp500_df = pd.read_csv("outputs/01_SP500_Tickers_list.csv")
    initial_sp500_symbols = sp500_df['Symbol'].tolist()
    logger.info(f"Loaded {len(initial_sp500_symbols)} S&P500 tickers in {time.time() - load_tickers_start:.2f} seconds.")

    # Normalize for Yahoo (S&P list is often Alpaca-style: BRK-B, BF-B)
    initial_sp500_symbols = [_normalize_yahoo_symbol(s) for s in initial_sp500_symbols]

    # === 2. Identify Top 50 Most Liquid Stocks ===
    logger.info("Step 2/6: Identifying Top 50 Most Liquid Stocks...")
    identify_liquid_start = time.time()
    sp500_symbols = get_top_liquid_stocks(initial_sp500_symbols)
    logger.info(f"Identified top liquid stocks in {time.time() - identify_liquid_start:.2f} seconds.")

    # === 3. Default extra symbols (FX, indices, yields, commodities) ===
    logger.info("Step 3/6: Preparing extra symbols for fetching.")
    extra_symbols = [
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X",
        "USDCAD=X", "USDCHF=X", "NZDUSD=X", "USDNOK=X",
        "USDSEK=X", "USDDKK=X", "USDCNY=X",
        "^GSPC", "^VIX",
        "^TNX", "^FVX", "^IRX",
        "CL=F", "GC=F"
    ]

    # Merge all symbols for fetching
    symbols = sp500_symbols + extra_symbols
    # Normalize equities again defensively (extras should remain unchanged)
    symbols = [_normalize_yahoo_symbol(s) for s in symbols]
    logger.info(f"Total symbols to fetch: {len(symbols)}")

    # === 4. Fetch Yahoo Finance data in batches ===
    logger.info("Step 4/6: Fetching Yahoo Finance data in batches...")
    fetch_data_start = time.time()
    data_batches = fetch_data(symbols)
    logger.info(f"Fetched Yahoo Finance data in {time.time() - fetch_data_start:.2f} seconds.")

    # === 5. Reformat into separate DataFrames ===
    logger.info("Step 5/6: Reformatting data into separate DataFrames...")
    reformat_data_start = time.time()
    stock_frames = []
    extra_frames = []

    for sym in tqdm(symbols, desc="Reformatting Data"):
        frames = []
        for batch_df in data_batches:
            if batch_df is None or getattr(batch_df, "empty", True):
                continue
            if isinstance(batch_df.columns, pd.MultiIndex):
                if sym in batch_df.columns.get_level_values(0):
                    symbol_data = batch_df[sym].copy()
                    symbol_data.columns = symbol_data.columns.droplevel(0) if symbol_data.columns.nlevels > 1 else symbol_data.columns
                    frames.append(symbol_data)
            elif sym in batch_df.columns:
                 frames.append(batch_df[[sym]])

        if frames:
            df = pd.concat(frames)
            if df is None or df.empty:
                logger.warning("⚠️ Yahoo returned empty data for %s; skipping.", sym)
                continue
            df["Ticker"] = sym
            df = df.reset_index().rename(columns={"Date":"date"})
            if sym in sp500_symbols:
                stock_frames.append(df)
            else:
                extra_frames.append(df)
    logger.info(f"Reformatted data into separate DataFrames in {time.time() - reformat_data_start:.2f} seconds.")

    # === 6. Save separate CSVs ===
    logger.info("Step 6/6: Saving data to CSV files...")
    save_csv_start = time.time()
    Path("outputs").mkdir(parents=True, exist_ok=True)

    if stock_frames:
        stocks_df = pd.concat(stock_frames, axis=0)
        if stocks_df is None or stocks_df.empty:
            logger.error("❌ Stocks DataFrame is empty; not saving outputs/02_Yahoo_Stocks.csv.")
        else:
            stocks_df.to_csv("outputs/02_Yahoo_Stocks.csv", index=False)
            logger.info(f"✅ Saved Stocks CSV with shape {stocks_df.shape}")

        # --- Save Top 50 universe by 20-day avg dollar volume ---
        try:
            if stocks_df is None or stocks_df.empty:
                raise ValueError("Stocks DataFrame is empty; cannot compute Top 50 universe.")
            stocks_df["DollarVolume"] = stocks_df["Volume"] * stocks_df["Close"]
            latest_date = stocks_df["date"].max()
            recent_dates = sorted(stocks_df["date"].unique(), reverse=True)[:20]
            recent_data = stocks_df[stocks_df["date"].isin(recent_dates)].copy()

            if recent_data.empty:
                logger.warning("⚠️ No recent data available to compute Top 50 universe.")
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
                logger.info(f"✅ Saved Top 50 universe to outputs/02_top50_universe.csv with {len(top_50)} tickers.")
        except Exception as e:
            logger.warning(f"⚠️ Failed to compute/save Top 50 universe: {e}")
    else:
        logger.error("❌ No stock data to save (all Yahoo downloads failed or returned empty).")

    if extra_frames:
        extras_df = pd.concat(extra_frames, axis=0)
        if extras_df is None or extras_df.empty:
            logger.error("❌ Extras DataFrame is empty; not saving outputs/02_Yahoo_Extras.csv.")
        else:
            extras_df.to_csv("outputs/02_Yahoo_Extras.csv", index=False)
            logger.info(f"✅ Saved Extras CSV with shape {extras_df.shape}")
    else:
        logger.warning("❌ No extra data to save.")

    if not stock_frames and not extra_frames:
        logger.warning("❌ No data fetched or saved in this run!")
    logger.info(f"Saved CSVs in {time.time() - save_csv_start:.2f} seconds.")
    logger.info(f"====== Yahoo Finance data fetching pipeline completed in {time.time() - start_time:.2f} seconds. ======")

def get_top_liquid_stocks(symbols, top_n=50, liquidity_days=252):
    """
    Fetches volume data and returns the top N most liquid stocks.
    """
    logger.info(f"Identifying top {top_n} most liquid stocks from {len(symbols)} tickers...")
    start_time = time.time()
    end_date = pd.Timestamp.today()
    start_date = end_date - timedelta(days=liquidity_days + 50) # Fetch a bit more for buffer

    # Fetch volume data for all symbols
    fetch_volume_start = time.time()
    logger.info(f"Downloading volume data for {len(symbols)} symbols...")
    all_volume_data = None
    try:
        all_volume_data = yf.download(
            symbols,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=True # Set to True to see yfinance's internal progress
        )
    except Exception as e:
        logger.warning("⚠️ yfinance liquidity download failed: %s", e)
    logger.info(f"Finished downloading volume data in {time.time() - fetch_volume_start:.2f} seconds.")

    if all_volume_data is None or all_volume_data.empty:
        logger.warning("⚠️ Could not fetch volume data for liquidity check. Using original list (first %d).", top_n)
        return symbols[:top_n]

    # Calculate average volume for each stock
    calculate_avg_volume_start = time.time()
    logger.info("Calculating average volumes...")
    avg_volumes = {}
    for symbol in tqdm(symbols, desc="Calculating Avg Volume"):
        try:
            # Handle both single and multi-level column structures
            if isinstance(all_volume_data.columns, pd.MultiIndex):
                symbol_data = all_volume_data[symbol]
            else:
                # If only one symbol was fetched, columns are not multi-indexed
                symbol_data = all_volume_data if len(symbols) == 1 else all_volume_data.xs(symbol, level=1, axis=1)

            if symbol_data is None or symbol_data.empty:
                logger.warning("⚠️ No volume data for %s during liquidity check; treating as 0.", symbol)
                avg_volumes[symbol] = 0
            elif 'Volume' in symbol_data.columns:
                # Calculate average daily volume over the last year
                avg_volumes[symbol] = symbol_data['Volume'].mean()
            else:
                logger.warning("⚠️ Missing Volume column for %s during liquidity check; treating as 0.", symbol)
                avg_volumes[symbol] = 0
        except (KeyError, IndexError):
            logger.debug(f"Could not process volume for {symbol}. It might be delisted or have no data.")
            avg_volumes[symbol] = 0
    logger.info(f"Calculated average volumes in {time.time() - calculate_avg_volume_start:.2f} seconds.")

    # Sort by volume and get top N
    sorted_symbols = sorted(avg_volumes.items(), key=lambda item: item[1], reverse=True)
    top_liquid_symbols = [symbol for symbol, volume in sorted_symbols[:top_n]]

    logger.info(f"✅ Identified Top {top_n} Liquid Stocks (e.g., {top_liquid_symbols[:5]}...) in {time.time() - start_time:.2f} seconds.")
    return top_liquid_symbols

def fetch_data(symbols, start="2015-01-01", end=None, batch_size=50):
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    all_data = []
    num_batches = (len(symbols) + batch_size - 1) // batch_size
    for i in tqdm(range(0, len(symbols), batch_size), desc="Fetching Data Batches"):
        batch_start_time = time.time()
        batch = symbols[i:i+batch_size]
        # logger.info(f"Fetching batch {i//batch_size+1}/{num_batches} with {len(batch)} tickers...") # TQDM handles this visually
        try:
            df = yf.download(
                batch, start=start, end=end, group_by="ticker",
                auto_adjust=True, threads=True, progress=False # Let tqdm handle overall progress
            )
            if df is None or df.empty:
                logger.warning(
                    "⚠️ yfinance returned empty data for batch %d/%d; skipping this batch.",
                    (i // batch_size) + 1,
                    num_batches,
                )
            else:
                all_data.append(df)
            # logger.info(f"Batch {i//batch_size+1} fetched in {time.time() - batch_start_time:.2f} seconds.")
        except Exception as e:
            logger.error(f"Error fetching batch {i//batch_size+1}: {e}")
        time.sleep(1) # Be respectful to the API
    return all_data

if __name__ == "__main__":
    run_pipeline()
