# main.py
import os
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
import pandas as pd

# ---------------- Request Models ---------------- #
class CLAXAgentOutputContract(BaseModel):
    status: str
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None

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


# ------------- Business Logic ------------- #

REBALANCE_TYPE_STRENGTH = {
    "conservative": 0.35,
    "moderate": 0.60,
    "aggressive": 0.85,
}


def _symbol_return_score(symbol: str) -> float:
    """Create a stable score so recommendations vary without external market calls."""
    normalized = symbol.upper().strip()
    ordinal_score = sum((idx + 1) * ord(char) for idx, char in enumerate(normalized))
    return 0.75 + (ordinal_score % 50) / 100


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(value, 0) for value in weights.values())
    if total <= 0:
        equal_weight = 1 / len(weights)
        return {symbol: equal_weight for symbol in weights}
    return {symbol: max(value, 0) / total for symbol, value in weights.items()}


def _apply_max_weight_cap(weights: Dict[str, float], max_weight: float) -> Dict[str, float]:
    if not weights:
        return weights
    if max_weight <= 0:
        equal_weight = 1 / len(weights)
        return {symbol: equal_weight for symbol in weights}
    if max_weight * len(weights) < 1:
        max_weight = 1 / len(weights)

    capped = weights.copy()
    for _ in range(len(capped)):
        over_cap = {symbol: weight for symbol, weight in capped.items() if weight > max_weight}
        if not over_cap:
            break

        excess = sum(weight - max_weight for weight in over_cap.values())
        for symbol in over_cap:
            capped[symbol] = max_weight

        under_cap_symbols = [symbol for symbol, weight in capped.items() if weight < max_weight]
        if not under_cap_symbols:
            break

        under_cap_total = sum(capped[symbol] for symbol in under_cap_symbols)
        if under_cap_total <= 0:
            redistribution = excess / len(under_cap_symbols)
            for symbol in under_cap_symbols:
                capped[symbol] += redistribution
        else:
            for symbol in under_cap_symbols:
                capped[symbol] += excess * (capped[symbol] / under_cap_total)

    return _normalize_weights(capped)

def generate_rebalance_recommendations(request: PortfolioRebalanceRequest) -> PortfolioRebalanceResponse:
    """
    Generates deterministic rebalancing recommendations from request inputs.

    This keeps the API useful even when the ML pipeline is not invoked: quantities,
    prices, ROI target, rebalance type, and max-weight constraints all affect the
    returned quantities, trades, risk metrics, and reasons.
    """
    if not request.holdings:
        raise ValueError("Portfolio must contain at least one holding.")

    if any(h.quantity < 0 for h in request.holdings):
        raise ValueError("Holding quantity must be non-negative.")

    if any(h.current_price <= 0 for h in request.holdings):
        raise ValueError("Holding current_price must be greater than zero.")

    total_value = sum(h.quantity * h.current_price for h in request.holdings)
    if total_value <= 0:
        raise ValueError("Portfolio value must be greater than zero.")

    constraints = request.constraints or Constraints()
    max_single_stock_weight = (
        constraints.max_single_stock_weight
        if constraints.max_single_stock_weight is not None
        else 1.0
    )
    rebalance_strength = REBALANCE_TYPE_STRENGTH.get(
        (request.rebalance_type or "moderate").lower(),
        REBALANCE_TYPE_STRENGTH["moderate"],
    )

    current_weights = {
        h.symbol: (h.quantity * h.current_price) / total_value
        for h in request.holdings
    }
    return_scores = {
        h.symbol: _symbol_return_score(h.symbol) * (1 + request.target_roi)
        for h in request.holdings
    }
    return_weights = _normalize_weights(return_scores)

    roi_pressure = min(request.target_roi / 0.25, 1.0)
    optimizer_weight = max(0.10, min(0.90, rebalance_strength * (0.35 + roi_pressure)))
    blended_weights = {
        symbol: (current_weights[symbol] * (1 - optimizer_weight)) + (return_weights[symbol] * optimizer_weight)
        for symbol in current_weights
    }
    target_weights = _apply_max_weight_cap(_normalize_weights(blended_weights), max_single_stock_weight)

    expected_asset_returns = {
        symbol: 0.02 + (request.target_roi * return_scores[symbol] / max(return_scores.values()))
        for symbol in return_scores
    }
    current_expected_roi = sum(current_weights[symbol] * expected_asset_returns[symbol] for symbol in current_weights)
    target_expected_roi = sum(target_weights[symbol] * expected_asset_returns[symbol] for symbol in target_weights)
    concentration = sum(weight ** 2 for weight in target_weights.values())
    volatility = 0.08 + (0.18 * concentration) + (0.04 * rebalance_strength)
    sharpe_ratio = target_expected_roi / volatility if volatility else 0
    beta = 0.75 + (0.50 * concentration) + (0.20 * rebalance_strength)

    recs = []
    for holding in request.holdings:
        symbol = holding.symbol
        target_value = total_value * target_weights[symbol]
        target_quantity = target_value / holding.current_price
        trade_quantity = target_quantity - holding.quantity
        trade_value = abs(trade_quantity * holding.current_price)

        if trade_value < max(total_value * 0.005, 1.0):
            action = "hold"
            reason = "Current allocation is within the rebalance tolerance."
        elif trade_quantity > 0:
            action = "rebalance"
            reason = f"Increase allocation toward the {round(target_weights[symbol] * 100, 2)}% target weight."
        else:
            action = "rebalance"
            reason = f"Reduce allocation toward the {round(target_weights[symbol] * 100, 2)}% target weight."

        recs.append(
            Recommendation(
                symbol=symbol,
                action=action,
                current_quantity=round(holding.quantity, 4),
                target_quantity=round(target_quantity, 4),
                trade_quantity=round(trade_quantity, 4),
                reason=reason,
            )
        )

    return PortfolioRebalanceResponse(
        status="success",
        portfolio_value=round(total_value, 2),
        current_expected_roi=round(current_expected_roi, 4),
        risk_metrics=RiskMetrics(
            sharpe_ratio=round(sharpe_ratio, 4),
            volatility=round(volatility, 4),
            beta=round(beta, 4),
        ),
        recommendations=recs
    )


