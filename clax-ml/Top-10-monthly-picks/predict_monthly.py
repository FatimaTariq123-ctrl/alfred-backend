# predict_monthly.py
"""
Monthly Top-10 Stock Prediction Module

This module provides a clean interface for generating monthly top-10 stock predictions
by reproducing the full feature engineering pipeline and applying the trained model.
"""

import os
import logging
import joblib
import pandas as pd
import numpy as np
import onnxruntime as ort
from typing import List, Optional
from datetime import datetime
from pathlib import Path

# Import feature engineering functions from Pipeline
import sys
import importlib.util

SCRIPT_DIR = Path(__file__).resolve().parent

# Import feature engineering module
fe_spec = importlib.util.spec_from_file_location("fe", SCRIPT_DIR / "Pipeline" / "06_Feature_Engg.py")
fe = importlib.util.module_from_spec(fe_spec)
fe_spec.loader.exec_module(fe)

# Import labels module
labels_spec = importlib.util.spec_from_file_location("labels", SCRIPT_DIR / "Pipeline" / "04_Labels.py")
labels_module = importlib.util.module_from_spec(labels_spec)
labels_spec.loader.exec_module(labels_module)

# ----------------- Constants ----------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
MODEL_PATH = "models/top10_model.onnx"
SCALER_PATH = "models/feature_scaler.joblib"
PCA_PATH = "outputs/pca_model.joblib"
SEQUENCE_LENGTH = 66  # Must match training sequence length
DATA_WINDOW_ROWS = 2520  # ~10 years of trading days


def _normalize_yahoo_symbol(symbol: str) -> str:
    """
    Normalize symbols to the Yahoo Finance convention.

    Example: 'BRK-B' -> 'BRK.B', 'BF-B' -> 'BF.B'.
    Non-equity symbols (indices, FX, futures) are left unchanged.
    """
    if not isinstance(symbol, str):
        return symbol
    if symbol.startswith("^") or "=" in symbol:
        return symbol
    return symbol.replace("-", ".")

# ----------------- Model Architecture ----------------- #
try:
    import torch.nn as nn

    class Top10LSTM(nn.Module):
        """LSTM model architecture matching training specification."""
        def __init__(self, input_dim, lstm_hidden=300, dense_hidden=100):
            super().__init__()
            self.lstm1 = nn.LSTM(input_dim, lstm_hidden, batch_first=True)
            self.lstm2 = nn.LSTM(lstm_hidden, lstm_hidden, batch_first=True)
            self.dense1 = nn.Linear(lstm_hidden, dense_hidden)
            self.relu = nn.ReLU()
            self.output_layer = nn.Linear(dense_hidden, 1)

        def forward(self, x):
            lstm_out, _ = self.lstm1(x)
            lstm_out, _ = self.lstm2(lstm_out)
            last_time_step_out = lstm_out[:, -1, :]
            x = self.relu(self.dense1(last_time_step_out))
            x = self.output_layer(x)
            return x
except ImportError:
    Top10LSTM = None


# ----------------- Data Loading ----------------- #
def load_raw_data(
    price_path: str = "outputs/02_Yahoo_Stocks.csv",
    membership_path: str = "outputs/01_SP500_membership_matrix.csv",
    fred_path: str = "outputs/03_fred_features.csv",
    max_rows: int = DATA_WINDOW_ROWS
) -> tuple:
    """
    Load raw data files and limit to last max_rows per ticker.
    
    Returns:
        tuple: (price_df, membership_df, fred_df)
    """
    logging.info("Loading raw data files...")
    
    # Load price data
    # First load without parse_dates to check column names
    price_df = pd.read_csv(price_path)
    # Handle different date column names
    if 'date' in price_df.columns:
        price_df.rename(columns={'date': 'Date'}, inplace=True)
    elif 'Date' not in price_df.columns:
        raise ValueError(f"Price CSV must have 'Date' or 'date' column. Found columns: {price_df.columns.tolist()}")
    price_df['Date'] = pd.to_datetime(price_df['Date']).dt.normalize()
    price_df = price_df.sort_values(['Ticker', 'Date'])
    
    # Limit to last max_rows per ticker
    price_df = price_df.groupby('Ticker').tail(max_rows).reset_index(drop=True)
    logging.info(f"Loaded price data: {price_df.shape}, date range: {price_df['Date'].min()} to {price_df['Date'].max()}")
    
    # Load membership matrix
    membership_df = pd.read_csv(membership_path, index_col=0, parse_dates=True)
    # Normalize membership tickers to match Yahoo Finance convention (e.g. BRK-B -> BRK.B)
    original_cols = list(membership_df.columns)
    normalized_cols = [_normalize_yahoo_symbol(c) for c in original_cols]
    if normalized_cols != original_cols:
        col_mapping = {old: new for old, new in zip(original_cols, normalized_cols)}
        membership_df = membership_df.rename(columns=col_mapping)
        logging.info("Normalized membership tickers for Yahoo Finance compatibility.")
    logging.info(f"Loaded membership matrix: {membership_df.shape}")
    
    # Load FRED macro data
    fred_df = pd.read_csv(fred_path)
    if 'DATE' in fred_df.columns:
        fred_df.rename(columns={'DATE': 'Date'}, inplace=True)
    fred_df['Date'] = pd.to_datetime(fred_df['Date']).dt.normalize()
    fred_df = fred_df.sort_values('Date')
    logging.info(f"Loaded FRED data: {fred_df.shape}")
    
    return price_df, membership_df, fred_df


