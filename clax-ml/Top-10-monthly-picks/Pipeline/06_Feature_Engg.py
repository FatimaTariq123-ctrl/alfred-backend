# Pipeline/06_Feature_Engg.py
import os
import logging
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from scipy.stats import rankdata
import joblib

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ---------------- Data Loading ---------------- #
def load_feature_panel(panel_path: str = "outputs/05_label_macro_features.csv") -> pd.DataFrame:
    logging.info(f"Loading feature panel from {panel_path}...")
    df = pd.read_csv(panel_path, parse_dates=["Date"])
    df = df.sort_values(["Ticker", "Date"]).set_index(["Ticker", "Date"])
    return df


# ---------------- Feature Engineering ---------------- #
def add_price_volume_derivatives(data: pd.DataFrame, windows=[22, 132, 252]) -> pd.DataFrame:
    """Calculates pct_change for close price and volume."""
    for w in windows:
        data[f'Return_{w}d'] = data.groupby(level='Ticker')['Close'].pct_change(w)
        data[f'Volume_{w}d'] = data.groupby(level='Ticker')['Volume'].pct_change(w)
    
    data = data.groupby(level='Ticker').ffill()
    data = data.groupby(level='Ticker').bfill()
    logging.info(f"Added price and volume derivatives for windows: {windows}")
    return data


def add_macro_derivatives(data: pd.DataFrame, windows=[22, 132, 252]) -> pd.DataFrame:
    """Calculates derivatives for macro features."""
    macro_cols = {
        'CPI': 'pct_change',
        'Unemployment': 'diff',
        '10Y_Yield': 'diff',
        '5Y_Yield': 'diff',
        '2Y_Yield': 'diff'
    }
    
    for col, method in macro_cols.items():
        if col in data.columns:
            for w in windows:
                if method == 'pct_change':
                    data[f'{col}_{w}d'] = data.groupby(level='Ticker')[col].pct_change(w)
                elif method == 'diff':
                    data[f'{col}_{w}d'] = data.groupby(level='Ticker')[col].diff(w)

    data = data.groupby(level='Ticker').ffill()
    data = data.groupby(level='Ticker').bfill()
    logging.info("Added macro derivatives.")
    return data


def add_sentiment_dispersion(data: pd.DataFrame) -> pd.DataFrame:
    """Calculates sentiment and dispersion based on daily returns."""
    data['DailyReturn'] = data.groupby(level='Ticker')['Close'].pct_change(1)
    
    daily_stats = data.reset_index().groupby("Date")["DailyReturn"].agg(
        Sentiment="median", Dispersion="std"
    ).reset_index()
    
    data = data.reset_index().merge(daily_stats, on="Date", how="left").set_index(["Ticker", "Date"])
    data.drop(columns=['DailyReturn'], inplace=True)
    logging.info("Added sentiment & dispersion features.")
    return data


def add_seasonality_features(data: pd.DataFrame) -> pd.DataFrame:
    """Adds time-based cyclical features."""
    date_idx = data.index.get_level_values('Date')
    data["dow_sin"] = np.sin(2 * np.pi * date_idx.dayofweek / 7)
    data["month_sin"] = np.sin(2 * np.pi * date_idx.month / 12)
    data["day_sin"] = np.sin(2 * np.pi * date_idx.day / 31)
    logging.info("Added seasonality features.")
    return data


# ---------------- ECOD Normalization ---------------- #
def ecod_normalization(df: pd.DataFrame, cols: list, window: int = 504) -> pd.DataFrame:
    df_sorted = df.copy() # Data is already sorted by index
    for c in cols:
        if c in df_sorted.columns:
            df_sorted[f"{c}_ecod"] = df_sorted.groupby(level="Ticker")[c].transform(
                lambda x: (x - x.rolling(window, min_periods=20).mean()) /
                          (x.rolling(window, min_periods=20).std().replace(0, 1))
            )
    logging.info(f"ECOD normalization applied to {len(cols)} columns.")
    return df_sorted


