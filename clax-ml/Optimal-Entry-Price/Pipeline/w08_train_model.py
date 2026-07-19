# Pipeline/w07_train_model.py
#-------------------------

"""
Train Model -- Optimal Entry Price (OEP)
---------------------------------------
Trains a regression neural network to predict continuous target values (Target)
based on engineered features from the OEP labeling pipeline.

**Updated to align with documentation:**
- Model: Unified LSTM-LSTM-Dense architecture for both buy and sell predictions.
- Loss: Root Mean Squared Error (RMSE).
- Training: Early stopping mechanism.
- Sampling: Balanced sampling for buy and sell directions.
- Evaluation: Advanced performance metrics by direction (hit ratio, success rate, etc.).
"""

import os
import logging
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.model_selection import train_test_split
import joblib

# Handle imports - try relative first, then absolute
try:
    from .w07_model import LSTMRegressor, RMSELoss, apply_directional_activation
except (ImportError, ValueError):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from w07_model import LSTMRegressor, RMSELoss, apply_directional_activation

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------- Configuration ---------------- #
FEATURE_CSV = "outputs/06_final_features.csv"
EPOCHS = 10
BATCH_SIZE = 256
LEARNING_RATE = 1e-3
TEST_SIZE = 0.2
RANDOM_STATE = 42
PATIENCE = 5  # For early stopping
HIT_TOLERANCE = 0.02 # 2% tolerance for hit ratio calculation


# ---------------- Early Stopping ---------------- #
class EarlyStopping:
    def __init__(self, patience=7, verbose=False, delta=0, path='models/oep_regressor.pth'):
        self.patience = patience
        self.verbose = verbose
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.val_loss_min = np.inf
        self.delta = delta
        self.path = path

    def __call__(self, val_loss, model):
        score = -val_loss
        if self.best_score is None:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
        elif score < self.best_score + self.delta:
            self.counter += 1
            logging.info(f'EarlyStopping counter: {self.counter} out of {self.patience}')
            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
            self.counter = 0

    def save_checkpoint(self, val_loss, model):
        if self.verbose:
            logging.info(f'Validation loss decreased ({self.val_loss_min:.6f} --> {val_loss:.6f}).  Saving model ...')
        torch.save(model.state_dict(), self.path)
        self.val_loss_min = val_loss


# ---------------- Evaluation ---------------- #
def calculate_advanced_metrics(model, loader, scaler_y, y_true_orig_df, hit_tolerance, device):
    model.eval()
    predictions_scaled = []
    with torch.no_grad():
        for xb, _, db in loader:
            xb = xb.to(device)
            out = model(xb)
            out = apply_directional_activation(out, db.to(device))
            predictions_scaled.extend(out.cpu().numpy())

    # Inverse transform predictions to original scale
    y_pred_orig = scaler_y.inverse_transform(np.array(predictions_scaled))
    
    y_true_orig_df = y_true_orig_df.copy()
    y_true_orig_df['Predicted'] = y_pred_orig

    metrics = {}
    for direction in ['buy', 'sell']:
        direction_val = 1 if direction == 'buy' else 0
        df_direction = y_true_orig_df[y_true_orig_df['Direction'] == direction_val]
        
        if df_direction.empty:
            continue

        y_pred_direction = df_direction['Predicted'].values    
        y_true_direction = df_direction['Target'].values

        # Percent-gap deviation (absolute error)
        price_deviation = np.mean(np.abs(y_pred_direction - y_true_direction))

        # Hit Ratio: Prediction is within a tolerance of the true value
        hits = np.abs(y_pred_direction - y_true_direction) <= hit_tolerance
        hit_ratio = np.mean(hits)
        
        # Mean Prediction - Helps diagnose if model is 'lazy' (predicting only zeros)
        mean_pred = np.mean(y_pred_direction)
        mean_true = np.mean(y_true_direction)

        # Success Rate: Now requires the prediction to be accurate (a 'Hit'), 
        # not just the correct sign.
        success_rate = hit_ratio 

        metrics[direction] = {
            "Price Deviation": price_deviation,
            "Hit Ratio": hit_ratio,
            "Success Rate": success_rate,
            "Mean Predicted": mean_pred,
            "Mean Target": mean_true
        }
    return metrics