def apply_universe_filter(
    price_df: pd.DataFrame,
    membership_df: pd.DataFrame,
    top_n: int = 50
) -> pd.DataFrame:
    """
    Apply universe construction:
    1. Filter by membership = 1 on latest date
    2. Filter to top N stocks by 20-day average dollar volume
    
    Args:
        price_df: Price data
        membership_df: Membership matrix
        top_n: Number of top stocks to keep
        
    Returns:
        Filtered price dataframe
    """
    logging.info("Applying universe filters...")
    
    # Get latest date membership
    latest_date = membership_df.index.max()
    latest_membership = membership_df.loc[latest_date]

    # Handle potential duplicate rows for the latest date by taking the last one
    if isinstance(latest_membership, pd.DataFrame):
        logging.warning(
            "Membership matrix has multiple rows for latest date %s; "
            "using the last row for universe construction.",
            latest_date,
        )
        latest_membership = latest_membership.iloc[-1]

    tradable_tickers = set(latest_membership[latest_membership == 1].index)
    
    # Filter by membership
    price_df = price_df[price_df['Ticker'].isin(tradable_tickers)].copy()
    logging.info(f"After membership filter: {len(price_df['Ticker'].unique())} tickers")
    if price_df.empty:
        logging.warning("Universe empty after membership filter; downstream steps may fail if no data is available.")
    
    # Filter by dollar volume (top N)
    price_df = labels_module.filter_by_dollar_volume(price_df, window=20, top_n=top_n)
    logging.info(f"After dollar volume filter: {len(price_df['Ticker'].unique())} tickers")
    
    return price_df


def build_features_for_prediction(
    price_df: pd.DataFrame,
    fred_df: pd.DataFrame,
    target_date: Optional[pd.Timestamp] = None
) -> pd.DataFrame:
    """
    Build features for prediction (C1-C7) without target generation.
    
    Args:
        price_df: Filtered price data
        fred_df: FRED macro data
        target_date: Target date for prediction (defaults to latest)
        
    Returns:
        DataFrame with features ready for model input
    """
    logging.info("Building features for prediction...")
    
    if target_date is None:
        target_date = price_df['Date'].max()
    
    # Filter data up to target date
    price_df = price_df[price_df['Date'] <= target_date].copy()
    
    # Step 1: Merge with macro data (no labels needed)
    # Create a temporary panel structure (without actual labels)
    temp_panel = price_df.copy()
    temp_panel['ForwardReturn'] = np.nan  # No labels for prediction
    temp_panel['Label'] = np.nan
    temp_panel['Rank'] = np.nan
    
    # Merge with macro data manually (since build_feature_panel expects file paths)
    merged_df = pd.merge(temp_panel, fred_df, on="Date", how="left")
    merged_df = merged_df.sort_values(["Ticker", "Date"])
    merged_df = merged_df.groupby("Ticker").apply(lambda g: g.ffill().bfill()).reset_index(drop=True)
    
    # Set index for feature engineering (required by feature functions)
    merged_df = merged_df.set_index(["Ticker", "Date"])
    
    # Step 2: Apply feature engineering (C1-C5)
    merged_df = fe.add_price_volume_derivatives(merged_df, windows=[22, 132, 252])
    merged_df = fe.add_macro_derivatives(merged_df, windows=[22, 132, 252])
    merged_df = fe.add_sentiment_dispersion(merged_df)
    merged_df = fe.add_seasonality_features(merged_df)
    
    # Step 3: ECOD normalization (C6)
    windows = [22, 132, 252]
    ecod_cols = [f'Return_{w}d' for w in windows] + \
                [f'Volume_{w}d' for w in windows] + \
                [f'CPI_{w}d' for w in windows] + \
                [f'Unemployment_{w}d' for w in windows] + \
                [f'10Y_Yield_{w}d' for w in windows] + \
                [f'5Y_Yield_{w}d' for w in windows] + \
                [f'2Y_Yield_{w}d' for w in windows] + \
                ['Sentiment', 'Dispersion']
    
    merged_df = fe.ecod_normalization(merged_df, ecod_cols, window=504)
    
    # Step 4: PCA transformation (C7) - use saved PCA model
    merged_df = fe.transform_pca(merged_df, suffix="_ecod", load_path=PCA_PATH)
    
    # Reset index for easier manipulation
    merged_df = merged_df.reset_index()
    
    logging.info(f"Feature engineering complete. Shape: {merged_df.shape}")
    return merged_df


