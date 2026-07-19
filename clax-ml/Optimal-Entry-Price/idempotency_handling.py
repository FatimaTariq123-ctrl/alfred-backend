# main.py
# ------------------------------- 
import subprocess
import sys
import os
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel
import pandas as pd
import joblib
from torch.utils.data import DataLoader, TensorDataset
import torch
import numpy as np

# Import the prediction service
from prediction import PredictionService
from Pipeline.w07_model import LSTMRegressor, RMSELoss
from Pipeline.w08_train_model import calculate_advanced_metrics

# ====================================================== 
#  PIPELINE RUNNER FUNCTIONS
# ====================================================== 

def _run_scripts(script_paths: list):
    """
    Helper function to run a list of python scripts in a subprocess.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    for script_path in script_paths:
        print(f"--- Running {script_path} ---")
        try:
            # Use the python executable from the venv
            python_executable = os.path.join(os.path.dirname(sys.executable), 'python.exe')
            result = subprocess.run([python_executable, script_path], check=True, capture_output=True, text=True, encoding='utf-8', env=env)
            print(result.stdout)
            if result.stderr:
                print("--- Stderr ---")
                print(result.stderr)
            print(f"--- Finished {script_path} ---")
        except subprocess.CalledProcessError as e:
            print(f"--- Error running {script_path} ---")
            print(e.stdout)
            print(e.stderr)
            # Re-raising the exception will stop the background task
            raise

def run_data_loaders_pipeline():
    """
    Runs the data loading part of the pipeline using alternative (Alpaca-based) loaders.
    """
    os.makedirs("outputs", exist_ok=True)
    scripts = [
        "Data_loaders_alt/w01_SP500_Tickers_and_Membership.py",
        "Data_loaders_alt/w02_Alpaca.py",
        "Data_loaders_alt/w02b_Extras.py",
        "Data_loaders_alt/w03_Fred.py",
    ]
    _run_scripts(scripts)

def run_feature_engineering_pipeline():
    """
    Runs the data processing and feature engineering part of the pipeline.
    """
    os.makedirs("outputs", exist_ok=True)
    scripts = [
        "Pipeline/w04_Labels.py",
        "Pipeline/w05_merge_price_macro.py",
        "Pipeline/w06_Feature_Engg.py",
    ]
    _run_scripts(scripts)

def run_training_pipeline():
    """
    Runs the model training part of the pipeline.
    """
    os.makedirs("models", exist_ok=True)
    scripts = ["Pipeline/w08_train_model.py"]
    _run_scripts(scripts)

def run_full_pipeline():
    """
    Runs the full data collection, feature engineering, and model training pipeline.
    """
    print("--- Running Data Loaders ---")
    run_data_loaders_pipeline()
    print("--- Running Feature Engineering ---")
    run_feature_engineering_pipeline()
    print("--- Running Model Training ---")
    run_training_pipeline()


# ====================================================== 
#  API SETUP
# ====================================================== 

# Initialize FastAPI app and Prediction Service
app = FastAPI(
    title="Optimal Entry Price API",
    description="API to predict the optimal entry price for S&P 500 equities and run training pipelines.",
    version="1.0.0"
)

# Load the service. This will load the models into memory on startup.
try:
    prediction_service = PredictionService()
except Exception as e:
    print(f"FATAL: Could not initialize PredictionService. Error: {e}")
    # In a real-world scenario, you might want to prevent the app from starting.
    prediction_service = None

@app.get("/", tags=["Health Check"])
def read_root():
    """A simple health check endpoint."""
    return {"status": "Optimal Entry Price API is running"}

@app.get("/top-50-universe", tags=["Universe"])
async def get_top_50_universe():
    """
    Returns the top 50 most liquid S&P 500 stocks based on 20-day average dollar volume.
    
    Data is precomputed during the data loader pipeline and stored at
    `outputs/02_top50_universe.csv`. This endpoint only reads that file.
    """
    try:
        df = pd.read_csv("outputs/02_top50_universe.csv", parse_dates=["Date"])
        if df.empty:
            raise HTTPException(
                status_code=404,
                detail="Top 50 universe file is empty. Please run the data loading pipeline first."
            )

        latest_date = df["Date"].max()
        # Ensure we only return tickers (sorted by stored AvgDollarVolume)
        df_sorted = df.sort_values("AvgDollarVolume", ascending=False)
        tickers = df_sorted["Ticker"].tolist()

        return {
            "date": latest_date.strftime("%Y-%m-%d"),
            "top_50_liquid_stocks": tickers,
            "note": "Only top 50 stocks by 20-day average dollar volume are included -- no forced major tickers."
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Top 50 universe file not found. Please run the data loading pipeline first."
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while reading top 50 universe: {str(e)}"
        )

class CLAXAgentOutputContract(BaseModel):
    status: str
    data: dict = None
    message: str = None

class OptimalSignalRequest(BaseModel):
    ticker: str

@app.post("/optimal-entry-exit-price", tags=["Prediction"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def optimal_entry_exit_price(request: OptimalSignalRequest, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Returns unified optimal buy/sell signal with predicted price, confidence, and last updated timestamp.
    """
    if prediction_service is None:
        raise HTTPException(status_code=503, detail="Prediction service is not available.")

    try:
        return prediction_service.predict_optimal_entry_exit_signal(request.ticker)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while generating optimal entry/exit signal: {str(e)}"
        )

