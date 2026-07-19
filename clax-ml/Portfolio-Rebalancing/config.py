# config.py
import os
from datetime import datetime
import pandas as pd # For pd.DateOffset

# --- Project Paths ---
BASE_OUTPUT_DIR = "outputs"
MODELS_DIR = "models"
LAST_RUN_LOG = "last_run.log"

# --- Data Loaders ---
# w01_SP500_Tickers_and_Membership.py
SP500_TICKERS_LIST_PATH = os.path.join(BASE_OUTPUT_DIR, "01_SP500_Tickers_list.csv")
SP500_MEMBERSHIP_MATRIX_PATH = os.path.join(BASE_OUTPUT_DIR, "01_SP500_membership_matrix.csv")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

# w02_Yahoo.py
REBALANCE_PERIOD_DAYS = 30
TOP_N_LIQUID = 20
LIQUIDITY_LOOKBACK_DAYS = 22
YAHOO_DATA_START_DATE = (datetime.today() - pd.DateOffset(years=10)).strftime('%Y-%m-%d')
YAHOO_STOCKS_OUTPUT_FILE = os.path.join(BASE_OUTPUT_DIR, "02_Yahoo_Stocks.csv")
YAHOO_EXTRAS_OUTPUT_FILE = os.path.join(BASE_OUTPUT_DIR, "02_Yahoo_Extras.csv")
YAHOO_UNIVERSE_OUTPUT_FILE = os.path.join(BASE_OUTPUT_DIR, "02_top50_universe.csv")
YAHOO_DOWNLOAD_FAILURE_RATE_THRESHOLD = 0.10

# w03_Fred.py
FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_DATA_START_DATE = (datetime.today() - pd.DateOffset(years=10)).strftime('%Y-%m-%d')
FRED_FEATURES_OUTPUT_FILE = os.path.join(BASE_OUTPUT_DIR, "03_fred_features.csv")
FRED_SERIES_MAPPING = {
    "10Y_Yield": "GS10",
    "5Y_Yield": "DGS5",
    "2Y_Yield": "DGS2",
    "Unemployment": "UNRATE",
    "CPI": "CPIAUCSL"
}

# --- Pipeline ---
# w04a_Markowitz_Labels.py
MARKOWITZ_LABELS_OUTPUT_PATH = os.path.join(BASE_OUTPUT_DIR, "04_markowitz_labels.csv")
MARKOWITZ_LOOKBACK_YEARS = 1
MARKOWITZ_TARGET_ANNUAL_RETURN = 0.20
MARKOWITZ_REBALANCE_FREQ_DAYS = 22
MARKOWITZ_MIN_HISTORY_DAYS = 100 # for pypfopt
MARKOWITZ_ANNUAL_TRADING_DAYS = 252 # for pypfopt frequency

# w05_merge_price_macro.py
MERGED_PANEL_PATH = MARKOWITZ_LABELS_OUTPUT_PATH # Input to w05 is output of w04a
MERGED_FRED_PATH = FRED_FEATURES_OUTPUT_FILE
MERGED_EXTRAS_PATH = YAHOO_EXTRAS_OUTPUT_FILE
MERGED_OUT_PATH = os.path.join(BASE_OUTPUT_DIR, "05_label_macro_features_OEP.csv")
MERGED_SUMMARY_PATH = os.path.join(BASE_OUTPUT_DIR, "05_label_macro_features_summary_OEP.csv")
MACRO_DIFF_HORIZONS = (1, 12, 24)
MACRO_INTEREST_KEYWORDS = ("rate", "yield", "interest", "treasury", "ffr", "fedfund", "bond")
MACRO_UNEMPLOY_KEYWORDS = ("unemp", "unemployment", "UNRATE")

# w06_Feature_Engg.py
FEATURES_INPUT_PATH = MERGED_OUT_PATH # Input to w06 is output of w05
FINAL_FEATURES_OUTPUT_PATH = os.path.join(BASE_OUTPUT_DIR, "06_final_features.csv")
PCA_MODEL_SAVE_PATH = os.path.join(MODELS_DIR, "pca_model.joblib")
PCT_CHANGE_HORIZONS = [22, 132, 252]
MACRO_EXCLUDE_PCT_CHANGE = ("UNRATE", "FEDFUNDS")
ECOD_WINDOW_SIZE = 504
PCA_VARIANCE_THRESHOLD = 0.95

# w07_train_model.py
TRAINING_FEATURES_PATH = FINAL_FEATURES_OUTPUT_PATH # Input to w07 is output of w06
TRAINING_EPOCHS = 100
TRAINING_BATCH_SIZE = 256
TRAINING_LEARNING_RATE = 1e-3
TRAINING_TEST_SIZE = 0.2
TRAINING_RANDOM_STATE = 42
TRAINING_PATIENCE = 30
MODEL_SAVE_FILE = os.path.join(MODELS_DIR, "portfolio_weights_model.pth")
SCALER_X_SAVE_PATH = os.path.join(MODELS_DIR, "scaler_X.pkl")
SCALER_Y_SAVE_PATH = os.path.join(MODELS_DIR, "scaler_y.pkl")

# w08_predict_and_rebalance.py
PREDICTION_FEATURES_PATH = FINAL_FEATURES_OUTPUT_PATH # Input to w08 is output of w06
PREDICTED_WEIGHTS_OUTPUT_PATH = os.path.join(BASE_OUTPUT_DIR, "08_predicted_portfolio_weights.csv")
REBALANCE_INSTRUCTIONS_OUTPUT_PATH = os.path.join(BASE_OUTPUT_DIR, "08_rebalance_instructions.csv")
WEIGHT_CHANGE_BUY_THRESHOLD = 0.001
WEIGHT_CHANGE_SELL_THRESHOLD = -0.001

# --- Orchestration (run.py) ---
ORCHESTRATION_MODEL_PATH = MODEL_SAVE_FILE
ORCHESTRATION_UNIVERSE_SAVE_PATH = SP500_TICKERS_LIST_PATH
ORCHESTRATION_LAST_RUN_LOG = LAST_RUN_LOG
ORCHESTRATION_RETRAIN_INTERVAL_DAYS = 126
ORCHESTRATION_UNIVERSE_COPY_PATH = os.path.join(MODELS_DIR, "last_run_universe.csv")

# --- Global / Shared ---
MIN_HISTORY_DAYS = 22 # For filtering stocks with less than 1 month history
MIN_ACTIVE_DAYS = 20 # For filtering stocks with insufficient active days in lookback
