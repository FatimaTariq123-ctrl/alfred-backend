#Data_loaders/w03_Fred.py
# --------------------
#These affect all stocks equally on a given date, so when merged, you repeat them for each ticker.
import os
import pandas as pd
from pandas_datareader import data as pdr
from dotenv import load_dotenv
import logging
from tqdm import tqdm

# ------------------ Logging Setup ------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")
logger.info(f"FRED_API_KEY loaded: {'YES' if FRED_API_KEY else 'NO'}")

# ---------------- Utility ---------------- #
def _print_data_summary(df):
    logger.info(f"Shape: {df.shape}")
    logger.info(f"Date range: {df['Date'].min().date()} -> {df['Date'].max().date()}")

# ---------------- Fetching ---------------- #
def fetch_fred_series(series_mapping, start="2015-01-01"):
    logger.info(f"Starting to fetch FRED series from {start}...")
    merged_df = None

    for name, code in tqdm(series_mapping.items(), desc="Fetching FRED Series"):
        try:
            logger.info(f"   -> Fetching {name} ({code})...")
            series = pdr.DataReader(code, "fred", start=start, api_key=FRED_API_KEY)
            series.index = pd.to_datetime(series.index)
            series = series.rename(columns={code: name}).reset_index()
            if merged_df is None:
                merged_df = series
            else:
                merged_df = pd.merge(merged_df, series, on="DATE", how="outer")
            logger.info(f"     OK {name}: {series.shape[0]} rows fetched.")
        except Exception as e:
            logger.error(f"     X {name} ({code}) failed: {e}")

    if merged_df is None or merged_df.empty:
        raise RuntimeError("No FRED data fetched. Check API key or series codes.")

    merged_df.rename(columns={"DATE": "Date"}, inplace=True)
    merged_df = merged_df.sort_values("Date").reset_index(drop=True)
    logger.info("FRED data fetching complete.")
    _print_data_summary(merged_df)
    return merged_df

# ---------------- Save ---------------- #
def save_fred_data(df, filename="outputs/03_fred_features.csv"):
    logger.info(f"Saving FRED features to {filename}...")
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    df.to_csv(filename, index=False)
    logger.info(f"Saved FRED features at: {os.path.abspath(filename)}")
    _print_data_summary(df)
    logger.info("FRED data saving complete.")

# ---------------- Main ---------------- #
def run_pipeline():
    """
    Fetches and saves FRED data.
    """
    logger.info("====== Starting Data Loader 03: FRED Data Fetching ======")
    fred_series = {
        "10Y_Yield": "GS10",
        "5Y_Yield": "DGS5",
        "2Y_Yield": "DGS2",
        "Unemployment": "UNRATE",
        "CPI": "CPIAUCSL"
    }
    fred_df = fetch_fred_series(fred_series, start="2015-01-01")
    save_fred_data(fred_df)
    logger.info("====== Finished Data Loader 03 ======")

# ---------------- Main ---------------- #
if __name__ == "__main__":
    run_pipeline()
