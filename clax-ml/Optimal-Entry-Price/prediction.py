# prediction.py
# -----------------------------
import logging
import pandas as pd
import numpy as np
import onnxruntime as ort
import joblib
from datetime import timezone

# Import feature engineering functions
import Pipeline.w06_Feature_Engg as fe

# Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_merged_data():
    """
    Loads the merged historical data.
    """
    logging.info("Loading historical data...")
    try:
        stock_data = pd.read_csv("outputs/02_Yahoo_Stocks.csv", parse_dates=["date"])
        stock_data.rename(columns={'date': 'Date'}, inplace=True)
        macro_data = pd.read_csv("outputs/03_fred_features.csv", parse_dates=["Date"])
        
        merged_data = pd.merge(stock_data, macro_data, on="Date", how="left")
        merged_data.sort_values(by=["Ticker", "Date"], inplace=True)
        
        # Group by ticker and forward-fill, then back-fill
        merged_data = merged_data.groupby('Ticker').apply(lambda group: group.ffill().bfill()).reset_index(drop=True)
        
        logging.info("Historical stock and macro data loaded.")
        return merged_data
    except FileNotFoundError as e:
        logging.error(f"Failed to load historical data from CSV: {e}. Make sure 'outputs/02_Yahoo_Stocks.csv' and 'outputs/03_fred_features.csv' exist.")
        raise
    except Exception as e:
        logging.error(f"An error occurred while loading or processing historical data: {e}")
        raise

