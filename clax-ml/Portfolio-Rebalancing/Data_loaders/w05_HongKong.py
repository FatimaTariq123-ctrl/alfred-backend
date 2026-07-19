# Data_loaders/w05_HongKong.py
# --------------------
import os
import time
import pandas as pd
import yfinance as yf
from pathlib import Path
import logging
from tqdm import tqdm

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------ Constants ------------------ #
HONGKONG_SYMBOLS = [
    "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK",
    "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0027.HK",
    "0066.HK", "0083.HK", "0101.HK", "0175.HK", "0232.HK",
    "0267.HK", "0386.HK", "0388.HK", "0669.HK", "0688.HK",
    "0700.HK", "0857.HK", "0883.HK", "0939.HK", "0941.HK",
    "0960.HK", "0968.HK", "0981.HK", "0992.HK", "1038.HK",
    "1088.HK", "1093.HK", "1109.HK", "1113.HK", "1177.HK",
    "1288.HK", "1299.HK", "1336.HK", "1339.HK", "1359.HK",
    "1398.HK", "1810.HK", "1876.HK", "1928.HK", "1929.HK",
    "1997.HK", "2007.HK", "2018.HK", "2269.HK", "2313.HK",
    "2318.HK", "2319.HK", "2331.HK", "2382.HK", "2388.HK",
    "2628.HK", "2688.HK", "2899.HK", "3328.HK", "3690.HK",
    "3968.HK", "3988.HK", "6881.HK"
]

OUTPUT_PATH = "outputs/05_HongKong_OHLCV.csv"

def fetch_data(symbols, start="2015-01-01", end=None, batch_size=50):
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    all_data = []
    failed_tickers = []

    # ---------------- Batch Download ---------------- #
    for i in tqdm(range(0, len(symbols), batch_size), desc="Fetching Hong Kong Data Batches"):
        batch = symbols[i:i+batch_size]
        try:
            df = yf.download(
                batch, start=start, end=end, group_by="ticker",
                auto_adjust=True, threads=True, progress=False
            )
            if df is not None and not df.empty:
                all_data.append(df)
        except Exception as e:
            logger.error(f"Error fetching batch {i//batch_size+1}: {e}")
            failed_tickers.extend(batch)
        time.sleep(1)

    # ---------------- Retry Failed Tickers Individually ---------------- #
    if failed_tickers:
        logger.info(f"Retrying {len(failed_tickers)} failed tickers individually...")
        for ticker in failed_tickers:
            try:
                df = yf.download(
                    ticker, start=start, end=end,
                    auto_adjust=True, progress=False
                )
                if df is not None and not df.empty:
                    # Wrap single-ticker DataFrame in a MultiIndex format
                    df.columns = pd.MultiIndex.from_product([[ticker], df.columns])
                    all_data.append(df)
                    logger.info(f"✅ Successfully fetched {ticker} on retry")
                else:
                    logger.warning(f"❌ No data found for {ticker} on retry")
            except Exception as e:
                logger.error(f"❌ Failed to fetch {ticker} on retry: {e}")
            time.sleep(1)

    return all_data

def run_pipeline():
    logger.info("====== Starting Data Loader 05: Hong Kong Stock Data Fetching ======")
    start_time = time.time()

    symbols = HONGKONG_SYMBOLS
    logger.info(f"Fetching data for {len(symbols)} Hong Kong stocks...")

    # Fetch data
    data_batches = fetch_data(symbols)
    logger.info(f"Fetched data in batches (including retries).")

    # Reformat into DataFrame
    frames = []
    for sym in tqdm(symbols, desc="Reformatting Data"):
        symbol_frames = []
        for batch_df in data_batches:
            if batch_df is None or getattr(batch_df, "empty", True):
                continue
            if isinstance(batch_df.columns, pd.MultiIndex):
                if sym in batch_df.columns.get_level_values(0):
                    symbol_data = batch_df[sym].copy()
                    symbol_data.columns = symbol_data.columns.droplevel(0) if symbol_data.columns.nlevels > 1 else symbol_data.columns
                    symbol_frames.append(symbol_data)
            elif sym in batch_df.columns:
                symbol_frames.append(batch_df[[sym]])

        if symbol_frames:
            df = pd.concat(symbol_frames)
            if df is not None and not df.empty:
                df["Ticker"] = sym
                df = df.reset_index().rename(columns={"Date": "date"})
                frames.append(df)

    if frames:
        hk_df = pd.concat(frames, axis=0)
        hk_df = hk_df.sort_values(["Ticker", "date"])
        Path("outputs").mkdir(parents=True, exist_ok=True)
        hk_df.to_csv(OUTPUT_PATH, index=False)
        logger.info(f"✅ Saved Hong Kong data to {OUTPUT_PATH} with shape {hk_df.shape}")
    else:
        logger.error("❌ No data fetched for Hong Kong stocks.")

    logger.info(f"Total time: {time.time() - start_time:.2f} seconds.")

if __name__ == "__main__":
    run_pipeline()
