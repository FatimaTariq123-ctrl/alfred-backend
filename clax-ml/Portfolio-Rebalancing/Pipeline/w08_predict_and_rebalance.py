# Pipeline/w08_predict_and_rebalance.py

import os
import logging
import pandas as pd
import numpy as np
import torch
import joblib
from typing import Optional, List, Dict, Any


# ---------------- Inlined configuration (from config.py) ---------------- #
BASE_OUTPUT_DIR = "outputs"
MODELS_DIR = "models"

PREDICTION_FEATURES_PATH = os.path.join(BASE_OUTPUT_DIR, "06_final_features.csv")
PREDICTED_WEIGHTS_OUTPUT_PATH = os.path.join(BASE_OUTPUT_DIR, "08_predicted_portfolio_weights.csv")
REBALANCE_INSTRUCTIONS_OUTPUT_PATH = os.path.join(BASE_OUTPUT_DIR, "08_rebalance_instructions.csv")

MODEL_SAVE_FILE = os.path.join(MODELS_DIR, "portfolio_weights_model.pth")
SCALER_X_SAVE_PATH = os.path.join(MODELS_DIR, "scaler_X.pkl")
SCALER_Y_SAVE_PATH = os.path.join(MODELS_DIR, "scaler_y.pkl")
TRAINED_TICKERS_PATH = os.path.join(MODELS_DIR, "trained_tickers.csv")
TRAINED_MODEL_COLUMNS_PATH = os.path.join(MODELS_DIR, "trained_model_columns.csv")

WEIGHT_CHANGE_BUY_THRESHOLD = 0.001
WEIGHT_CHANGE_SELL_THRESHOLD = -0.001


# ---------------- Logging setup (inlined from utils.logging.get_logger) ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------- Model definition (inlined from utils.model) ---------------- #
class LSTMRegressor(torch.nn.Module):
    def __init__(self, input_size, hidden_layer_size=300, output_size=1):
        super(LSTMRegressor, self).__init__()
        self.hidden_layer_size = hidden_layer_size

        # LSTM(300) -> LSTM(300) -> Dense(100) layers.
        self.lstm1 = torch.nn.LSTM(input_size, hidden_layer_size, batch_first=True)
        self.lstm2 = torch.nn.LSTM(hidden_layer_size, hidden_layer_size, batch_first=True)

        # Dense(100) layer with ReLU
        self.linear1 = torch.nn.Linear(hidden_layer_size, 100)
        self.relu = torch.nn.ReLU()

        # Output layer: Dense(num_assets) with Softmax
        self.linear2 = torch.nn.Linear(100, output_size)
        self.softmax = torch.nn.Softmax(dim=1)  # Softmax across the output features (weights)

    def forward(self, input_seq):
        # input_seq: (batch_size, seq_len, input_size)
        lstm_out1, _ = self.lstm1(input_seq)
        lstm_out2, _ = self.lstm2(lstm_out1)

        # Take the output of the last time step
        last_time_step_out = lstm_out2[:, -1, :]

        # Dense(100) -> ReLU
        dense1_out = self.relu(self.linear1(last_time_step_out))

        # Dense(output_size) -> Softmax
        output = self.softmax(self.linear2(dense1_out))

        return output


def load_trained_tickers() -> Optional[List[str]]:
    """
    Load the ticker universe that the model was trained on, if available.
    """
    if not os.path.exists(TRAINED_TICKERS_PATH):
        logger.warning(
            f"Trained tickers file not found at {TRAINED_TICKERS_PATH}. "
            "Ticker-level comparison will be limited."
        )
        return None
    try:
        df_tickers = pd.read_csv(TRAINED_TICKERS_PATH)
        if "Ticker" not in df_tickers.columns:
            logger.warning(
                f"Trained tickers file at {TRAINED_TICKERS_PATH} is missing 'Ticker' column. "
                "Ignoring its contents."
            )
            return None
        tickers = df_tickers["Ticker"].astype(str).tolist()
        logger.info(f"Loaded trained ticker universe ({len(tickers)} tickers) from {TRAINED_TICKERS_PATH}")
        return tickers
    except Exception as e:
        logger.error(f"Error loading trained tickers from {TRAINED_TICKERS_PATH}: {e}", exc_info=True)
        return None

def load_model_and_scalers(input_size: int):
    """Loads the trained model and scalers.

    Notes:
    - For weights model, we only use scaler_X. Weights are softmax outputs (0-1).
    """
    try:
        scaler_X = joblib.load(SCALER_X_SAVE_PATH)

        # Infer output size from trained tickers
        trained_tickers = load_trained_tickers()
        if trained_tickers:
            output_size = len(trained_tickers)
        else:
            raise RuntimeError("Could not load trained tickers to infer output size.")

        model = LSTMRegressor(input_size=input_size, output_size=output_size)
        model.load_state_dict(torch.load(MODEL_SAVE_FILE))
        model.eval()

        logger.info("Loaded model and scaler_X.")
        return model, scaler_X, None  # No scaler_y for weights
    except Exception as e:
        logger.error(f"Error loading model or scalers: {e}", exc_info=True)
        return None, None, None

