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
def fetch_prediction_features_from_db(target_date: pd.Timestamp = None) -> pd.DataFrame:
    """
    Fetches the pre-computed features directly from PostgreSQL instead of building them.
    """
    try:
        import sys
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from shared_db import load_from_db
    except ImportError:
        raise ImportError("shared_db.py not found. Make sure the database module is configured.")
        
    logging.info("Fetching pre-computed features from database...")
    query = 'SELECT * FROM clax_top10_features'
    features_df = load_from_db(query)
    
    if features_df.empty:
        raise ValueError("No pre-computed features found in clax_top10_features.")
        
    features_df['Date'] = pd.to_datetime(features_df['Date'])
    
    # Apply date filtering
    if target_date:
        features_df = features_df[features_df['Date'] <= target_date]
        
    return features_df


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
    1. Loads the latest model and scaler
    2. Fetches pre-computed features from PostgreSQL (clax_top10_features)
    3. Prepares the LSTM sequences
    4. Applies the trained model to produce rankings
    5. Returns top 10 tickers
    """
    try:
        # 1. Load models and scalers
        logging.info("Loading models and scalers...")
        scaler = joblib.load(SCALER_PATH)
        feature_cols = list(scaler.feature_names_in_)
        model = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        logging.info(f"Model loaded. Features: {len(feature_cols)}")
        
        # 2. Parse target date
        if target_date:
            target_date = pd.to_datetime(target_date).normalize()
        else:
            target_date = None
            
        # 3. Load pre-computed features directly from Postgres
        features_df = fetch_prediction_features_from_db(target_date)
        
        # If no explicit target date, just use the latest available date from the DB
        if target_date is None:
            target_date = features_df['Date'].max()
        logging.info(f"Target date: {target_date}")
        
        # 4. Verify all required features are present
        missing_features = set(feature_cols) - set(features_df.columns)
        if missing_features:
            raise ValueError(f"Missing required features: {missing_features}")
        
        # 5. Prepare sequences
        sequences, valid_tickers = prepare_prediction_sequences(
            features_df, target_date, feature_cols
        )
        
        if len(valid_tickers) == 0:
            raise ValueError("No valid tickers with sufficient history for prediction")
        
        # 6. Scale features
        flattened = sequences.reshape(-1, len(feature_cols))
        flattened_df = pd.DataFrame(flattened, columns=feature_cols)
        scaled_flat = scaler.transform(flattened_df)
        
        if not np.isfinite(scaled_flat).all():
            raise ValueError("Scaler output contains non-finite values")
        
        scaled_sequences = scaled_flat.reshape(len(valid_tickers), SEQUENCE_LENGTH, -1).astype(np.float32)
        
        # 7. Run prediction
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
        
        # 8. Rank and select top 10
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
