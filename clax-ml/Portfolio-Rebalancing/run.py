# run.py
import subprocess
import os
import shutil
import datetime
import logging
import pandas as pd

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------- Configuration ---------------- #
MODEL_SAVE_PATH = "models/portfolio_weights_model.pth"
UNIVERSE_SAVE_PATH = "outputs/01_SP500_Tickers_list.csv"
LAST_RUN_LOG = "last_run.log" # To store timestamp of last successful training
RETRAIN_INTERVAL_DAYS = 126

def execute_script(script_path: str):
    """Executes a Python script as a subprocess."""
    logger.info(f"Executing: python {script_path}")
    process = subprocess.run(["python", script_path], capture_output=True, text=True, cwd=os.getcwd())
    if process.returncode != 0:
        logger.error(f"Error executing {script_path}:\n{process.stderr}")
        raise RuntimeError(f"Script execution failed: {script_path}")
    else:
        logger.info(f"Successfully executed {script_path}:\n{process.stdout}")

def get_last_run_timestamp(log_file: str) -> datetime.datetime | None:
    """Reads the timestamp of the last successful run from a log file."""
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            try:
                timestamp_str = f.read().strip()
                return datetime.datetime.fromisoformat(timestamp_str)
            except ValueError:
                logger.warning(f"Invalid timestamp in {log_file}.")
    return None

def update_last_run_timestamp(log_file: str):
    """Updates the log file with the current timestamp."""
    with open(log_file, 'w') as f:
        f.write(datetime.datetime.now().isoformat())

def has_universe_changed(current_universe_path: str, last_universe_path: str) -> bool:
    """Checks if the investment universe has changed since the last run."""
    if not os.path.exists(current_universe_path) or not os.path.exists(last_universe_path):
        logger.warning("Universe files not found. Assuming change or initial run.")
        return True
    
    current_df = pd.read_csv(current_universe_path)
    last_df = pd.read_csv(last_universe_path)
    
    # Simple comparison: check if ticker lists are identical
    current_tickers = sorted(current_df['Symbol'].tolist())
    last_tickers = sorted(last_df['Symbol'].tolist())
    
    if current_tickers != last_tickers:
        logger.info("Investment universe has changed.")
        return True
    logger.info("Investment universe has not changed.")
    return False

def main():
    logger.info("🚀 Starting Portfolio Rebalancing Pipeline Orchestration 🚀")

    # --- Step 1: Data Acquisition ---
    # Assuming w01_SP500_Tickers_and_Membership.py handles S&P 500 tickers and membership
    # We will need to decide if we run this always or conditionally
    execute_script("Data_loaders/w01_SP500_Tickers_and_Membership.py")
    
    # Prepare path for last-run universe copy (comparison target)
    os.makedirs("models", exist_ok=True)
    current_universe_copy = "models/last_run_universe.csv"
    
    # --- Step 2: Yahoo Finance Data Fetching ---
    execute_script("Data_loaders/w02_Yahoo.py")

    # --- Step 3: FRED Data Fetching ---
    execute_script("Data_loaders/w03_Fred.py")

    # --- Step 4: Markowitz Labels Generation ---
    execute_script("Pipeline/w04a_Markowitz_Labels.py")

    # --- Step 5: Merge Price & Macro Data ---
    execute_script("Pipeline/w05_merge_price_macro.py")

    # --- Step 6: Feature Engineering ---
    execute_script("Pipeline/w06_Feature_Engg.py")

    # --- Step 7: Model Training (Conditional Retraining) ---
    last_run_time = get_last_run_timestamp(LAST_RUN_LOG)
    needs_retraining = False

    if not os.path.exists(MODEL_SAVE_PATH):
        logger.info("No trained model found. Training from scratch.")
        needs_retraining = True
    elif last_run_time is None:
        logger.info(f"'{LAST_RUN_LOG}' is invalid or missing. Training from scratch.")
        needs_retraining = True
    elif (datetime.datetime.now() - last_run_time).days >= RETRAIN_INTERVAL_DAYS:
        logger.info(f"Retraining interval ({RETRAIN_INTERVAL_DAYS} days) elapsed. Retraining model.")
        needs_retraining = True
    elif has_universe_changed(UNIVERSE_SAVE_PATH, current_universe_copy):
        logger.info("Investment universe has changed. Retraining model.")
        needs_retraining = True
    else:
        logger.info("Model is up-to-date and universe has not changed. Skipping training.")

    if needs_retraining:
        execute_script("Pipeline/w07_train_model.py")
        update_last_run_timestamp(LAST_RUN_LOG)
        logger.info("Model training/retraining completed and timestamp updated.")

        # After successful training, update the saved universe copy for next-run comparisons
        try:
            if os.path.exists(UNIVERSE_SAVE_PATH):
                shutil.copyfile(UNIVERSE_SAVE_PATH, current_universe_copy)
                logger.info(f"Updated stored universe copy at {current_universe_copy}")
        except Exception as e:
            logger.warning(f"Could not update stored universe copy: {e}")
    
    # --- Step 8: Prediction & Rebalancing ---
    execute_script("Pipeline/w08_predict_and_rebalance.py")

    logger.info("✅ Portfolio Rebalancing Pipeline Orchestration Completed.")

if __name__ == "__main__":
    main()