def predict_weights(date: Optional[str] = None) -> pd.DataFrame:
    """
    Loads latest features and makes predictions for a given date.
    """
    logger.info(f"Starting weight prediction for date: {date or 'latest'}")
    
    try:
        # Load expected columns and tickers early
        expected_columns = pd.read_csv(TRAINED_MODEL_COLUMNS_PATH)['feature_column'].tolist()
        trained_tickers = load_trained_tickers()
        if not trained_tickers:
            logger.error("Could not load the list of tickers the model was trained on. Aborting.")
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"Could not load model training metadata (columns or tickers): {e}. "
                     "Please retrain the model (w07).", exc_info=True)
        return pd.DataFrame()

    try:
        df = pd.read_csv(PREDICTION_FEATURES_PATH, parse_dates=["Date"])
    except Exception as e:
        logger.error(f"Error loading features file: {e}")
        return pd.DataFrame()

    if date:
        prediction_date = pd.to_datetime(date)
    else:
        prediction_date = df['Date'].max()
    
    df_latest = df[df['Date'] == prediction_date].copy()
    
    if df_latest.empty:
        logger.error(f"No feature data found for date {prediction_date.date()}.")
        return pd.DataFrame()

    feature_cols = [c for c in df_latest.columns if c.endswith("_ecod") or c.startswith("PCA_")]
    
    df_features_pivoted = df_latest.pivot_table(index='Date', columns='Ticker', values=feature_cols)
    df_features_pivoted.columns = ['_'.join(col).strip() for col in df_features_pivoted.columns.values]
    
    # Align columns with the trained model
    X_wide_df = df_features_pivoted.reindex(columns=expected_columns).fillna(0)
    
    # Log if there were missing tickers on this date
    missing_cols = set(expected_columns) - set(df_features_pivoted.columns)
    if missing_cols:
        # Infer tickers from column names to give a more helpful warning
        missing_tickers = sorted(list(set([c.split('_')[0] for c in missing_cols if c.split('_')[0] in trained_tickers])))
        if missing_tickers:
            logger.warning(f"Features for date {prediction_date.date()} were missing for these tickers: {missing_tickers}. "
                           "Their feature values have been imputed as 0 for this prediction.")

    input_size = len(expected_columns)
    model, scaler_X, _ = load_model_and_scalers(input_size=input_size)  # No scaler_y
    if not all([model, scaler_X]):
        return pd.DataFrame()

    tickers_order = trained_tickers.copy() # Use the definitive order from training
    
    X_np_latest = X_wide_df.values.astype(np.float32)
    X_scaled_latest = scaler_X.transform(X_np_latest)
    X_reshaped_latest = np.reshape(X_scaled_latest, (1, 1, X_scaled_latest.shape[1]))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    with torch.no_grad():
        X_tensor = torch.tensor(X_reshaped_latest).to(device)
        predicted_weights = model(X_tensor).cpu().numpy().flatten()

    # Weights are already 0-1 from softmax, no need to inverse transform
    predicted_weights[predicted_weights < 0] = 0  # Ensure non-negative
    predicted_weights /= predicted_weights.sum()  # Renormalize to sum to 1

    predicted_weights_df = pd.DataFrame({
        'Date': prediction_date,
        'Ticker': tickers_order,
        'Predicted_Weight': predicted_weights
    })
    
    predicted_weights_df.to_csv(PREDICTED_WEIGHTS_OUTPUT_PATH, index=False)
    logger.info(f"Saved predicted weights to {PREDICTED_WEIGHTS_OUTPUT_PATH}.")
    
    return predicted_weights_df

def generate_rebalance_instructions(
    predicted_weights_df: pd.DataFrame, 
    current_holdings: Dict[str, float]
) -> List[Dict[str, Any]]:
    """
    Generates rebalancing instructions based on predicted weights and current holdings.
    """
    current_holdings_df = pd.DataFrame(list(current_holdings.items()), columns=['Ticker', 'Current_Weight'])
    
    rebalance_df = pd.merge(predicted_weights_df, current_holdings_df, on='Ticker', how='outer').fillna(0)
    rebalance_df['Weight_Change'] = rebalance_df['Predicted_Weight'] - rebalance_df['Current_Weight']
    
    instructions = []
    for _, row in rebalance_df.iterrows():
        action = "HOLD"
        if row['Weight_Change'] > WEIGHT_CHANGE_BUY_THRESHOLD:
            action = "BUY"
        elif row['Weight_Change'] < WEIGHT_CHANGE_SELL_THRESHOLD:
            action = "SELL"
        
        if action != "HOLD":
            instructions.append({
                'Ticker': row['Ticker'],
                'Action': action,
                'Weight_Change': row['Weight_Change']
            })
            
    rebalance_instructions_df = pd.DataFrame(instructions)
    if not rebalance_instructions_df.empty:
        rebalance_instructions_df.to_csv(REBALANCE_INSTRUCTIONS_OUTPUT_PATH, index=False)
        logger.info(f"Saved rebalancing instructions to {REBALANCE_INSTRUCTIONS_OUTPUT_PATH}.")
    
    return instructions

def main():
    """
    Main function to run the prediction and rebalancing pipeline.
    """
    logger.info("🚀 Starting Prediction and Rebalancing Pipeline 🚀")
    predicted_weights = predict_weights()
    
    if not predicted_weights.empty:
        # Simulate current holdings for the standalone run
        simulated_holdings = {ticker: 1/len(predicted_weights) for ticker in predicted_weights['Ticker']}
        generate_rebalance_instructions(predicted_weights, simulated_holdings)
    
    logger.info("✅ Prediction and Rebalancing Pipeline Completed.")

if __name__ == "__main__":
    main()
