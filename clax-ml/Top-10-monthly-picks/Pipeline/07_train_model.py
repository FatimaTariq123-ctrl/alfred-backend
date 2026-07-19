# Pipeline/07_train_model.py
import os
import logging
import math
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import ndcg_score
import joblib

# ----------------- Constants ----------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
FEATURE_CSV = "outputs/06_final_features.csv"
MODEL_PATH = "models/top10_model.pth"
SCALER_PATH = "models/feature_scaler.joblib"
SEQUENCE_LENGTH = 66  # Approx. 3 months of trading days
BATCH_SIZE = 16
MAX_EPOCHS = 100
PATIENCE = 5
LEARNING_RATE = 1e-6

# ----------------- LambdaRank Loss ----------------- #
class LambdaRankLoss(nn.Module):
    def __init__(self, sigma=1.0):
        super().__init__()
        self.sigma = sigma

    def forward(self, y_pred, y_true):
        y_pred = y_pred.squeeze()
        y_true = y_true.squeeze()
        y_pred_diff = y_pred.unsqueeze(1) - y_pred.unsqueeze(0)
        y_true_diff = y_true.unsqueeze(1) - y_true.unsqueeze(0)
        y_true_sign = torch.sign(y_true_diff)
        lambdas = self.sigma * (
            0.5 * (1 - y_true_sign) - 1 / (1 + torch.exp(self.sigma * y_pred_diff))
        )
        loss = torch.sum(torch.abs(lambdas))
        return loss

# ----------------- Model Architecture ----------------- #
class Top10LSTM(nn.Module):
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

# ----------------- Data Preparation ----------------- #
def create_sequences(data, feature_cols, label_col, sequence_length):
    logging.info("Starting sequence creation...")
    sequences = []
    labels = []
    query_ids = []

    tickers = data['Ticker'].unique()
    logging.info(f"Processing {len(tickers)} unique tickers...")
    
    for idx, (ticker, group) in enumerate(data.groupby('Ticker')):
        if idx % 50 == 0:
            logging.info(f"Processing ticker {idx}/{len(tickers)}: {ticker}")

        df = group.sort_values('Date')
        if len(df) >= sequence_length:
            for i in range(len(df) - sequence_length + 1):
                sequences.append(df.iloc[i:i+sequence_length][feature_cols].values)
                labels.append(df.iloc[i+sequence_length-1][label_col])
                query_ids.append(df.iloc[i+sequence_length-1]['Date'])
    
    logging.info(f"Sequence creation complete. Total sequences: {len(sequences)}")
    return np.array(sequences, dtype=np.float32), np.array(labels, dtype=np.float32), pd.to_datetime(query_ids)

class QueryDataset(Dataset):
    def __init__(self, X, y, qids):
        self.X = X
        self.y = y
        self.qids = qids
        self.unique_qids = np.unique(self.qids)

    def __len__(self):
        return len(self.unique_qids)

    def __getitem__(self, idx):
        qid = self.unique_qids[idx]
        mask = self.qids == qid
        return torch.tensor(self.X[mask]), torch.tensor(self.y[mask])

def custom_collate(batch):
    return batch

def model_has_invalid_params(model: nn.Module) -> bool:
    for name, param in model.named_parameters():
        if not torch.isfinite(param).all():
            logging.error(f"Detected non-finite values in parameter '{name}'.")
            return True
    return False

# ----------------- Early Stopping ----------------- #
class EarlyStopping:
    def __init__(self, patience=5, min_delta=0, model_path=MODEL_PATH):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_loss = float('inf')
        self.model_path = model_path

    def __call__(self, val_loss, model):
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter = 0
            logging.info("Validation loss improved. Saving model.")
            torch.save(model.state_dict(), self.model_path)
        else:
            self.counter += 1
            if self.counter >= self.patience:
                logging.info("Early stopping triggered.")
                return True
        return False