# ------------- FastAPI App ------------- #
app = FastAPI(title="Portfolio Rebalancing API", version="1.0.0")


# ------------- Endpoints ------------- #

@app.post("/api/v1/portfolio/rebalance", response_model=PortfolioRebalanceResponse, tags=["Portfolio"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def rebalance_portfolio(request: PortfolioRebalanceRequest, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
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


@app.post("/data/loaders/run", summary="Run all data loaders (w01, w02, w03)", tags=["Pipeline"],
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def run_all_data_loaders(authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Runs all data loader pipelines in sequence:
    1. S&P 500 tickers & membership (Data_loaders/w01_SP500_Tickers_and_Membership.py)
    2. Yahoo Finance prices & volumes (Data_loaders/w02_Yahoo.py)
    3. FRED macro series (Data_loaders/w03_Fred.py)
    """
    try:
        from Data_loaders.w01_SP500_Tickers_and_Membership import run_pipeline as w01_pipeline
        from Data_loaders.w02_Yahoo import run_pipeline as w02_pipeline
        from Data_loaders.w03_Fred import run_pipeline as w03_pipeline

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


@app.post("/pipeline/features/run", summary="Run feature engineering pipeline (w04a, w05, w06)",
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def run_feature_pipeline(authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Runs the model feature pipeline in sequence:
    1. Build Markowitz labels (Pipeline/w04a_Markowitz_Labels.py)
    2. Merge price data with macro features (Pipeline/w05_merge_price_macro.py)
    3. Generate final engineered features (Pipeline/w06_Feature_Engg.py)
    """
    try:
        from Pipeline.w04a_Markowitz_Labels import build_markowitz_labels
        from Pipeline.w05_merge_price_macro import build_feature_panel
        from Pipeline.w06_Feature_Engg import build_features

        # Step 1: Markowitz labels
        build_markowitz_labels()

        # Step 2: Merge price + macro
        build_feature_panel()

        # Step 3: Feature engineering
        build_features()

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


@app.post("/pipeline/train/run", summary="Run model training pipeline (w07_train_model)",
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def run_training_pipeline(req: TrainRequest, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Runs the model training pipeline (Pipeline/w07_train_model.py).
    This will train the LSTM model and save the model file, scalers, and ticker list.
    """
    try:
        from Pipeline.w07_train_model import train_model

        metrics = train_model(epochs=req.epochs, patience=req.patience)
        return {
            "status": "success",
            "message": "Model training pipeline completed successfully.",
            "step": "w07_train_model",
            "metrics": metrics,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Training pipeline failed: {str(e)}")


@app.post("/rebalance/predict", summary="Predict portfolio weights with ML model (w08_predict_and_rebalance)",
    responses={
        409: {"description": "Conflict: Request already processing (Idempotency)"},
        422: {"description": "Unprocessable Entity: Risk/Slippage veto"},
        403: {"description": "Forbidden: Sanctions/Compliance veto"}
    })
async def rebalance_predict(req: RebalanceRequest, authorization: str = Header(..., description="Bearer <JWT_TOKEN>"), x_idempotency_key: str = Header(..., description="UUIDv4 string")):
    """
    Predicts portfolio weights using the trained LSTM model for the
    requested (or latest) date.
    This runs the Pipeline/w08_predict_and_rebalance.py pipeline.
    """
    try:
        from Pipeline.w08_predict_and_rebalance import predict_weights

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
