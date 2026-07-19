# main.py
import os
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import pandas as pd

# Import pipeline functions
from Data_loaders.w01_SP500_Tickers_and_Membership import run_pipeline as w01_pipeline
from Data_loaders.w02_Yahoo import run_pipeline as w02_pipeline, filter_universe
from Data_loaders.w03_Fred import run_pipeline as w03_pipeline
from Pipeline.w04a_Markowitz_Labels import build_markowitz_labels
from Pipeline.w05_merge_price_macro import build_feature_panel
from Pipeline.w06_Feature_Engg import generate_features, get_cycle_encoding_summary
from Pipeline.w07_train_model import train_model
from Pipeline.w08_predict_and_rebalance import predict_weights, generate_rebalance_instructions


# ---------------- Request Models ---------------- #
class RebalanceRequest(BaseModel):
    date: Optional[str] = Field(
        default=None,
        description=(
            "Optional rebalance date in 'YYYY-MM-DD' format. "
            "If omitted or null, the API will use the latest available date."
        ),
        example="2026-01-14",
    )


class TrainRequest(BaseModel):
    epochs: int = Field(default=1, description="Number of training epochs.")
    patience: int = Field(default=30, description="Patience for early stopping.")


# --- Portfolio Rebalancing Agent Models --- #

class Holding(BaseModel):
    symbol: str
    quantity: float
    current_price: float


class Constraints(BaseModel):
    max_single_stock_weight: Optional[float] = Field(default=0.2, ge=0.0, le=1.0)
    long_only: Optional[bool] = True


class PortfolioRebalanceRequest(BaseModel):
    user_id: str
    portfolio_id: str
    target_roi: float
    holdings: List[Holding]
    rebalance_type: Optional[str] = "moderate"
    constraints: Optional[Constraints] = None


class Recommendation(BaseModel):
    symbol: str
    action: str  # rebalance | replace | hold
    current_quantity: float
    target_quantity: float
    trade_quantity: float
    reason: str


class RiskMetrics(BaseModel):
    sharpe_ratio: float
    volatility: float
    beta: float


class PortfolioRebalanceResponse(BaseModel):
    status: str
    portfolio_value: float
    current_expected_roi: float
    risk_metrics: RiskMetrics
    recommendations: List[Recommendation]


# ------------- Business Logic (Placeholders) ------------- #

def generate_rebalance_recommendations(request: PortfolioRebalanceRequest) -> PortfolioRebalanceResponse:
    """
    Placeholder service logic for portfolio rebalancing.
    In a real implementation, this would call the ML models and optimization engines.
    """
    # Basic validation for demo purposes
    if not request.holdings:
        raise ValueError("Portfolio must contain at least one holding.")

    total_value = sum(h.quantity * h.current_price for h in request.holdings)
    
    # Mocking recommendations: just returning 'hold' for existing assets for now
    recs = [
        Recommendation(
            symbol=h.symbol,
            action="hold",
            current_quantity=h.quantity,
            target_quantity=h.quantity,
            trade_quantity=0,
            reason="Current position is optimal according to placeholder logic."
        ) for h in request.holdings
    ]

    return PortfolioRebalanceResponse(
        status="success",
        portfolio_value=round(total_value, 2),
        current_expected_roi=request.target_roi,  # Simplified for placeholder
        risk_metrics=RiskMetrics(
            sharpe_ratio=1.8,
            volatility=0.15,
            beta=1.1
        ),
        recommendations=recs
    )


# ------------- FastAPI App ------------- #
app = FastAPI(title="Portfolio Rebalancing API", version="1.0.0")


# ------------- Endpoints ------------- #