# ----------------- Training Pipeline ----------------- #
def run_training():
    logging.info("Starting model training pipeline...")
    logging.info(f"Using device: {DEVICE}")

    # Load data
    logging.info(f"Loading data from {FEATURE_CSV}...")
    df = pd.read_csv(FEATURE_CSV, parse_dates=['Date'])
    logging.info(f"Data loaded. Shape: {df.shape}")

    # Feature selection & scaling
    logging.info("Selecting features...")
    feature_cols = [c for c in df.columns if '_ecod' in c or '_sin' in c or 'PCA_' in c]
    logging.info(f"Selected {len(feature_cols)} features")
    label_col = 'ForwardReturn'
    logging.info(f"Dropping rows with missing {label_col}...")
    df = df.dropna(subset=[label_col])
    logging.info(f"Data shape after dropping missing labels: {df.shape}")

    logging.info("Scaling features...")
    scaler = StandardScaler()
    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan)
    feature_nan_count = df[feature_cols].isna().sum().sum()
    if feature_nan_count > 0:
        logging.warning(f"Detected {feature_nan_count} NaNs in feature columns. Dropping affected rows before scaling.")
        before_rows = len(df)
        df = df.dropna(subset=feature_cols)
        logging.info(f"Dropped {before_rows - len(df)} rows. New shape: {df.shape}")
    df[feature_cols] = scaler.fit_transform(df[feature_cols])
    os.makedirs(os.path.dirname(SCALER_PATH), exist_ok=True)
    joblib.dump(scaler, SCALER_PATH)
    logging.info(f"Feature scaler saved to {SCALER_PATH}")

    # Create sequences
    X, y, qids = create_sequences(df, feature_cols, label_col, SEQUENCE_LENGTH)
    logging.info(f"Created sequences. X shape: {X.shape}, y shape: {y.shape}")

    # Train/Validation split
    logging.info("Creating train/validation split...")
    unique_dates = np.unique(qids)
    train_cutoff = unique_dates[int(len(unique_dates) * 0.8)]
    logging.info(f"Train cutoff date: {train_cutoff}")

    train_mask = qids <= train_cutoff
    val_mask = qids > train_cutoff
    logging.info(f"Train samples: {train_mask.sum()}, Val samples: {val_mask.sum()}")

    train_dataset = QueryDataset(X[train_mask], y[train_mask], qids[train_mask])
    val_dataset = QueryDataset(X[val_mask], y[val_mask], qids[val_mask])
    logging.info(f"Train queries: {len(train_dataset)}, Val queries: {len(val_dataset)}")

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=custom_collate)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=custom_collate)
    logging.info("Data loaders created successfully")

    # Model, Loss, Optimizer
    logging.info("Initializing model...")
    model = Top10LSTM(input_dim=X.shape[2]).to(DEVICE)
    logging.info(f"Model initialized with {sum(p.numel() for p in model.parameters())} parameters")
    criterion = LambdaRankLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-3)
    early_stopping = EarlyStopping(patience=PATIENCE)
    logging.info("Optimizer and loss function ready")

    # Training loop
    logging.info("Starting training loop...")
    for epoch in range(MAX_EPOCHS):
        logging.info(f"\n{'='*50}")
        logging.info(f"Starting Epoch {epoch+1}/{MAX_EPOCHS}")
        logging.info(f"{'='*50}")

        model.train()
        total_train_loss = 0

        for batch_idx, batch in enumerate(train_loader):
            if batch_idx % 10 == 0:
                logging.info(f"Training batch {batch_idx}/{len(train_loader)}")

            batch_loss = 0
            for x_query, y_query in batch:
                x_query = x_query.to(DEVICE)
                y_query = y_query.to(DEVICE)

                optimizer.zero_grad()
                y_pred = model(x_query)
                loss = criterion(y_pred, y_query)
                if not math.isfinite(loss.item()):
                    raise ValueError(f"Encountered non-finite training loss at epoch {epoch+1}, batch {batch_idx}.")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=2.0)  # Gradient clipper max_norm=2
                optimizer.step()
                batch_loss += loss.item()

            total_train_loss += batch_loss

        avg_train_loss = total_train_loss / len(train_loader)
        logging.info(f"Training complete for epoch {epoch+1}. Avg train loss: {avg_train_loss:.4f}")

        # Validation
        logging.info("Starting validation...")
        model.eval()
        total_val_loss = 0
        total_ndcg = 0
        query_count = 0

        with torch.no_grad():
            for batch_idx, batch in enumerate(val_loader):
                if batch_idx % 10 == 0:
                    logging.info(f"Validation batch {batch_idx}/{len(val_loader)}")

                for x_query, y_query in batch:
                    x_query = x_query.to(DEVICE)
                    y_query = y_query.to(DEVICE)

                    y_pred = model(x_query)
                    loss = criterion(y_pred, y_query)
                    total_val_loss += loss.item()

                    # Computing NDCG@10 (shift y_true if negative values exist)
                    y_true_np = y_query.cpu().numpy().reshape(1, -1)
                    y_pred_np = y_pred.cpu().numpy().reshape(1, -1)
                    min_val = y_true_np.min()
                    if min_val < 0:
                        y_true_np = y_true_np - min_val  # shift to make non-negative
                    ndcg = ndcg_score(y_true_np, y_pred_np, k=10)

                    total_ndcg += ndcg
                    query_count += 1

        avg_val_loss = total_val_loss / len(val_loader)
        avg_ndcg = total_ndcg / query_count if query_count > 0 else 0

        logging.info(f"Validation complete. Avg val loss: {avg_val_loss:.4f}")
        logging.info(f"Validation NDCG@10: {avg_ndcg:.4f}")
        logging.info(f"Epoch {epoch+1}/{MAX_EPOCHS} - Train Loss: {avg_train_loss:.4f}, Val Loss: {avg_val_loss:.4f}, NDCG@10: {avg_ndcg:.4f}")

        # Early stopping monitors **validation loss**
        if early_stopping(avg_val_loss, model):
            break

    logging.info("Training finished.")
    if model_has_invalid_params(model):
        raise ValueError("Final model parameters contain NaN or Inf values. Aborting save.")

    torch.save(model.state_dict(), MODEL_PATH)
    logging.info(f"Final model from last epoch saved at {MODEL_PATH}")
    logging.info(f"Final validation NDCG@10: {avg_ndcg:.4f}") #NDCG@10 for model evaluation

if __name__ == "__main__":
    run_training()
