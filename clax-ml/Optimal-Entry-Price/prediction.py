# prediction.py
# -----------------------------
import logging
import pandas as pd
import numpy as np
import onnxruntime as ort
import joblib
from datetime import timezone
import os
import sys

# Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

try:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from shared_db import load_from_db
except ImportError:
    pass

class PredictionService:
    def __init__(self, model_path="models/oep_regressor.onnx", scaler_x_path="models/scaler_X.pkl", scaler_y_path="models/scaler_y.pkl", pca_path="outputs/pca_model.joblib"):
        logging.info("Initializing Prediction Service...")
        
        try:
            # Load scalers
            self.scaler_X = joblib.load(scaler_x_path)
            self.scaler_y = joblib.load(scaler_y_path)
            # PCA is now handled entirely within the data pipeline and saved to the DB
        except Exception as e:
            logging.error(f"Failed to load scalers: {e}")
            raise

        try:
            # Load model
            self.model = self.load_model(model_path)
        except Exception as e:
            logging.error(f"Failed to load model from {model_path}: {e}")
            raise
        
        try:
            # Ensure feature names match training scaler
            self.feature_names = list(self.scaler_X.feature_names_in_)
            logging.info(f"Loaded {len(self.feature_names)} feature names from scaler.")
        except Exception as e:
            logging.error(f"Failed to load feature names from scaler: {e}")
            raise

        logging.info("Prediction Service initialized successfully.")

    def load_model(self, model_path):
        """Loads the ONNX Runtime inference session."""
        logging.info(f"Attempting to load model from {model_path}...")
        try:
            model = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            logging.info(f"Model successfully loaded from {model_path}.")
            return model
        except FileNotFoundError:
            logging.error(f"Model file not found at {model_path}.")
            raise
        except Exception as e:
            logging.error(f"Error loading ONNX model from {model_path}: {e}")
            raise

    def get_feature_vector_from_db(self, ticker: str, trade_direction: str):
        """
        Retrieves the exact, pre-computed single-row feature slice from PostgreSQL.
        """
        logging.info(f"Extracting historical feature data for {ticker} from DB...")
        direction_val = 1 if trade_direction == 'buy' else 0
        
        query = '''
            SELECT * FROM clax_oep_features 
            WHERE "Ticker" = %(ticker)s AND "Direction" = %(direction)s 
            ORDER BY "Date" DESC LIMIT 1
        '''
        try:
            df = load_from_db(query, params={"ticker": ticker, "direction": direction_val})
        except Exception as e:
            logging.error(f"Database error during feature retrieval for {ticker}: {e}")
            raise
            
        if df.empty:
            raise ValueError(f"No precomputed feature data found in PostgreSQL for ticker {ticker} ({trade_direction}).")
        
        return df

    def predict(self, ticker: str, trade_direction: str):
        """
        Predicts the optimal entry price for a given stock ticker using pre-computed DB features.
        """
        logging.info(f"Generating prediction for {ticker} ({trade_direction})...")
        
        try:
            # 1. Get pre-computed feature slice from DB
            latest_features = self.get_feature_vector_from_db(ticker, trade_direction)
            current_price = float(latest_features['Close'].iloc[0])
            last_date = latest_features['Date'].iloc[0]
            
            # Align columns with the training scaler
            X_df = latest_features.drop(columns=["Date", "Ticker", "Close", "Target", "ForwardReturn", "EntryTarget", "Tradable", "Label"], errors='ignore')
            X_df = X_df.reindex(columns=self.feature_names, fill_value=0)
            feature_vector = X_df.values.astype(np.float32)
            logging.info(f"Feature slice extracted for {ticker}. Shape: {feature_vector.shape}")
        except Exception as e:
            logging.error(f"Failed to extract features for {ticker}: {e}")
            raise
        
        try:
            # 2. Scale features
            X_scaled = self.scaler_X.transform(feature_vector)
            logging.info(f"Features scaled. Scaled shape: {X_scaled.shape}")
            
            # 3. Reshape for LSTM
            X_reshaped = np.reshape(X_scaled, (X_scaled.shape[0], 1, X_scaled.shape[1]))
            logging.info(f"Features reshaped for LSTM. Reshaped shape: {X_reshaped.shape}")
        except Exception as e:
            logging.error(f"Error during feature scaling or reshaping for {ticker}: {e}")
            raise
        
        try:
            # 4. Predict with the model (directional activation)
            input_name = self.model.get_inputs()[0].name
            prediction_scaled = self.model.run(None, {input_name: X_reshaped.astype(np.float32)})[0]
            if trade_direction == "buy":
                prediction_scaled = np.maximum(prediction_scaled, 0.0)
            else:
                prediction_scaled = -np.abs(prediction_scaled)
            logging.info(f"Model prediction completed. Scaled prediction: {float(prediction_scaled[0][0]):.4f}")
        except Exception as e:
            logging.error(f"Error during model prediction for {ticker}: {e}")
            raise

        try:
            # 5. Inverse transform the prediction to percent-gap target
            prediction = self.scaler_y.inverse_transform(prediction_scaled)
            target_pct = float(prediction[0][0])
            logging.info(f"Prediction inverse transformed. Target pct: {target_pct:.6f}")
        except Exception as e:
            logging.error(f"Error during inverse transformation of prediction for {ticker}: {e}")
            raise

        try:
            # 6. Compute the limit price
            denom = 1.0 + target_pct
            if denom <= 0:
                denom = 1e-6
            limit_price = current_price / denom
            logging.info(f"Calculated limit price: {limit_price:.2f}")
        except Exception as e:
            logging.error(f"Error during current price fetching or limit price calculation for {ticker}: {e}")
            raise

        logging.info(
            f"Prediction for {ticker}: TargetPct={target_pct:.6f}, LimitPrice={limit_price:.2f} (Current: {current_price:.2f})"
        )

        return {
            "ticker": ticker,
            "trade_direction": trade_direction,
            "current_price": float(round(current_price, 2)),
            "predicted_target_pct": float(target_pct),
            "limit_price": float(round(limit_price, 2)),
            "last_date": last_date
        }

    def predict_optimal_entry_exit_signal(self, ticker: str):
        """
        Returns a unified buy/sell signal with price, confidence, and last-updated timestamp.
        """
        ticker = ticker.upper()

        buy_result = self.predict(ticker, "buy")
        sell_result = self.predict(ticker, "sell")

        current_price = float(buy_result["current_price"])
        buy_price = float(buy_result["limit_price"])
        sell_price = float(sell_result["limit_price"])

        buy_target = float(buy_result["predicted_target_pct"])
        sell_target = float(sell_result["predicted_target_pct"])

        buy_edge = max(0.0, buy_target)
        sell_edge = max(0.0, -sell_target)

        if buy_edge >= sell_edge:
            signal_type = "buy"
            signal_price = buy_price
            chosen_edge = buy_edge
        else:
            signal_type = "sell"
            signal_price = sell_price
            chosen_edge = sell_edge

        # Confidence heuristic: convert edge strength to [0.50, 0.99].
        confidence = min(0.99, 0.50 + (chosen_edge * 5.0))

        last_dt = pd.to_datetime(buy_result["last_date"], utc=True)
        if last_dt.tzinfo is None:
            last_dt = last_dt.tz_localize(timezone.utc)
        last_updated = last_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "status": "success",
            "data": {
                "ticker": ticker,
                "signal": {
                    "type": signal_type,
                    "price": float(round(signal_price, 2)),
                    "confidence": float(round(confidence, 2)),
                },
                "last_updated": last_updated,
            },
        }