def prepare_prediction_sequences(
    features_df: pd.DataFrame,
    target_date: pd.Timestamp,
    feature_cols: List[str]
) -> tuple:
    """
    Prepare sequences for model prediction.
    
    Args:
        features_df: DataFrame with features
        target_date: Target date for prediction
        feature_cols: List of feature column names
        
    Returns:
        tuple: (sequences array, valid_tickers list)
    """
    logging.info("Preparing prediction sequences...")
    
    # Get tickers available on target date (or latest available date if target_date doesn't exist)
    available_dates = features_df['Date'].unique()
    if target_date not in available_dates:
        # Use latest available date if target_date doesn't exist
        latest_date = pd.to_datetime(available_dates).max()
        logging.warning(f"Target date {target_date} not found in data. Using latest available date: {latest_date}")
        target_date = latest_date
    
    tickers_on_date = features_df[features_df['Date'] == target_date]['Ticker'].unique()
    logging.info(f"Tickers on target date ({target_date}): {len(tickers_on_date)}")
    
    sequences = []
    valid_tickers = []
    
    for ticker in tickers_on_date:
        ticker_df = features_df[features_df['Ticker'] == ticker].copy()
        ticker_df = ticker_df.set_index('Date').sort_index()
        ticker_df = ticker_df.loc[:target_date].tail(SEQUENCE_LENGTH)
        
        if len(ticker_df) == SEQUENCE_LENGTH:
            feature_window = ticker_df[feature_cols]
            
            # Check for NaNs or non-finite values
            if feature_window.isnull().values.any():
                continue
            window_values = feature_window.values.astype(np.float32, copy=False)
            if not np.isfinite(window_values).all():
                continue
            
            sequences.append(window_values)
            valid_tickers.append(ticker)
    
    logging.info(f"Prepared sequences for {len(valid_tickers)} tickers")
    return np.array(sequences, dtype=np.float32), valid_tickers


