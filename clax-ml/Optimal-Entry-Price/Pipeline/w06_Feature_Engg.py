# Pipeline/w06_Feature_Engg.py
# ---------------------
import os
import logging
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
import joblib

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ======================================================
#  DATA LOADING
# ======================================================
def load_feature_panel(panel_path: str = "outputs/05_label_macro_features_OEP.csv") -> pd.DataFrame:
    logging.info(f"Loading merged stock + macro panel: {panel_path}")
    df = pd.read_csv(panel_path, parse_dates=["Date"]).sort_values(["Ticker", "Date"])
    return df


# ======================================================
#  C1: % CHANGE OVER MULTIPLE HORIZONS (STOCK + MACRO)
# ======================================================
def add_rolling_pct_changes(df: pd.DataFrame,
                            horizons=[22, 132, 252],
                            macro_exclude=("UNRATE", "FEDFUNDS")) -> pd.DataFrame:
    """
    Compute % changes for Close + macro variables (excluding slow ones like rates/unemployment).
    """
    logging.info("Adding rolling % changes for stock and macro variables...")

    df_unique_close = df[['Date', 'Ticker', 'Close']].drop_duplicates()
    
    macro_cols = [c for c in df.columns if c not in
                  ["Date", 'Direction', "Ticker", "Close", "ForwardReturn", "EntryTarget", "Tradable", "Label", 'Target']]

    # exclude interest rate and unemployment rate columns
    macro_pct_cols = [c for c in macro_cols if all(excl not in c for excl in macro_exclude)]

    for h in horizons:
        # stock-level price change
        df_unique_close[f"StockPct_{h}"] = df_unique_close.groupby("Ticker")["Close"].pct_change(h)

        # macro % change (same for all tickers)
        for mc in macro_pct_cols:
            df[f"{mc}_pct_{h}"] = df[mc].pct_change(h)
    
    df = pd.merge(df, df_unique_close.drop(columns='Close'), on=['Date', 'Ticker'], how='left')

    df = df.groupby(["Ticker", "Direction"]).apply(lambda g: g.ffill().bfill()).reset_index(drop=True)
    logging.info("Added rolling % change features.")
    return df


# ======================================================
#  C2: RAW DIFFERENCES FOR INTEREST/UNEMPLOYMENT
# ======================================================
def add_macro_raw_differences(df: pd.DataFrame,
                              horizons=[22, 132, 252],
                              macro_vars=("UNRATE", "FEDFUNDS")) -> pd.DataFrame:
    """
    Compute raw differences for interest rate & unemployment over given horizons.
    """
    logging.info("Adding raw macro differences for interest & unemployment...")

    for h in horizons:
        for mv in macro_vars:
            if mv in df.columns:
                df[f"{mv}_diff_{h}"] = df[mv].diff(h)
    df = df.ffill().bfill()
    return df


# ======================================================
#  C3: CYCLE ENCODING FOR MACRO UPDATES
# ======================================================
def add_cycle_encodings(df: pd.DataFrame, macro_cols=None) -> pd.DataFrame:
    """
    Encode time since last macro update as a cyclic signal.
    Useful for sparse-updated macro vars (monthly, quarterly).
    """
    logging.info("Adding cycle encodings for macro features...")
    if macro_cols is None:
        macro_cols = [c for c in df.columns if c.startswith(("UNRATE", "FEDFUNDS"))]

    for col in macro_cols:
        mask = df[col].notna()
        last_update = df["Date"].where(mask).ffill()
        delta_days = (df["Date"] - last_update).dt.days
        df[f"{col}_cycle_sin"] = np.sin(2 * np.pi * delta_days / 365)
        df[f"{col}_cycle_cos"] = np.cos(2 * np.pi * delta_days / 365)
    return df


