# Data_loaders_alt/w02b_Extras.py
# Fetches extra financial data: FX pairs, Treasury yields, and commodities from FRED + indices from yfinance
# ======================================

import os
import time
import logging
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from pandas_datareader import data as pdr
from tqdm import tqdm

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------ API Setup (FRED) ------------------ #
load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
logger.info(f"FRED_API_KEY loaded: {'YES' if FRED_API_KEY else 'NO'}")


# ========== FRED Functions ==========
def fetch_fred_series(fred_series_mapping, start="2015-01-01", end=None, invert_series=None):
    """
    Fetches FRED (Federal Reserve Economic Data) series for economic indicators and FX.
    
    Args:
        fred_series_mapping: Dict mapping display names to FRED series codes
                              e.g., {"10Y_Yield": "GS10", "EURUSD": "DEXUSEU"}
        start: Start date (default: "2015-01-01")
        end: End date (default: today)
        invert_series: Set of display names to invert (1/value) for FX pairs
                       e.g., {"USDJPY", "USDCAD"} for inverted rates
    
    Returns:
        List of DataFrames ready for concatenation, formatted like equities
    """
    if not FRED_API_KEY:
        logger.warning("FRED_API_KEY not configured; skipping FRED data.")
        return []
    
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")
    
    if invert_series is None:
        invert_series = set()
    
    logger.info(f"Fetching FRED data from {start} to {end}...")
    frames = []
    
    for display_name, series_code in tqdm(fred_series_mapping.items(), desc="Fetching FRED Series"):
        try:
            logger.info(f"   -> Fetching {display_name} ({series_code})...")
            series = pdr.DataReader(
                series_code, 
                "fred", 
                start=start, 
                end=end, 
                api_key=FRED_API_KEY
            )
            series.index = pd.to_datetime(series.index)
            series = series.reset_index()
            series.columns = ["date", "Value"]
            series["date"] = series["date"].dt.strftime("%Y-%m-%d")
            
            # Handle inverted FX rates (convert from foreign/USD to USD/foreign)
            if display_name in invert_series:
                series["Value"] = 1.0 / series["Value"]
                logger.info(f"     Inverted {display_name} (converted to USD/foreign format)")
            
            # Format to match equity structure (Open, High, Low, Close)
            series["Open"] = series["Value"]
            series["High"] = series["Value"]
            series["Low"] = series["Value"]
            series["Close"] = series["Value"]
            series["Volume"] = 0  # FRED data doesn't have volume
            series["Ticker"] = display_name
            
            keep = ["date", "Open", "High", "Low", "Close", "Volume", "Ticker"]
            df = series[[c for c in keep if c in series.columns]]
            frames.append(df)
            
            logger.info(f"     OK {display_name}: {len(df)} rows fetched.")
        except Exception as e:
            logger.error(f"     X {display_name} ({series_code}) failed: {e}")
    
    return frames


# ========== yfinance Functions ==========
def fetch_yfinance_indices(symbols, start="2015-01-01", end=None, max_retries=2, base_sleep=3):
    """
    Fetches stock indices from yfinance (S&P 500, VIX, etc.)
    
    Args:
        symbols: List of yfinance ticker symbols (e.g., ["^GSPC", "^VIX"])
        start: Start date (default: "2015-01-01")
        end: End date (default: today)
        max_retries: Maximum retry attempts per symbol
        base_sleep: Base sleep time between retries
    
    Returns:
        List of DataFrames ready for concatenation, formatted like equities
    """
    try:
        import yfinance as yf
    except Exception:
        logger.warning("yfinance not available; skipping yfinance indices.")
        return []

    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")

    frames = []
    for sym in tqdm(symbols, desc="Fetching yfinance Indices"):
        df = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"   -> Downloading {sym} (attempt {attempt}/{max_retries})...")
                # Add timeout handling for yfinance
                df = yf.download(
                    sym, 
                    start=start, 
                    end=end, 
                    auto_adjust=True, 
                    progress=False,
                    timeout=30  # 30-second timeout
                )
            except Exception as e:
                logger.warning("Failed to fetch %s (attempt %d/%d): %s", sym, attempt, max_retries, str(e)[:100])
                if attempt < max_retries:
                    time.sleep(base_sleep * attempt)
                continue

            if df is None or df.empty:
                logger.warning("Empty data for %s (attempt %d/%d).", sym, attempt, max_retries)
                if attempt < max_retries:
                    time.sleep(base_sleep * attempt)
                df = None
                continue

            break

        if df is None or df.empty:
            logger.warning("Skipping %s after %d attempts.", sym, max_retries)
            time.sleep(1)
            continue

        try:
            df = df.reset_index().rename(columns={"Date": "date"})
            df["Ticker"] = sym
            keep = ["date", "Open", "High", "Low", "Close", "Volume", "Ticker"]
            df = df[[c for c in keep if c in df.columns]]
            frames.append(df)
            logger.info(f"     OK {sym}: {len(df)} rows fetched.")
        except Exception as e:
            logger.error(f"     X Failed to process {sym}: {e}")
        
        time.sleep(1)
    
    return frames