# ---------------- PCA / Orthogonal Features ---------------- #
def fit_pca(data: pd.DataFrame, suffix="_ecod", variance_threshold=0.95, save_path="outputs/pca_model.joblib"):
    feature_cols = [c for c in data.columns if c.endswith(suffix) and data[c].notna().any()]
    logging.info(f"Running PCA on {len(feature_cols)} features...")
    # Replace infinities that can arise from pct_change / ECOD with NaN, then fill with 0
    X = data[feature_cols].replace([np.inf, -np.inf], np.nan)
    # Optional: log how many values were non-finite before cleaning
    non_finite_count = (~np.isfinite(X.to_numpy())).sum()
    if non_finite_count > 0:
        logging.warning(f"PCA input had {non_finite_count} non-finite values; replacing with 0 after cleaning.")
    X = X.fillna(0)
    pca = PCA(n_components=variance_threshold)
    pca_data = pca.fit_transform(X)
    joblib.dump(pca, save_path)
    logging.info(f"PCA model saved to {save_path}, explaining {pca.explained_variance_ratio_.sum():.2f} variance with {pca.n_components_} components.")
    pca_df = pd.DataFrame(pca_data, columns=[f"PCA_{i+1}" for i in range(pca.n_components_)], index=data.index)
    data = pd.concat([data, pca_df], axis=1)
    logging.info("Applied PCA (orthogonal) transformation.")
    return data


def transform_pca(data: pd.DataFrame, suffix="_ecod", load_path="outputs/pca_model.joblib") -> pd.DataFrame:
    feature_cols = [c for c in data.columns if c.endswith(suffix) and data[c].notna().any()]
    # Match fit_pca cleaning: remove infinities, then fill NaNs with 0
    X = data[feature_cols].replace([np.inf, -np.inf], np.nan)
    non_finite_count = (~np.isfinite(X.to_numpy())).sum()
    if non_finite_count > 0:
        logging.warning(f"PCA transform input had {non_finite_count} non-finite values; replacing with 0 after cleaning.")
    X = X.fillna(0)
    pca = joblib.load(load_path)
    pca_data = pca.transform(X)
    pca_df = pd.DataFrame(pca_data, columns=[f"PCA_{i+1}" for i in range(pca.n_components_)], index=data.index)
    data = pd.concat([data, pca_df], axis=1)
    logging.info(f"Applied saved PCA model from {load_path}")
    return data


# ---------------- Saving ---------------- #
def save_features(data: pd.DataFrame, out_path="outputs/06_final_features.csv"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    reset_data = data.reset_index()
    reset_data.to_csv(out_path, index=False)
    logging.info(f"✅ Final features saved to {out_path} | Shape: {data.shape}")

    # Write curated features to Postgres as per architectural requirements
    try:
        import sys
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
        from shared_db import save_to_db
        logging.info("Writing curated Top-10 features to PostgreSQL database (clax_top10_features)...")
        save_to_db(reset_data, "clax_top10_features")
        logging.info("✅ Successfully synced Top-10 features to PostgreSQL.")
    except Exception as e:
        logging.warning(f"Failed to sync Top-10 features to PostgreSQL: {e}")


# ---------------- Main Pipeline ---------------- #
def generate_features(panel_path="outputs/05_label_macro_features.csv",
                      output_path="outputs/06_final_features.csv",
                      pca_save_path="outputs/pca_model.joblib"):
    
    data = load_feature_panel(panel_path)

    # Feature Creation
    data = add_price_volume_derivatives(data)
    data = add_macro_derivatives(data)
    data = add_sentiment_dispersion(data)
    data = add_seasonality_features(data)

    # ECOD Normalization
    windows = [22, 132, 252]
    ecod_cols = [f'Return_{w}d' for w in windows] + \
                [f'Volume_{w}d' for w in windows] + \
                [f'CPI_{w}d' for w in windows] + \
                [f'Unemployment_{w}d' for w in windows] + \
                [f'10Y_Yield_{w}d' for w in windows] + \
                [f'5Y_Yield_{w}d' for w in windows] + \
                [f'2Y_Yield_{w}d' for w in windows] + \
                ['Sentiment', 'Dispersion']
    
    data = ecod_normalization(data, ecod_cols)

    # PCA
    data = fit_pca(data, suffix="_ecod", save_path=pca_save_path)
    
    # Save
    save_features(data, output_path)
    return data


if __name__ == "__main__":
    generate_features()
