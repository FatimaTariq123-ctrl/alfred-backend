# Pipeline/w07_train_model.py
#-------------------------

import os
import logging
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error
from sklearn.metrics.pairwise import cosine_similarity
import joblib


# ---------------- CONFIG ---------------- #
TRAINING_FEATURES_PATH = os.path.join("outputs", "06_final_features.csv")
MODELS_DIR = "models"
MODEL_SAVE_FILE = os.path.join(MODELS_DIR, "portfolio_weights_model.pth")
SCALER_X_SAVE_PATH = os.path.join(MODELS_DIR, "scaler_X.pkl")
TRAINED_TICKERS_PATH = os.path.join(MODELS_DIR, "trained_tickers.csv")
TRAINED_MODEL_COLUMNS_PATH = os.path.join(MODELS_DIR, "trained_model_columns.csv")

TRAINING_EPOCHS = 100
TRAINING_BATCH_SIZE = 32
learning_rate = 1e-5
TRAINING_TEST_SIZE = 0.2
TRAINING_PATIENCE = 30


# ---------------- MODEL ---------------- #
class LSTMRegressor(nn.Module):
    def __init__(self, input_size, hidden_layer_size=300, output_size=1):
        super().__init__()

        self.lstm1 = nn.LSTM(input_size, hidden_layer_size, batch_first=True)
        self.lstm2 = nn.LSTM(hidden_layer_size, hidden_layer_size, batch_first=True)

        self.linear1 = nn.Linear(hidden_layer_size, 100)
        self.relu = nn.ReLU()
        self.linear2 = nn.Linear(100, output_size)
        self.softmax = nn.Softmax(dim=1)

    def forward(self, x):
        x, _ = self.lstm1(x)
        x, _ = self.lstm2(x)
        x = x[:, -1, :]
        x = self.relu(self.linear1(x))
        x = self.softmax(self.linear2(x))
        return x


class RMSELoss(nn.Module):
    def __init__(self):
        super().__init__()
        self.mse = nn.MSELoss()

    def forward(self, yhat, y):
        return torch.sqrt(self.mse(yhat, y))


# ---------------- LOGGING ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------- EARLY STOPPING ---------------- #
class EarlyStopping:
    def __init__(self, patience=7, delta=0, path=MODEL_SAVE_FILE):
        self.patience = patience
        self.delta = delta
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.val_loss_min = np.inf
        self.path = path

    def __call__(self, val_loss, model):
        score = -val_loss

        if self.best_score is None:
            self.best_score = score
            self.save(val_loss, model)

        elif score < self.best_score + self.delta:
            self.counter += 1
            logger.info(f"EarlyStopping: {self.counter}/{self.patience}")
            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_score = score
            self.save(val_loss, model)
            self.counter = 0

    def save(self, val_loss, model):
        torch.save(model.state_dict(), self.path)
        self.val_loss_min = val_loss