@app.get("/evaluate", tags=["Evaluation"])
async def evaluate_model():
    """
    Evaluates the trained model on the validation set and returns performance metrics.
    """
    try:
        # Load validation data
        df = pd.read_csv("outputs/06_final_features.csv", parse_dates=["Date"])
        
        # Prepare data
        drop_cols = ["Date", "Ticker", "Close", "Target"]
        drop_cols = [c for c in drop_cols if c in df.columns]
        X_df = df.drop(columns=drop_cols)
        y_df = df[["Target", "Direction", "Close"]]

        X_np = X_df.values.astype(np.float32)
        X_np = np.nan_to_num(X_np, nan=0.0, posinf=0.0, neginf=0.0)
        y_np = y_df[["Target"]].values.astype(np.float32).reshape(-1, 1)
        direction_np = y_df[["Direction"]].values.astype(np.float32)

        scaler_X = joblib.load("models/scaler_X.pkl")
        scaler_y = joblib.load("models/scaler_y.pkl")

        X_scaled = scaler_X.transform(X_np)
        y_scaled = scaler_y.transform(y_np)

        X_reshaped = np.reshape(X_scaled, (X_scaled.shape[0], 1, X_scaled.shape[1]))
        
        val_ds = TensorDataset(torch.tensor(X_reshaped), torch.tensor(y_scaled), torch.tensor(direction_np))
        val_loader = DataLoader(val_ds, batch_size=256, shuffle=False)

        # Load model
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = LSTMRegressor(X_reshaped.shape[2]).to(device)
        model.load_state_dict(torch.load("models/oep_regressor.pth", map_location=device))

        # Calculate metrics
        metrics = calculate_advanced_metrics(model, val_loader, scaler_y, y_df, 0.02, device)
        return metrics
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Required file not found: {e}. Please run the training pipeline first.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during evaluation: {str(e)}")


@app.post("/scheduler", tags=["Scheduler"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def schedule_training(background_tasks: BackgroundTasks, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Triggers the full retraining pipeline in the background.
    """
    background_tasks.add_task(run_full_pipeline)
    return {"message": "Full retraining pipeline scheduled in the background."}


@app.post("/pipeline/data-loaders", tags=["Pipeline"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def trigger_data_loaders(background_tasks: BackgroundTasks, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Triggers the data loading pipeline in the background.
    This includes:
    - `Data_loaders_alt/w01_SP500_Tickers_and_Membership.py`: Fetches current S&P 500 tickers from Wikipedia and verifies them with Alpaca.
    - `Data_loaders_alt/w02_Alpaca.py`: Fetches historical price and volume data for top liquid S&P 500 stocks using the Alpaca Market Data API.
    - `Data_loaders_alt/w02b_Extras.py`: Fetches extra financial data (FX, Yields, Commodities) from FRED and yfinance.
    - `Data_loaders_alt/w03_Fred.py`: Fetches macroeconomic time series data (e.g., interest rates, unemployment, CPI) from the FRED API.
    """
    background_tasks.add_task(run_data_loaders_pipeline)
    return {"message": "Data loading pipeline started in the background (Alpaca-alt)."}

@app.post("/pipeline/feature-engineering", tags=["Pipeline"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def trigger_feature_engineering(background_tasks: BackgroundTasks, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Triggers the data processing and feature engineering part of the pipeline.
    This includes:
    - `Pipeline/w04_Labels.py`: Computes a continuous percent-gap target representing the distance to the optimal limit price for each stock over specified horizons.
    - `Pipeline/w05_merge_price_macro.py`: Merges the labeled stock-level data with FRED macroeconomic features and generates raw differences for interest-rate and unemployment-like series.
    - `Pipeline/w06_Feature_Engg.py`: Adds rolling percentage changes for stock and macro variables, raw differences for interest/unemployment, cyclic encodings for sparse macro updates, sentiment & dispersion features, seasonality features, ECOD normalization, and PCA for dimensionality reduction.
    """
    background_tasks.add_task(run_feature_engineering_pipeline)
    return {"message": "Feature engineering pipeline started in the background."}

@app.post("/pipeline/train-model", tags=["Pipeline"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def trigger_train_model(background_tasks: BackgroundTasks, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Triggers the model training pipeline in the background.
    This executes:
    - `Pipeline/w08_train_model.py`: Trains a regression neural network (LSTM-LSTM-Dense architecture) to predict percent-gap targets based on the engineered features. It includes data scaling, weighted sampling, early stopping, and advanced performance metrics calculation.
    """
    background_tasks.add_task(run_training_pipeline)
    return {"message": "Model training pipeline started in a background."}

@app.post("/pipeline/full-pipeline", tags=["Pipeline"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def trigger_full_pipeline(background_tasks: BackgroundTasks, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Triggers the entire end-to-end Optimal Entry Price (OEP) pipeline in the background.
    This sequentially runs all three major pipeline stages:
    1.  **Data Loading:** Fetches S&P 500 tickers, Yahoo Finance data, and FRED macroeconomic data.
    2.  **Feature Engineering:** Computes OEP labels, merges price and macro features, and generates various technical, macro, and seasonal features, including PCA.
    3.  **Model Training:** Trains the regression neural network model using the prepared features.
    """
    background_tasks.add_task(run_full_pipeline)
    return {"message": "Full training pipeline started in the background."}


# ====================================================== 
#  MAIN EXECUTION
# ====================================================== 

if __name__ == "__main__":
    # This allows running the server or the training pipeline via command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        print("Starting full training pipeline...")
        try:
            run_full_pipeline()
            print("\nPipeline completed successfully.")
        except Exception as e:
            print(f"\nPipeline failed: {e}")
    else:
        print("Starting API server...")
        # To run: uvicorn main:app --reload
        uvicorn.run(app, host="0.0.0.0", port=8000)
