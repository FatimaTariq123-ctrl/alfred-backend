# Pipeline/w04a_Markowitz_Labels.py

import os
import logging
import pandas as pd
import numpy as np
from pypfopt.efficient_frontier import EfficientFrontier
from pypfopt import risk_models, expected_returns

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------- Defaults / Paths ---------------- #
DEFAULT_STOCK_PRICES_PATH = "outputs/02_Yahoo_Stocks.csv"
DEFAULT_OUT_PATH = "outputs/04_markowitz_labels.csv"

# ---------------- Core function ---------------- #
def build_markowitz_labels(
    stock_prices_path: str = DEFAULT_STOCK_PRICES_PATH,
    out_path: str = DEFAULT_OUT_PATH,
    lookback_years: int = 1, # for historical returns and not less than 100 days
    target_annual_return: float = 0.20, # 20% target
    rebalance_freq_days: int = 22 # 22 trading days for lagging 
) -> pd.DataFrame:
    """
    Calculates optimal portfolio weights using Markowitz Optimal Sharpe Ratio.
    Weights are lagged to serve as training targets.

    Args:
        stock_prices_path: Path to the CSV containing stock prices (expects Date, Ticker, Close).
        out_path: Output path for the DataFrame containing optimal portfolio weights.
        lookback_years: Number of years to consider for historical returns calculation.
        target_annual_return: The target annual return for portfolio optimization.
        rebalance_freq_days: The number of days to lag the weights for training target alignment.

    Returns:
        pd.DataFrame: A DataFrame with 'Date', 'Ticker', and 'Target_Weight' columns.
    """
    logger.info("Starting Markowitz Optimal Sharpe Ratio portfolio construction...")

    # Load stock prices
    try:
        prices_df = pd.read_csv(stock_prices_path, parse_dates=['date'])
        prices_df = prices_df.rename(columns={'date': 'Date'})
        prices_df = prices_df.pivot(index='Date', columns='Ticker', values='Close')
    except Exception as e:
        logger.error(f"Error loading or pivoting stock prices from {stock_prices_path}: {e}")
        return pd.DataFrame()

    # Ensure prices are sorted
    prices_df = prices_df.sort_index()

    # Calculate daily returns
    returns_df = prices_df.pct_change().dropna()
    
    if returns_df.empty:
        logger.warning("No returns data available after calculating percentage changes.")
        return pd.DataFrame()

    all_weights_list = []
    # We will compute weights at a weekly frequency to speed up the process,
    # as daily re-optimization is computationally expensive and often unnecessary.
    unique_dates = returns_df.index.to_series().resample('W').last().dropna()

    for current_date in unique_dates:
        # Define the lookback window for this optimization point
        window_start_date = current_date - pd.DateOffset(years=lookback_years)
        
        # Extract data for the lookback window
        window_prices = prices_df.loc[window_start_date:current_date]
        
        # Skip if not enough history
        if len(window_prices) < 100:
            continue

        try:
            # Calculate expected returns and a *shrinkage* covariance matrix for the window
            # Using Ledoit-Wolf shrinkage via PyPortfolioOpt's CovarianceShrinkage to obtain
            # a more stable, positive semidefinite covariance estimate and reduce
            # LDL/KKT factorization errors in the optimizer.
            mu = expected_returns.mean_historical_return(window_prices, frequency=252)
            S = risk_models.CovarianceShrinkage(window_prices, frequency=252).ledoit_wolf()

            # Markowitz optimization
            ef = EfficientFrontier(mu, S, weight_bounds=(0, 1)) # Long only constraint
            
            # Find the portfolio that meets the target return with minimum volatility
            # This is a common interpretation of optimizing with a target return
            ef.efficient_return(target_annual_return)
            
            # Get weights
            raw_weights = ef.clean_weights()
            weights_df = pd.DataFrame.from_dict(raw_weights, orient='index', columns=['Target_Weight'])
            weights_df['Date'] = current_date
            weights_df.reset_index(inplace=True)
            weights_df.rename(columns={'index': 'Ticker'}, inplace=True)
            
            all_weights_list.append(weights_df)

        except Exception as e:
            logger.warning(f"Could not optimize portfolio for {current_date}: {e}")
            continue
            
    if not all_weights_list:
        logger.warning("No portfolio weights could be calculated.")
        return pd.DataFrame()

    final_weights_df = pd.concat(all_weights_list, ignore_index=True)

    # Shift weights backward by `rebalance_freq_days` to align for training
    final_weights_df['Date'] = final_weights_df['Date'] - pd.to_timedelta(rebalance_freq_days, unit='D')
    
    # Fill forward the weights to create a daily signal
    # This means the calculated weights will be the target until the next rebalance point
    full_date_range = pd.date_range(start=final_weights_df['Date'].min(), end=prices_df.index.max(), freq='D')
    daily_targets = final_weights_df.pivot(index='Date', columns='Ticker', values='Target_Weight')
    daily_targets = daily_targets.reindex(full_date_range).ffill()
    
    # Unpivot to get back to long format
    daily_targets_long = daily_targets.reset_index().melt(id_vars='index', var_name='Ticker', value_name='Target_Weight')
    daily_targets_long.rename(columns={'index': 'Date'}, inplace=True)
    daily_targets_long.dropna(subset=['Target_Weight'], inplace=True)

    logger.info("Markowitz portfolio construction complete. Output shape: %s", daily_targets_long.shape)

    # Persist outputs
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    daily_targets_long.to_csv(out_path, index=False)
    logger.info("Saved Markowitz labels to: %s", out_path)

    return daily_targets_long

# ---------------- Script entry ---------------- #
if __name__ == "__main__":
    build_markowitz_labels()