@app.post("/api/v1/portfolio/rebalance", response_model=PortfolioRebalanceResponse, tags=["Portfolio"])
async def rebalance_portfolio(request: PortfolioRebalanceRequest):
    """
    Endpoint for the Portfolio Rebalancing Agent.
    Analyzes current holdings and returns optimization recommendations.
    """
    try:
        # 1. Basic validation (already handled by Pydantic mostly)
        if request.target_roi < 0:
            raise HTTPException(status_code=400, detail="target_roi must be non-negative.")

        # 2. Check if portfolio exists (Mocking a 404 for a specific ID for demonstration)
        if request.portfolio_id == "non-existent-id":
            raise HTTPException(status_code=404, detail=f"Portfolio {request.portfolio_id} not found.")

        # 3. Call business logic layer
        response = generate_rebalance_recommendations(request)
        return response

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        # Log the full error here in production
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@app.post("/data/loaders/run", summary="Run all data loaders (w01, w02, w03)", tags=["Pipeline"])
async def run_all_data_loaders():
    """
    Runs all data loader pipelines in sequence:
    1. S&P 500 tickers & membership (Data_loaders/w01_SP500_Tickers_and_Membership.py)
    2. Yahoo Finance prices & volumes (Data_loaders/w02_Yahoo.py)
    3. FRED macro series (Data_loaders/w03_Fred.py)
    """
    try:
        # Run S&P 500 tickers & membership loader
        w01_pipeline()

        # Run Yahoo Finance data loader
        w02_pipeline()

        # Run FRED macro data loader
        w03_pipeline()

        return {
            "status": "success",
            "message": "All data loaders completed successfully.",
            "steps": [
                "w01_SP500_Tickers_and_Membership",
                "w02_Yahoo",
                "w03_Fred",
            ],
        }
    except Exception as e:
        # Bubble up as HTTP error with basic detail
        raise HTTPException(status_code=500, detail=f"Data loaders failed: {e}")


@app.post("/pipeline/features/run", summary="Run feature engineering pipeline (w04a, w05, w06)")
async def run_feature_pipeline():
    """
    Runs the model feature pipeline in sequence:
    1. Build Markowitz labels (Pipeline/w04a_Markowitz_Labels.py)
    2. Merge price data with macro features (Pipeline/w05_merge_price_macro.py)
    3. Generate final engineered features (Pipeline/w06_Feature_Engg.py)
    """
    try:
        # Step 1: Markowitz labels
        build_markowitz_labels()

        # Step 2: Merge price + macro
        build_feature_panel()

        # Step 3: Feature engineering
        generate_features()

        return {
            "status": "success",
            "message": "Feature engineering pipeline completed successfully.",
            "steps": [
                "w04a_Markowitz_Labels",
                "w05_merge_price_macro",
                "w06_Feature_Engg",
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feature pipeline failed: {e}")


@app.post("/pipeline/train/run", summary="Run model training pipeline (w07_train_model)")
async def run_training_pipeline(req: TrainRequest):
    """
    Runs the model training pipeline (Pipeline/w07_train_model.py).
    This will train the LSTM model and save the model file, scalers, and ticker list.
    """
    try:
        metrics = train_model(epochs=req.epochs, patience=req.patience)
        return {
            "status": "success",
            "message": "Model training pipeline completed successfully.",
            "step": "w07_train_model",
            "metrics": metrics,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Training pipeline failed: {str(e)}")


@app.post("/rebalance/predict", summary="Predict portfolio weights with ML model (w08_predict_and_rebalance)")
async def rebalance_predict(req: RebalanceRequest):
    """
    Predicts portfolio weights using the trained LSTM model for the
    requested (or latest) date.
    This runs the Pipeline/w08_predict_and_rebalance.py pipeline.
    """
    try:
        # predict_weights is expected to take a date string or be able to handle None
        weights_df = predict_weights(date=req.date)

        if weights_df is None or weights_df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"Could not predict weights for date {req.date}. "
                       "Ensure the model is trained and features are available for that date.",
            )

        # The date should be in the returned dataframe from predict_weights
        if 'Date' not in weights_df.columns:
            raise HTTPException(status_code=500, detail="Prediction output is missing 'Date' column.")
        
        if 'Predicted_Weight' not in weights_df.columns:
            raise HTTPException(status_code=500, detail="Prediction output is missing 'Predicted_Weight' column.")

        # Assume one row of weights is returned for the target date
        prediction_date = pd.to_datetime(weights_df['Date'].iloc[0])
        weights_dict = weights_df.set_index("Ticker")["Predicted_Weight"].to_dict()

        return {
            "date": prediction_date.strftime("%Y-%m-%d"),
            "weights": weights_dict,
            "method": "LSTM Model",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")



if __name__ == "__main__":
    # Run with: python main.py
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
