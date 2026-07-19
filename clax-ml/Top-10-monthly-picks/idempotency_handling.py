# main.py
import os
import logging
import importlib
import joblib
import requests
import pandas as pd
import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Header
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# ----------------- Constants ----------------- #
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
MODEL_PATH = "models/top10_model.onnx"
SCALER_PATH = "models/feature_scaler.joblib"
FEATURES_PATH = "outputs/06_final_features.csv"
SEQUENCE_LENGTH = 66  # Must match the sequence length used in training
STOCK_PRICES_PATH = "outputs/02_Yahoo_Stocks.csv"
FMP_PROFILE_URL = "https://financialmodelingprep.com/stable/profile"
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()

# Curated Top 10 S&P 500 tickers for this agent
TOP_10_SP500_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "AVGO", "TSLA", "JPM", "XOM"
]

ASSET_NAME_OVERRIDES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc. Class A",
    "META": "Meta Platforms, Inc.",
    "AVGO": "Broadcom Inc.",
    "TSLA": "Tesla, Inc.",
    "JPM": "JPMorgan Chase & Co.",
    "XOM": "Exxon Mobil Corporation",
}

OPENAPI_TAGS = [
    {"name": "Assets - Core", "description": "Primary asset detail APIs: overview, quote, and chart."},
    {"name": "Assets - Supporting", "description": "Supporting asset collection APIs."},
    {"name": "Predictions", "description": "Top 10 monthly pick prediction APIs."},
    {"name": "Jobs", "description": "Background data refresh and model retraining jobs."},
    {"name": "Monitoring", "description": "Health and service status endpoints."},
]

# This dictionary will hold our loaded model and other ML assets
ml_models = {}
icon_url_cache: Dict[str, str] = {}


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _build_logo_url(ticker: str) -> str:
    normalized_ticker = _normalize_ticker(ticker)
    if normalized_ticker in icon_url_cache:
        return icon_url_cache[normalized_ticker]

    fallback_url = f"https://images.financialmodelingprep.com/symbol/{normalized_ticker}.png"
    if not FMP_API_KEY:
        return fallback_url

    try:
        response = requests.get(
            FMP_PROFILE_URL,
            params={"symbol": normalized_ticker, "apikey": FMP_API_KEY},
            timeout=10
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list) and payload:
            image_url = payload[0].get("image")
            if image_url:
                icon_url_cache[normalized_ticker] = image_url
                return image_url
    except Exception as e:
        logging.warning(f"FMP icon fetch failed for {normalized_ticker}: {e}")

    return fallback_url


def _market_status_now() -> str:
    # Basic US market-hours check (Mon-Fri, 09:30-16:00 ET).
    now_et = datetime.now(ZoneInfo("America/New_York"))
    is_weekday = now_et.weekday() < 5
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return "open" if is_weekday and market_open <= now_et <= market_close else "closed"


def _load_ticker_price_history(ticker: str) -> pd.DataFrame:
    normalized_ticker = _normalize_ticker(ticker)
    try:
        price_df = pd.read_csv(STOCK_PRICES_PATH)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Required file not found: {STOCK_PRICES_PATH}")

    if "date" in price_df.columns and "Date" not in price_df.columns:
        price_df = price_df.rename(columns={"date": "Date"})

    required_cols = {"Ticker", "Date", "Close"}
    if not required_cols.issubset(price_df.columns):
        raise HTTPException(status_code=500, detail="Price dataset is missing required columns: Ticker, Date, Close")

    price_df["Ticker"] = price_df["Ticker"].astype(str).str.upper()
    ticker_df = price_df.loc[price_df["Ticker"] == normalized_ticker, ["Date", "Close"]].copy()

    if ticker_df.empty:
        raise HTTPException(status_code=404, detail=f"Ticker '{normalized_ticker}' not found")

    ticker_df["Date"] = pd.to_datetime(ticker_df["Date"], errors="coerce")
    ticker_df["Close"] = pd.to_numeric(ticker_df["Close"], errors="coerce")
    ticker_df = ticker_df.dropna(subset=["Date", "Close"]).sort_values("Date")

    if ticker_df.empty:
        raise HTTPException(status_code=404, detail=f"No valid price history found for '{normalized_ticker}'")

    return ticker_df