class PredictionService:
    def __init__(self, model_path="models/oep_regressor.onnx", scaler_x_path="models/scaler_X.pkl", scaler_y_path="models/scaler_y.pkl", pca_path="outputs/pca_model.joblib"):
        logging.info("Initializing Prediction Service...")
        
        try:
            # Load scalers and PCA first
            self.scaler_X = joblib.load(scaler_x_path)
            self.scaler_y = joblib.load(scaler_y_path)
            self.pca_model = joblib.load(pca_path)
        except Exception as e:
            logging.error(f"Failed to load scalers or PCA model: {e}")
            raise

        try:
            # Load model
            self.model = self.load_model(model_path)
        except Exception as e:
            logging.error(f"Failed to load model from {model_path}: {e}")
            raise
        
        # Load data
        self.merged_data = get_merged_data()

        try:
            # Load feature names from the training data
            logging.info("Loading feature names from training source...")
            feature_df = pd.read_csv("outputs/06_final_features.csv", nrows=0) # Read only header
            drop_cols = ["Date", "Ticker", "Close", "Target"]
            self.feature_names = [col for col in feature_df.columns if col not in drop_cols]
            logging.info(f"Loaded {len(self.feature_names)} feature names.")
        except Exception as e:
            logging.error(f"Failed to load feature names from 'outputs/06_final_features.csv': {e}")
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

    def get_ticker_data(self, ticker: str):
        """
        Extracts historical data for a single ticker from the pre-loaded dataframe.
        """
        logging.info(f"Extracting historical data for {ticker}...")
        ticker_df = self.merged_data[self.merged_data['Ticker'] == ticker].copy()
        if ticker_df.empty:
            raise ValueError(f"No data found for ticker {ticker} in the loaded CSV files.")
        
        ticker_df.sort_values(by='Date', inplace=True)
        logging.info(f"Found {len(ticker_df)} records for {ticker}.")
        return ticker_df

    def create_feature_vector(self, df: pd.DataFrame, ticker: str, trade_direction: str):
        """
        Creates the full feature vector for a single ticker for the most recent day.
        """
        import time
        logging.info(f"Creating feature vector for {ticker} from historical data...")
        
        df['Direction'] = 1 if trade_direction == 'buy' else 0

        try:
            # 1. Apply feature engineering
            logging.info("Applying feature engineering steps...")
            start_time = time.time()
            df = fe.add_rolling_pct_changes(df)
            logging.info(f"add_rolling_pct_changes took {time.time() - start_time:.2f}s")
            start_time = time.time()
            df = fe.add_macro_raw_differences(df)
            logging.info(f"add_macro_raw_differences took {time.time() - start_time:.2f}s")
            start_time = time.time()
            df = fe.add_cycle_encodings(df)
            logging.info(f"add_cycle_encodings took {time.time() - start_time:.2f}s")
            start_time = time.time()
            df = fe.add_sentiment_dispersion(df) # Note: This will have limited meaning for a single stock
            logging.info(f"add_sentiment_dispersion took {time.time() - start_time:.2f}s")
            start_time = time.time()
            df = fe.add_seasonality_features(df)
            logging.info(f"add_seasonality_features took {time.time() - start_time:.2f}s")
            logging.info("Feature engineering steps applied.")

            start_time = time.time()
            ecod_cols = [c for c in df.columns if any(x in c for x in ["Pct_", "diff_", "Sentiment", "Dispersion"])]
            ecod_cols.append('Direction')
            df = fe.ecod_normalization(df, ecod_cols)
            logging.info(f"ecod_normalization took {time.time() - start_time:.2f}s")
            
            # Replace inf values and fill NaNs before PCA and scaling
            df.replace([np.inf, -np.inf], np.nan, inplace=True)
            df.fillna(0, inplace=True)
            logging.info("Infinite and NaN values handled.")
        except Exception as e:
            logging.error(f"Error during feature engineering for {ticker}: {e}")
            raise

        try:
            # 2. Apply PCA transform
            start_time = time.time()
            logging.info("Applying PCA transformation...")
            feature_cols = [c for c in df.columns if c.endswith("_ecod")]
            X_pca_features = df[feature_cols]
            
            # Ensure columns match what PCA was trained on
            pca_feature_names = self.pca_model.feature_names_in_
            X_pca_features = X_pca_features.reindex(columns=pca_feature_names, fill_value=0)

            pca_data = self.pca_model.transform(X_pca_features)
            pca_df = pd.DataFrame(pca_data, columns=[f"PCA_{i+1}" for i in range(pca_data.shape[1])], index=df.index)
            
            final_df = pd.concat([df, pca_df], axis=1)
            logging.info(f"PCA transformation took {time.time() - start_time:.2f}s")
        except Exception as e:
            logging.error(f"Error during PCA transformation for {ticker}: {e}")
            raise
        
        try:
            # 3. Select the latest data point
            latest_features = final_df.iloc[-1:]
            
            # 4. Align columns with the training scaler
            X_df = latest_features.drop(columns=["Date", "Ticker", "Close"])
            X_df = X_df.reindex(columns=self.feature_names, fill_value=0)
        except Exception as e:
            logging.error(f"Error during final feature selection and alignment for {ticker}: {e}")
            raise

        logging.info(f"Feature vector created successfully for {ticker}.")
        return X_df.values.astype(np.float32)

    def predict(self, ticker: str, trade_direction: str):
        """
        Predicts the optimal entry price for a given stock ticker using historical CSV data.
        """
        logging.info(f"Generating prediction for {ticker} ({trade_direction})...")
        
        try:
            # 1. Get historical data and create feature vector
            ticker_data = self.get_ticker_data(ticker)
            feature_vector = self.create_feature_vector(ticker_data.copy(), ticker, trade_direction) # Pass a copy to avoid side effects
            logging.info(f"Feature vector created for {ticker}. Shape: {feature_vector.shape}")
        except Exception as e:
            logging.error(f"Failed to create feature vector for {ticker}: {e}")
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
            # 6. Get the most recent price and compute the limit price
            current_price = float(ticker_data['Close'].iloc[-1])
            logging.info(f"Most recent price for {ticker} from CSV data: {current_price:.2f}")

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

        ticker_data = self.get_ticker_data(ticker)
        last_dt = pd.to_datetime(ticker_data["Date"].iloc[-1], utc=True)
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


