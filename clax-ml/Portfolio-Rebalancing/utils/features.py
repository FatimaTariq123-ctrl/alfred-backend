# utils/features.py
import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)

def ecod_normalization(df: pd.DataFrame, cols: list, window: int = 504) -> pd.DataFrame:
    """
    Applies Empirical Cumulative Distribution (ECOD) normalization to specified columns.
    """
    logger.info("Applying ECOD normalization...")
    df_sorted = df.sort_values(["Ticker", "Direction", "Date"]).copy()

    for c in cols:
        df_sorted[f"{c}_ecod"] = df_sorted.groupby(["Ticker", "Direction"])[c].transform(
            lambda x: x.rolling(window, min_periods=20).rank(pct=True)
        )
    return df_sorted

def save_features(df: pd.DataFrame, out_path="outputs/06_final_features.csv"):
    """
    Saves the final features DataFrame to a CSV file.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    logger.info(f"✅ Saved final OEP features → {out_path} | Shape: {df.shape}")