def fetch_yfinance_gold(ticker="GC=F", start="2015-01-01", end=None, max_retries=2):
    """
    Fetches gold futures data from yfinance.
    
    Args:
        ticker: yfinance ticker (default: GC=F for gold futures)
        start: Start date (default: "2015-01-01")
        end: End date (default: today)
        max_retries: Maximum retry attempts
    
    Returns:
        List containing single DataFrame, formatted like equities, or empty list if failed
    """
    try:
        import yfinance as yf
    except Exception:
        logger.warning("yfinance not available; skipping gold data.")
        return []

    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"   -> Fetching {ticker} (attempt {attempt}/{max_retries})...")
            df = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                timeout=15  # 15-second timeout
            )
            
            if df is None or df.empty:
                logger.warning(f"Empty data for {ticker} (attempt {attempt}/{max_retries}).")
                time.sleep(2 * attempt)
                continue
            
            # Format to match equity structure
            df = df.reset_index().rename(columns={"Date": "date"})
            
            # Handle MultiIndex columns from yfinance (flatten to single-level)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            
            df["Ticker"] = "Gold"
            keep = ["date", "Open", "High", "Low", "Close", "Volume", "Ticker"]
            df = df[[c for c in keep if c in df.columns]]
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            
            logger.info(f"     OK Gold: {len(df)} rows fetched.")
            return [df]
            
        except Exception as e:
            logger.warning(f"Failed to fetch {ticker} (attempt {attempt}/{max_retries}): {str(e)[:100]}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
            continue
    
    logger.warning(f"Skipping Gold after {max_retries} attempts.")
    return []


# ========== Save Functions ==========
def save_extras_data(df, filename="outputs/02_Extras.csv"):
    """Save extras data to CSV."""
    logger.info(f"Saving extras to {filename}...")
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    df.to_csv(filename, index=False)
    logger.info(f"Saved extras CSV with shape {df.shape} to {filename}")


# ========== Main Pipeline ==========
def run_pipeline():
    """
    Fetches and saves extra financial data: FX pairs, yields, commodities, and indices.
    """
    logger.info("====== Starting Data Loader 02b (Extras): Fetching FRED + yfinance ======")
    start_time = time.time()

    # === 1. Define FRED series ===
    logger.info("Step 1/3: Preparing FRED data sources...")
    fred_series = {
        # ========== FX Pairs (11 total) ==========
        # Standard format (USD/Foreign)
        "EURUSD": "DEXUSEU",      # USD to Euro
        "GBPUSD": "DEXUSUK",      # USD to GBP
        "AUDUSD": "DEXUSAL",      # USD to AUD
        "NZDUSD": "DEXUSNZ",      # USD to NZD
        # Inverted format (Foreign/USD - need inversion)
        "USDJPY": "DEXJPUS",      # JPY to USD → invert to USD/JPY
        "USDCAD": "DEXCAUS",      # CAD to USD → invert to USD/CAD
        "USDCHF": "DEXSZUS",      # CHF to USD → invert to USD/CHF
        "USDNOK": "DEXNOUS",      # NOK to USD → invert to USD/NOK
        "SEKUSD": "DEXSDUS",      # SEK to USD → invert to USD/SEK
        "DKKUSD": "DEXDNUS",      # DKK to USD → invert to USD/DKK
        "CNYUSD": "DEXCHUS",      # CNY to USD → invert to USD/CNY
        # ========== Treasury Yields (3 total) ==========
        "10Y_Yield": "GS10",
        "5Y_Yield": "DGS5",
        "2Y_Yield": "DGS2",
        # ========== Commodities (2 total - gold removed due to data discontinuation) ==========
        "WTI_Oil": "DCOILWTICO",       # West Texas Intermediate Crude Oil
        "Brent_Oil": "DCOILBRENTEU",   # Brent Crude Oil
        # ========== Stock Indices & Volatility (via FRED) ==========
        "SP500": "SP500",              # S&P 500 Index
        "VIX": "VIXCLS",               # CBOE Volatility Index
    }
    
    # Series that need inversion (from foreign/USD to USD/foreign)
    invert_fx_pairs = {"USDJPY", "USDCAD", "USDCHF", "USDNOK", "SEKUSD", "DKKUSD", "CNYUSD"}

    # === 2. Define yfinance indices (optional - most data via FRED) ===
    logger.info("Step 2/4: Preparing yfinance gold futures...")
    # yfinance_symbols removed - S&P 500 & VIX now fetched via FRED (more reliable)

    # === 3. Fetch FRED data (all data via FRED for reliability) ===
    logger.info("Step 3/4: Fetching FRED series (FX, yields, commodities, indices, VIX)...")
    fred_frames = fetch_fred_series(fred_series, invert_series=invert_fx_pairs)

    # === 4. Fetch Gold from yfinance ===
    logger.info("Step 4/4: Fetching Gold futures from yfinance...")
    gold_frames = fetch_yfinance_gold(ticker="GC=F")

    # === 5. Combine and save ===
    logger.info("Combining FRED and yfinance data...")
    all_frames = fred_frames + gold_frames

    if all_frames:
        extras_df = pd.concat(all_frames, axis=0, ignore_index=True)
        extras_df = extras_df.sort_values("date").reset_index(drop=True)
        
        if extras_df is None or extras_df.empty:
            logger.error("Combined extras DataFrame is empty; not saving.")
        else:
            save_extras_data(extras_df)
            fred_count = len(fred_frames)
            gold_count = len(gold_frames)
            total_count = fred_count + gold_count
            logger.info(f"Combined extras data: {total_count} series (FRED: {fred_count}, yfinance: {gold_count}), {extras_df.shape[0]} total rows")
    else:
        logger.warning("No extras data fetched or combined.")

    logger.info("====== Finished Data Loader 02b (Extras) in %.2f seconds ======", time.time() - start_time)


if __name__ == "__main__":
    run_pipeline()