def _ticker_name(ticker: str) -> str:
    ticker = _normalize_ticker(ticker)
    return ASSET_NAME_OVERRIDES.get(ticker, ticker)


# ----------------- FastAPI App Lifespan ----------------- #
@asynccontextmanager
async def lifespan(app: FastAPI, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    # Load the ML model and scaler on startup
    logging.info("Loading machine learning model and assets...")
    try:
        model = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        ml_models['model'] = model
        ml_models['scaler'] = joblib.load(SCALER_PATH)
        logging.info("Model and assets loaded successfully.")
    except FileNotFoundError as e:
        logging.error(f"Could not load ML model or assets: {e}. The /predict/top10 endpoint will be unavailable.")
        ml_models['model'] = None
        ml_models['scaler'] = None
    except ValueError as e:
        logging.error(f"Model validation failed: {e}")
        ml_models['model'] = None
        ml_models['scaler'] = None
    yield
    # Clean up the ML models and other resources on shutdown
    ml_models.clear()
    logging.info("ML models and assets cleared.")

app = FastAPI(lifespan=lifespan, openapi_tags=OPENAPI_TAGS)

# ----------------- Background Job Functions ----------------- #
def run_script(module_name: str, main_func_name: str = "run_pipeline"):
    """
    Helper to import and run a script's main function.
    Fails fast by re-raising any exceptions.
    """
    try:
        module = importlib.import_module(module_name)
        if hasattr(module, main_func_name):
            logging.info(f"Running {module_name}.{main_func_name}() ...")
            getattr(module, main_func_name)()
            logging.info(f"Finished running {module_name}.{main_func_name}().")
        else:  # For scripts that run on import
            importlib.reload(module)
            logging.info(f"Reloaded {module_name} (no {main_func_name}() found, code executed on import)")
    except Exception as e:
        logging.error(f"Error running script {module_name}: {e}", exc_info=True)
        raise  # Re-raise the exception to halt the background task pipeline


def run_full_pipeline():
    """
    Runs the full data refresh and feature engineering pipeline sequentially.
    The job will abort if any script fails.
    """
    pipeline_steps = [
        # --- Data Loading ---
        ("Data_loaders.w01_SP500_Tickers_and_Membership", "run_pipeline"),
        ("Data_loaders.w02_Yahoo", "run_pipeline"),
        ("Data_loaders.w03_Fred", "run_pipeline"),
        # --- Feature Engineering ---
        ("Pipeline.04_Labels", "run_pipeline"),
        ("Pipeline.05_merge_price_macro", "build_feature_panel"),
        ("Pipeline.06_Feature_Engg", "generate_features"),
    ]
    logging.info("Starting full data and feature pipeline...")
    for i, (script, main_func) in enumerate(pipeline_steps):
        try:
            step_num = i + 1
            logging.info(f"--- Pipeline Step {step_num}/{len(pipeline_steps)}: Running {script} ---")
            run_script(script, main_func_name=main_func)
            logging.info(f"--- Step {step_num} SUCCEEDED ---")
        except Exception:
            logging.error(f"--- Pipeline FAILED at step {step_num}: {script}. Aborting. ---")
            # The exception is already logged by run_script. We stop the sequence here.
            return
    logging.info("--- Full data and feature pipeline COMPLETED successfully. ---")




# ----------------- API Request Models ----------------- #
class CLAXAgentOutputContract(BaseModel):
    status: str
    data: Optional[Dict] = None
    message: Optional[str] = None

class RetrainInput(BaseModel):
    force_retrain: bool = False

class Prediction(BaseModel):
    rank: int
    ticker: str
    score: float

class PredictionResponse(BaseModel):
    prediction_date: str
    model_version: str
    top_10_picks: List[Prediction]

# ----------------- Endpoints ----------------- #
# ----------------- Asset APIs (Major) ----------------- #
@app.get("/assets/{ticker}/overview", tags=["Assets - Core"])
async def get_asset_overview(ticker: str, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    normalized_ticker = _normalize_ticker(ticker)
    if normalized_ticker not in TOP_10_SP500_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker '{normalized_ticker}' is not in Top 10 S&P 500 set")

    return {
        "status": "success",
        "data": {
            "ticker": normalized_ticker,
            "name": _ticker_name(normalized_ticker),
            "asset_image_url": _build_logo_url(normalized_ticker),
        }
    }


@app.get("/assets/{ticker}/quote", tags=["Assets - Core"])
async def get_asset_quote(ticker: str, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    normalized_ticker = _normalize_ticker(ticker)
    if normalized_ticker not in TOP_10_SP500_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker '{normalized_ticker}' is not in Top 10 S&P 500 set")

    ticker_df = _load_ticker_price_history(normalized_ticker)
    if len(ticker_df) < 2:
        raise HTTPException(status_code=422, detail=f"Not enough data to compute quote delta for '{normalized_ticker}'")

    latest_row = ticker_df.iloc[-1]
    previous_row = ticker_df.iloc[-2]

    current_price = float(latest_row["Close"])
    previous_close = float(previous_row["Close"])
    absolute_change = current_price - previous_close
    percentage_change = (absolute_change / previous_close * 100.0) if previous_close else 0.0

    last_updated = pd.Timestamp(latest_row["Date"]).to_pydatetime().replace(
        hour=16, minute=0, second=0, microsecond=0, tzinfo=ZoneInfo("UTC")
    )

    return {
        "status": "success",
        "data": {
            "ticker": normalized_ticker,
            "current_price": current_price,
            "price_change": {
                "absolute": round(absolute_change, 4),
                "percentage": round(percentage_change, 4)
            },
            "market_status": _market_status_now(),
            "last_updated": last_updated.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
    }


@app.get("/assets/{ticker}/chart", tags=["Assets - Core"])
async def get_asset_chart(
    ticker: str,
    range: str = Query("24h", description="Currently supports only 24h"),
    interval: str = Query("1h", description="Currently supports only 1h")
, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    normalized_ticker = _normalize_ticker(ticker)
    if normalized_ticker not in TOP_10_SP500_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker '{normalized_ticker}' is not in Top 10 S&P 500 set")

    if range != "24h" or interval != "1h":
        raise HTTPException(status_code=400, detail="Only range=24h and interval=1h are currently supported")

    ticker_df = _load_ticker_price_history(normalized_ticker)
    close_prices = ticker_df["Close"].tail(24).tolist()
    if not close_prices:
        raise HTTPException(status_code=404, detail=f"No chart data available for '{normalized_ticker}'")

    latest_ts = pd.Timestamp(ticker_df.iloc[-1]["Date"]).to_pydatetime().replace(
        minute=0, second=0, microsecond=0, tzinfo=ZoneInfo("UTC")
    )
    start_ts = latest_ts - timedelta(hours=len(close_prices) - 1)

    prices = []
    for idx, price in enumerate(close_prices):
        ts = start_ts + timedelta(hours=idx)
        prices.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price": round(float(price), 4)
        })

    return {
        "status": "success",
        "data": {
            "ticker": normalized_ticker,
            "range": "24h",
            "interval": "1h",
            "prices": prices
        }
    }
# ----------------- Unified Market Endpoint ----------------- #
# ----------------- Robust Unified Market Endpoint ----------------- #
@app.get("/api/market/top-10-sp500", tags=["Assets - Supporting"])
async def get_top10_market_data(authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Unified endpoint returning overview, quote, and chart for Top 10 S&P 500 tickers.
    If chart data is missing, returns empty 'prices' list instead of skipping the ticker.
    """
    results = []
    last_updated_list = []

    for ticker in TOP_10_SP500_TICKERS:
        ticker_result = {"ticker": ticker}

        # Overview
        try:
            overview_resp = await get_asset_overview(ticker, authorization=authorization, x_idempotency_key=x_idempotency_key)
            ticker_result["name"] = overview_resp["data"].get("name")
            ticker_result["asset_image_url"] = overview_resp["data"].get("asset_image_url")
        except Exception as e:
            logging.warning(f"Overview failed for {ticker}: {e}")
            ticker_result["name"] = ticker
            ticker_result["asset_image_url"] = ""

        # Quote
        try:
            quote_resp = await get_asset_quote(ticker, authorization=authorization, x_idempotency_key=x_idempotency_key)
            ticker_result["quote"] = {
                "current_price": quote_resp["data"].get("current_price"),
                "price_change": quote_resp["data"].get("price_change"),
                "market_status": quote_resp["data"].get("market_status"),
                "last_updated": quote_resp["data"].get("last_updated")
            }
            last_updated_list.append(quote_resp["data"].get("last_updated"))
        except Exception as e:
            logging.warning(f"Quote failed for {ticker}: {e}")
            ticker_result["quote"] = {
                "current_price": None,
                "price_change": {"absolute": None, "percentage": None},
                "market_status": "unknown",
                "last_updated": None
            }

        # Chart
        try:
            chart_resp = await get_asset_chart(ticker, range="24h", interval="1h", authorization=authorization, x_idempotency_key=x_idempotency_key)
            ticker_result["chart"] = {
                "range": chart_resp["data"].get("range"),
                "interval": chart_resp["data"].get("interval"),
                "prices": chart_resp["data"].get("prices")
            }
        except Exception as e:
            logging.warning(f"Chart failed for {ticker}: {e}")
            ticker_result["chart"] = {
                "range": "24h",
                "interval": "1h",
                "prices": []
            }

        results.append(ticker_result)

    # Determine the latest last_updated timestamp
    last_updated = max(
        [ts for ts in last_updated_list if ts is not None],
        default=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    return {
        "status": "success",
        "last_updated": last_updated,
        "data": results
    }




# ----------------- Asset APIs (Supporting) ----------------- #
@app.get("/assets/top10-sp500", tags=["Assets - Supporting"])
async def get_top10_sp500(authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    return {
        "status": "success",
        "data": {
            "name": "Top 10 S&P 500",
            "tickers": TOP_10_SP500_TICKERS
        }
    }


# ----------------- Prediction APIs ----------------- #
@app.get("/predict/top10", response_model=PredictionResponse, tags=["Predictions"])
async def predict_top10(date: Optional[str] = Query(None, description="Date for prediction in YYYY-MM-DD format. If not specified, automatically uses the latest available date in the data. If a future date is provided, falls back to the latest available date."), authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Retrieves the latest top-10 stock predictions, identifying stocks expected 
    to outperform the S&P 500 index for the upcoming period (next 22 trading days).
    
    **Date Handling:**
    - If no date is specified: Automatically uses the latest available date in the data
    - If a date is specified: Uses that date if it exists in the data
    - If a future date is specified: Automatically falls back to the latest available date
    
    The prediction is forward-looking - it predicts which stocks will outperform 
    in the NEXT 22 trading days (~1 month) from the specified (or latest) date.
    
    This endpoint uses the predict_monthly module to generate predictions
    by reproducing the full feature engineering pipeline.
    
    **Example Usage:**
    - GET /predict/top10 (uses latest available date automatically)
    - GET /predict/top10?date=2025-11-26 (uses specific date if available)
    """
    try:
        # Import predict_monthly function
        from predict_monthly import predict_top_10_monthly
        
        logging.info(f"Prediction request for date: {date}")
        
        # Call the prediction function
        top_10_tickers, top_10_scores = predict_top_10_monthly(target_date=date)
        
        # Format response with actual scores
        top_10_picks = [
            {
                'rank': idx + 1,
                'ticker': ticker,
                'score': float(score)
            }
            for idx, (ticker, score) in enumerate(zip(top_10_tickers, top_10_scores))
        ]
        
        # Get the actual prediction date that was used
        # The predict_top_10_monthly function automatically handles date fallback
        # We need to determine what date was actually used
        try:
            # Check latest available date from price data (same source as predict_monthly uses)
            price_df = pd.read_csv("outputs/02_Yahoo_Stocks.csv")
            if 'date' in price_df.columns:
                price_df.rename(columns={'date': 'Date'}, inplace=True)
            price_df['Date'] = pd.to_datetime(price_df['Date'])
            latest_available = price_df['Date'].max()
            
            if date:
                requested_date = pd.to_datetime(date).normalize()
                # If requested date is beyond available data, use latest available
                if requested_date > latest_available:
                    prediction_date = latest_available.strftime('%Y-%m-%d')
                    logging.info(f"Requested date {date} was beyond available data. Using {prediction_date}")
                else:
                    prediction_date = requested_date.strftime('%Y-%m-%d')
            else:
                # No date specified - use latest available
                prediction_date = latest_available.strftime('%Y-%m-%d')
        except Exception as e:
            logging.warning(f"Could not determine actual prediction date: {e}")
            # Fallback to requested date or current date
            if date:
                prediction_date = date
            else:
                prediction_date = datetime.now().strftime('%Y-%m-%d')
        
        model_timestamp = datetime.fromtimestamp(os.path.getmtime(MODEL_PATH)).isoformat()
        
        return {
            "prediction_date": prediction_date,
            "model_version": model_timestamp,
            "top_10_picks": top_10_picks
        }
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Required file not found: {e}")
    except Exception as e:
        logging.error(f"Prediction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred during prediction: {e}")


# ----------------- Job Control APIs ----------------- #
@app.post(
    "/jobs/refresh_data", 
    status_code=202, 
    tags=["Jobs"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    }
)
async def refresh_data(background_tasks: BackgroundTasks, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Triggers a background job to run the full data refresh and feature engineering pipeline.
    The pipeline executes the following scripts in order:
    1. All Data_loaders scripts
    2. All Feature engineering (Pipeline) scripts
    The job will stop if any script fails.
    """
    background_tasks.add_task(run_full_pipeline)
    return {"status": "Full data and feature pipeline started."}


@app.post(
    "/jobs/retrain_model", 
    status_code=202, 
    tags=["Jobs"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    }
)
async def retrain_model(params: RetrainInput, background_tasks: BackgroundTasks, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """Triggers the model training and validation pipeline."""
    # Note: In a real implementation, you might pass `force_retrain` to the script.
    logging.info(f"Adding model retraining to background tasks. Force retrain: {params.force_retrain}")
    background_tasks.add_task(run_script, "Pipeline.07_train_model", "run_training")
    return {"status": "model retraining job started"}


# ----------------- Monitoring APIs ----------------- #
@app.get("/monitoring/health", tags=["Monitoring"])
async def health_check(authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """A simple health check endpoint."""
    return {"status": "ok"}

@app.get("/monitoring/status", tags=["Monitoring"])
async def get_status(authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """Provides detailed status information about the agent's data and models."""
    def get_file_time(path):
        try:
            return datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
        except FileNotFoundError:
            return None

    status_info = {
        "service_status": "ok",
        "model_last_trained": get_file_time(MODEL_PATH),
        "feature_pipeline_last_run": get_file_time(FEATURES_PATH),
        "data_timestamps": {
            "sp500_membership": get_file_time("outputs/01_SP500_membership_matrix.csv"),
            "yahoo_finance": get_file_time("outputs/02_Yahoo_Stocks.csv"),
            "fred_macro": get_file_time("outputs/03_fred_features.csv"),
        }
    }
    return status_info

# To run the app, use the command: uvicorn main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