# ======================================================
#  C3/C4: SENTIMENT & DISPERSION
# ======================================================
def add_sentiment_dispersion(df: pd.DataFrame, horizons=[22, 132, 252]) -> pd.DataFrame:
    """
    Sentiment: median forward return of tradable stocks.
    Dispersion: std of returns across stocks.
    """
    logging.info("Adding sentiment & dispersion features...")

    for h in horizons:
        col = f"StockPct_{h}" if f"StockPct_{h}" in df.columns else "ForwardReturn"
        daily_stats = df.groupby("Date")[col].agg(
            Sentiment="median", Dispersion="std"
        ).reset_index()
        daily_stats.rename(columns={
            "Sentiment": f"Sentiment_{h}",
            "Dispersion": f"Dispersion_{h}"
        }, inplace=True)
        df = pd.merge(df, daily_stats, on="Date", how="left")
    return df


# ======================================================
#  C5: SEASONAL FEATURES
# ======================================================
def add_seasonality_features(df: pd.DataFrame) -> pd.DataFrame:
    df["dow_sin"] = np.sin(2 * np.pi * df["Date"].dt.dayofweek / 7)
    df["month_sin"] = np.sin(2 * np.pi * df["Date"].dt.month / 12)
    df["day_sin"] = np.sin(2 * np.pi * df["Date"].dt.day / 31)
    logging.info("Added seasonality features.")
    return df


# ======================================================
#  ECOD NORMALIZATION (EXCLUDE CYCLICAL & TARGET)
# ======================================================
def ecod_normalization(df: pd.DataFrame, cols: list, window: int = 504) -> pd.DataFrame:
    logging.info("Applying ECOD normalization...")
    df_sorted = df.sort_values(["Ticker", "Direction", "Date"]).copy()

    for c in cols:
        df_sorted[f"{c}_ecod"] = df_sorted.groupby(["Ticker", "Direction"])[c].transform(
            lambda x: (x - x.rolling(window, min_periods=20).mean()) /
                      x.rolling(window, min_periods=20).std().replace(0, 1)
        )
    return df_sorted


# ======================================================
#  PCA / ORTHOGONAL FEATURES
# ======================================================
def fit_pca(df: pd.DataFrame,
            suffix="_ecod",
            variance_threshold=0.95,
            save_path="outputs/pca_model.joblib") -> pd.DataFrame:
    feature_cols = [c for c in df.columns if c.endswith(suffix)]
    X = df[feature_cols].fillna(0)
    pca = PCA(n_components=variance_threshold)
    pca_data = pca.fit_transform(X)
    joblib.dump(pca, save_path)
    logging.info(f"PCA fitted & saved → {save_path}")
    pca_df = pd.DataFrame(pca_data, columns=[f"PCA_{i+1}" for i in range(pca_data.shape[1])])
    df = pd.concat([df.reset_index(drop=True), pca_df], axis=1)
    return df


# ======================================================
#  SAVE FEATURES
# ======================================================
def save_features(df: pd.DataFrame, out_path="outputs/06_final_features.csv"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    logging.info(f"✅ Saved final OEP features → {out_path} | Shape: {df.shape}")


# ======================================================
#  MAIN PIPELINE (OEP VERSION)
# ======================================================
def generate_features(panel_path="outputs/05_label_macro_features_OEP.csv",
                      output_path="outputs/06_final_features.csv",
                      pca_save_path="outputs/pca_model.joblib"):
    df = load_feature_panel(panel_path)

    df = add_rolling_pct_changes(df)
    df = add_macro_raw_differences(df)
    df = add_cycle_encodings(df)
    df = add_sentiment_dispersion(df)
    df = add_seasonality_features(df)

    # Select only numeric and stable columns for ECOD
    ecod_cols = [c for c in df.columns if any(x in c for x in ["Pct_", "diff_", "Sentiment", "Dispersion"])]
    ecod_cols.append('Direction')

    df = ecod_normalization(df, ecod_cols)
    # Replace inf values with NaN and then fill NaN with 0 before PCA
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.fillna(0, inplace=True)
    df = fit_pca(df, suffix="_ecod", save_path=pca_save_path)

    save_features(df, output_path)
    return df


if __name__ == "__main__":
    generate_features()