# ---------------- TRAINING ---------------- #
def train_model(epochs, patience, learning_rate=1e-3):

    logger.info(f"Loading data: {TRAINING_FEATURES_PATH}")
    df = pd.read_csv(TRAINING_FEATURES_PATH, parse_dates=["Date"])

    if "Market" in df.columns:
        logger.info("Market distribution:")
        logger.info(df["Market"].value_counts())

    # ---------------- FEATURES ---------------- #
    feature_cols = [c for c in df.columns if c.endswith("_ecod") or c.startswith("PCA_")]
    target_col = "Target_Weight"

    if target_col not in df.columns:
        raise ValueError("❌ Target_Weight column missing")

    # ---------------- PIVOT ---------------- #
    df_feat = df.pivot_table(index="Date", columns="Ticker", values=feature_cols)
    df_feat.columns = ["_".join(map(str, c)) for c in df_feat.columns]

    df_target = df.pivot_table(index="Date", columns="Ticker", values=target_col)

    common_dates = df_feat.index.intersection(df_target.index)

    X_df = df_feat.loc[common_dates].fillna(0)
    y_df = df_target.loc[common_dates].fillna(0)

    # ---------------- TICKERS FIX ---------------- #
    tickers = sorted({col.split("_")[-1] for col in X_df.columns})
    num_assets = len(tickers)

    logger.info(f"Assets: {num_assets}")
    logger.info(f"Tickers: {tickers}")

    # ---------------- TARGET MATRIX ---------------- #
    y_np = np.zeros((len(X_df), num_assets), dtype=np.float32)

    for i, t in enumerate(tickers):
        if t in y_df.columns:
            y_np[:, i] = y_df[t].values

    row_sums = y_np.sum(axis=1)
    row_sums[row_sums == 0] = 1
    y_np = y_np / row_sums[:, None]

    # ---------------- FEATURES ---------------- #
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_df.values)

    X = X_scaled.astype(np.float32).reshape(len(X_scaled), 1, -1)
    y = y_np.astype(np.float32)

    # ---------------- SPLIT ---------------- #
    split = int(len(X) * (1 - TRAINING_TEST_SIZE))

    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    # ---------------- TENSORS (FIXED FLOAT32) ---------------- #
    train_loader = DataLoader(
        TensorDataset(
            torch.tensor(X_train, dtype=torch.float32),
            torch.tensor(y_train, dtype=torch.float32)
        ),
        batch_size=TRAINING_BATCH_SIZE,
        shuffle=True
    )

    val_loader = DataLoader(
        TensorDataset(
            torch.tensor(X_val, dtype=torch.float32),
            torch.tensor(y_val, dtype=torch.float32)
        ),
        batch_size=TRAINING_BATCH_SIZE
    )

    # ---------------- MODEL ---------------- #
    device = "cuda" if torch.cuda.is_available() else "cpu"

    model = LSTMRegressor(input_size=X.shape[2], output_size=num_assets).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    criterion = RMSELoss()
    early_stopping = EarlyStopping(patience=patience)

    # ---------------- TRAIN LOOP ---------------- #
    for epoch in range(epochs):

        model.train()
        train_loss = 0

        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)

            optimizer.zero_grad()
            preds = model(xb)
            loss = criterion(preds, yb)

            loss.backward()
            optimizer.step()

            train_loss += loss.item()

        model.eval()
        val_loss = 0

        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                preds = model(xb)
                val_loss += criterion(preds, yb).item()

        logger.info(f"Epoch {epoch+1}: Train={train_loss:.4f} Val={val_loss:.4f}")

        early_stopping(val_loss, model)
        if early_stopping.early_stop:
            logger.info("Early stopping triggered")
            break

    # ---------------- SAVE ---------------- #
    os.makedirs(MODELS_DIR, exist_ok=True)

    torch.save(model.state_dict(), MODEL_SAVE_FILE)
    joblib.dump(scaler, SCALER_X_SAVE_PATH)

    pd.DataFrame({"Ticker": tickers}).to_csv(TRAINED_TICKERS_PATH, index=False)
    pd.DataFrame({"feature_column": X_df.columns}).to_csv(TRAINED_MODEL_COLUMNS_PATH, index=False)

    # ---------------- EVALUATION ---------------- #
    model.eval()

    all_preds, all_targets = [], []

    with torch.no_grad():
        for xb, yb in val_loader:
            xb = xb.to(device)
            preds = model(xb)

            all_preds.append(preds.cpu().numpy())
            all_targets.append(yb.cpu().numpy())

    y_pred = np.vstack(all_preds)
    y_true = np.vstack(all_targets)

    mae = mean_absolute_error(y_true, y_pred)

    cos_sim = np.mean([
        cosine_similarity(
            y_true[i].reshape(1, -1),
            y_pred[i].reshape(1, -1)
        )[0][0]
        for i in range(len(y_true))
    ])

    logger.info("📊 FINAL METRICS")
    logger.info(f"MAE: {mae:.6f}")
    logger.info(f"Cosine Similarity: {cos_sim:.6f}")

    logger.info("✅ Training completed successfully")

    return model


# ---------------- RUN ---------------- #
if __name__ == "__main__":
    train_model(
        epochs=TRAINING_EPOCHS,
        patience=TRAINING_PATIENCE,
        learning_rate=learning_rate
    )
