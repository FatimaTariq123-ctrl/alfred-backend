# Pipeline/w04_Labels.py
# ---------------------
"""
Optimal Entry Price (OEP) Labeling Pipeline
-------------------------------------------
Computes a continuous label representing the optimal future entry price
distance (downside potential) for each stock over specified horizons.
"""

import os
import logging
import pandas as pd
import numpy as np

# ---------------- Logging ---------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------- File Paths ---------------- #
PRICE_FILE = "outputs/02_Yahoo_Stocks.csv"
MEMBERSHIP_FILE = "outputs/01_SP500_membership_matrix.csv"
LABELED_PANEL_FILE = "outputs/04_labeled_panel_OEP.csv"
SUMMARY_FILE = "outputs/04_labeling_summary_OEP.csv"


# ---------------- Core Functions ---------------- #
def compute_future_extrema(df: pd.DataFrame, horizons=(22, 132, 252)) -> pd.DataFrame:
    """
    Compute max/min closing prices for multiple forward horizons per ticker.

    Args:
        df (pd.DataFrame): Stock price data with ['Ticker', 'Date', 'Close']
        horizons (tuple): Forward window lengths in trading days
    """
    df = df.copy()
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(['Ticker', 'Date'])

    for h in horizons:
        df[f'MaxFuture_{h}'] = (
            df.groupby('Ticker')['Close']
            .transform(lambda x: x.shift(-1).rolling(window=h, min_periods=1).max())
        )
        df[f'MinFuture_{h}'] = (
            df.groupby('Ticker')['Close']
            .transform(lambda x: x.shift(-1).rolling(window=h, min_periods=1).min())
        )

    logger.info(f"Computed future extrema for horizons: {horizons}")
    return df


def compute_direction_aware_targets(df: pd.DataFrame, horizon: int = 22) -> pd.DataFrame:
    """
    Derive the direction-aware percent-gap targets for buy and sell trades.

    Args:
        df (pd.DataFrame): DataFrame with future extrema
        horizon (int): Horizon used for target computation
    """
    df = df.copy()

    min_col = f"MinFuture_{horizon}"
    max_col = f"MaxFuture_{horizon}"
    if min_col not in df.columns or max_col not in df.columns:
        raise KeyError(f"Missing required columns: {min_col}, {max_col}")

    # Compute optimal limit prices from future extrema
    # Buy: limit below current price (profit from future drop)
    # Sell: limit above current price (profit-taking on strength)
    df['Optimal_Buy'] = df[min_col] * 0.9
    df['Optimal_Sell'] = df[max_col] * 1.1

    # Percent-gap targets relative to optimal limit levels
    # Buy targets: (Close - Optimal) / Optimal. 
    #   Close > Optimal -> Positive (Waiting for drop)
    #   Close <= Optimal -> 0 (Buy Now)
    df['Target_Buy'] = (df['Close'] - df['Optimal_Buy']) / df['Optimal_Buy']
    df['Target_Buy'] = df['Target_Buy'].clip(lower=0)

    # Sell targets: (Close - Optimal) / Optimal.
    #   Close < Optimal -> Negative (Waiting for rise)
    #   Close = Optimal -> 0 (Sell Now)
    #   Close > Optimal -> Positive (Exceeded). 
    # Feedback says 'Target < 0' for exceeded is even better, and '-abs' activation is used.
    # Thus we use -abs() to ensure both 'waiting' and 'exceeded' are negative, 
    # where 0 is the exact execution threshold.
    df['Target_Sell'] = (df['Close'] - df['Optimal_Sell']) / df['Optimal_Sell']
    df['Target_Sell'] = -df['Target_Sell'].abs()

    # Unpivot the data
    buy_df = df[['Date', 'Ticker', 'Close', 'Target_Buy']].copy()
    buy_df.rename(columns={'Target_Buy': 'Target'}, inplace=True)
    buy_df['Direction'] = 1 # 1 for buy

    sell_df = df[['Date', 'Ticker', 'Close', 'Target_Sell']].copy()
    sell_df.rename(columns={'Target_Sell': 'Target'}, inplace=True)
    sell_df['Direction'] = 0 # 0 for sell

    unified_df = pd.concat([buy_df, sell_df], ignore_index=True)
    
    # Drop rows where target is NaN
    unified_df.dropna(subset=['Target'], inplace=True)

    logger.info(f"Computed direction-aware targets. Total rows: {len(unified_df)}")

    return unified_df


def apply_membership(df: pd.DataFrame, membership_df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply SP500 membership filter to retain tradable tickers only.
    """
    tradable_tickers = set(membership_df.columns[membership_df.iloc[0] == 1])
    df['Tradable'] = df['Ticker'].isin(tradable_tickers).astype(int)
    tradable_df = df[df['Tradable'] == 1].copy()

    logger.info(f"Applied membership filter. Tradable tickers: {len(tradable_tickers)}")
    return tradable_df


def run_pipeline():
    """
    Execute the full Optimal Entry Price labeling pipeline.
    """
    logger.info("Loading input datasets...")
    price_data = pd.read_csv(PRICE_FILE)
    if 'date' in price_data.columns:
        price_data.rename(columns={'date': 'Date'}, inplace=True)
    membership_data = pd.read_csv(MEMBERSHIP_FILE, index_col=0)

    logger.info("Running OEP labeling pipeline...")
    price_data = compute_future_extrema(price_data)
    price_data = apply_membership(price_data, membership_data)
    labeled_data = compute_direction_aware_targets(price_data, horizon=22)

    os.makedirs(os.path.dirname(LABELED_PANEL_FILE), exist_ok=True)
    labeled_data.to_csv(LABELED_PANEL_FILE, index=False)
    logger.info(f"Saved labeled panel -> {LABELED_PANEL_FILE} ({len(labeled_data)} rows)")
    
    logger.info("OEP labeling pipeline completed successfully.")


# ---------------- Entry ---------------- #
if __name__ == "__main__":
    run_pipeline()