if __name__ == "__main__":
    logging.info(f"Loading feature CSV: {FEATURE_CSV}")
    df = pd.read_csv(FEATURE_CSV, parse_dates=["Date"])

    # ---------------- Prepare X, y ---------------- #
    # Keep Direction in X as a feature to help model distinguish modes
    drop_cols = ["Date", "Ticker", "Close", "Target"]
    drop_cols = [c for c in drop_cols if c in df.columns]
    X_df = df.drop(columns=drop_cols)
    y_df = df[["Target", "Direction", "Close"]]

    X_np = X_df.values.astype(np.float32)
    X_np = np.nan_to_num(X_np, nan=0.0, posinf=0.0, neginf=0.0)

    y_np = y_df[["Target"]].values.astype(np.float32).reshape(-1, 1)
    direction_np = y_df[["Direction"]].values.astype(np.float32)

    # Scale features
    scaler_X = StandardScaler()
    X_scaled = scaler_X.fit_transform(X_np)

    # Scale target using RobustScaler to handle buy/sell distribution differences
    scaler_y = RobustScaler(with_centering=False)
    y_scaled = scaler_y.fit_transform(y_np)

    # --- Reshape for LSTM ---
    X_reshaped = np.reshape(X_scaled, (X_scaled.shape[0], 1, X_scaled.shape[1]))

    # ---------------- Train/Val Split ---------------- #
    X_train, X_val, y_train, y_val, dir_train, dir_val, y_train_df, y_val_df = train_test_split(
        X_reshaped, y_scaled, direction_np, y_df,
        test_size=TEST_SIZE, shuffle=True, random_state=RANDOM_STATE, stratify=y_df['Direction']
    )

    # ---------------- Balanced Sampling ---------------- #
    train_targets = y_train_df['Direction']
    class_counts = train_targets.value_counts()
    class_weights = 1.0 / class_counts
    sample_weights = train_targets.map(class_weights).values
    sampler = WeightedRandomSampler(weights=sample_weights, num_samples=len(sample_weights), replacement=True)
    logging.info("Created balanced sampler for training data.")

    train_ds = TensorDataset(torch.tensor(X_train), torch.tensor(y_train), torch.tensor(dir_train))
    val_ds = TensorDataset(torch.tensor(X_val), torch.tensor(y_val), torch.tensor(dir_val))

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, sampler=sampler)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)

    # ---------------- Training Loop ---------------- #
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = LSTMRegressor(X_reshaped.shape[2]).to(device)
    criterion = RMSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    early_stopping = EarlyStopping(patience=PATIENCE, verbose=True, path="models/oep_regressor.pth")

    logging.info("Starting model training...")
    for epoch in range(EPOCHS):
        model.train()
        train_loss = 0.0
        for xb, yb, db in train_loader:
            xb, yb, db = xb.to(device), yb.to(device), db.to(device)
            optimizer.zero_grad()
            out = model(xb)
            out = apply_directional_activation(out, db)
            loss = criterion(out, yb)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * xb.size(0)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb, db in val_loader:
                xb, yb, db = xb.to(device), yb.to(device), db.to(device)
                out = model(xb)
                out = apply_directional_activation(out, db)
                loss = criterion(out, yb)
                val_loss += loss.item() * xb.size(0)

        train_loss /= len(train_loader.sampler)
        val_loss /= len(val_loader.dataset)

        logging.info(f"Epoch {epoch+1}/{EPOCHS} - Train RMSE: {train_loss:.6f} | Val RMSE: {val_loss:.6f}")

        early_stopping(val_loss, model)
        if early_stopping.early_stop:
            logging.info("Early stopping triggered.")
            break

    # Load the best model saved by early stopping
    model.load_state_dict(torch.load('models/oep_regressor.pth'))

    logging.info("Calculating advanced performance metrics on validation set...")
    val_metrics = calculate_advanced_metrics(model, val_loader, scaler_y, y_val_df, HIT_TOLERANCE, device)

    for direction, metrics in val_metrics.items():
        logging.info(f"--- {direction.upper()} ---")
        for name, value in metrics.items():
            logging.info(f"- {name}: {value:.4f}")

    # ---------------- Save Scalers ---------------- #
    os.makedirs("models", exist_ok=True)
    joblib.dump(scaler_X, "models/scaler_X.pkl")
    joblib.dump(scaler_y, "models/scaler_y.pkl")
    logging.info("Feature and target scalers saved.")
    logging.info("OEP model training pipeline completed successfully.")