def predict_top_10_monthly(
    target_date: Optional[str] = None,
    price_path: str = "outputs/02_Yahoo_Stocks.csv",
    membership_path: str = "outputs/01_SP500_membership_matrix.csv",
    fred_path: str = "outputs/03_fred_features.csv"
) -> List[str]:
    """
    Generate top 10 monthly stock predictions.
    
    This function:
    1. Loads the latest model, scaler, and PCA model
    2. Loads raw data (prices, membership, macros) for last 2520 rows
    3. Applies universe filters (membership + top 50 by liquidity)
    4. Reproduces the full feature pipeline (C1-C7)
    5. Applies the trained model to produce rankings
    6. Returns top 10 tickers
    
    Args:
        target_date: Date for prediction in YYYY-MM-DD format (defaults to latest)
        price_path: Path to price data CSV
        membership_path: Path to membership matrix CSV
        fred_path: Path to FRED macro data CSV
        
    Returns:
        tuple: (List[str] tickers, List[float] scores) - Top 10 stock tickers and their scores, sorted best → worst
    """
    try:
        # 1. Load models and scalers
        logging.info("Loading models and scalers...")
        scaler = joblib.load(SCALER_PATH)
        # Use the exact same features that were used during training
        # The scaler's feature_names_in_ contains the features used during training
        feature_cols = list(scaler.feature_names_in_)
        model = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        logging.info(f"Model loaded. Features: {len(feature_cols)}")
        
        # 2. Load raw data
        price_df, membership_df, fred_df = load_raw_data(
            price_path=price_path,
            membership_path=membership_path,
            fred_path=fred_path,
            max_rows=DATA_WINDOW_ROWS
        )
        
        # 3. Parse target date
        latest_available_date = price_df['Date'].max()
        if target_date:
            target_date = pd.to_datetime(target_date).normalize()
            # If target date is in the future, use latest available date
            if target_date > latest_available_date:
                logging.warning(f"Target date {target_date} is beyond latest available data ({latest_available_date}). Using latest available date.")
                target_date = latest_available_date
        else:
            target_date = latest_available_date
        logging.info(f"Target date: {target_date}")
        
        # 4. Apply universe filters
        price_df = apply_universe_filter(price_df, membership_df, top_n=50)
        if price_df.empty:
            raise ValueError(
                "Universe is empty after applying membership and dollar-volume filters; "
                "cannot build prediction features."
            )
        
        # 5. Build features
        features_df = build_features_for_prediction(price_df, fred_df, target_date=target_date)
        
        # Verify all required features are present
        missing_features = set(feature_cols) - set(features_df.columns)
        if missing_features:
            raise ValueError(f"Missing required features: {missing_features}")
        
        # Ensure feature columns are in the same order as scaler expects
        feature_cols = [col for col in feature_cols if col in features_df.columns]
        
        # 6. Prepare sequences
        sequences, valid_tickers = prepare_prediction_sequences(
            features_df, target_date, feature_cols
        )
        
        if len(valid_tickers) == 0:
            raise ValueError("No valid tickers with sufficient history for prediction")
        
        # 7. Scale features
        flattened = sequences.reshape(-1, len(feature_cols))
        flattened_df = pd.DataFrame(flattened, columns=feature_cols)
        scaled_flat = scaler.transform(flattened_df)
        
        if not np.isfinite(scaled_flat).all():
            raise ValueError("Scaler output contains non-finite values")
        
        scaled_sequences = scaled_flat.reshape(len(valid_tickers), SEQUENCE_LENGTH, -1).astype(np.float32)
        
        # 8. Run prediction
        logging.info("Running model prediction...")
        input_name = model.get_inputs()[0].name
        scores = model.run(None, {input_name: scaled_sequences})[0].squeeze()
        
        scores = np.atleast_1d(scores).astype(float)
        
        # Filter out non-finite scores
        valid_mask = np.isfinite(scores)
        scores = scores[valid_mask]
        valid_tickers = [t for i, t in enumerate(valid_tickers) if valid_mask[i]]
        
        if len(valid_tickers) == 0:
            raise ValueError("Model produced no valid scores")
        
        # 9. Rank and select top 10
        results_df = pd.DataFrame({'ticker': valid_tickers, 'score': scores})
        results_df = results_df.sort_values('score', ascending=False).head(10)
        top_10_tickers = results_df['ticker'].tolist()
        top_10_scores = results_df['score'].tolist()
        
        logging.info(f"Top 10 predictions: {top_10_tickers}")
        return top_10_tickers, top_10_scores
        
    except FileNotFoundError as e:
        logging.error(f"Required file not found: {e}")
        raise
    except Exception as e:
        logging.error(f"Prediction failed: {e}", exc_info=True)
        raise


def predict_top_10_monthly_tickers_only(
    target_date: Optional[str] = None,
    price_path: str = "outputs/02_Yahoo_Stocks.csv",
    membership_path: str = "outputs/01_SP500_membership_matrix.csv",
    fred_path: str = "outputs/03_fred_features.csv"
) -> List[str]:
    """
    Wrapper function that returns only the top 10 tickers (no scores).
    
    This is the clean interface specified in the requirements.
    
    Returns:
        List[str]: Top 10 stock tickers predicted for next month, sorted best → worst
    """
    tickers, _ = predict_top_10_monthly(target_date, price_path, membership_path, fred_path)
    return tickers


if __name__ == "__main__":
    # Example usage
    top_10_tickers, top_10_scores = predict_top_10_monthly()
    print(f"\nTop 10 Monthly Picks:")
    for i, (ticker, score) in enumerate(zip(top_10_tickers, top_10_scores), 1):
        print(f"  {i}. {ticker}: {score:.4f}")
    
    # Also demonstrate the clean interface
    print(f"\nClean interface (tickers only): {predict_top_10_monthly_tickers_only()}")
