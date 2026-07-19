# labels.py
import os
import logging
import pandas as pd
import numpy as np

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------- File Paths ---------------- #
PRICE_FILE = "outputs/02_Yahoo_Stocks.csv"
MEMBERSHIP_FILE = "outputs/01_SP500_Membership_Matrix.csv"
LABELED_PANEL_FILE = "outputs/04_labeled_panel.csv"
SUMMARY_FILE = "outputs/04_labeling_summary.csv"

# ---------------- Core Functions ---------------- #
def compute_forward_returns(df: pd.DataFrame, horizon: int = 22) -> pd.DataFrame:
    df = df.copy()
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(['Ticker','Date'])
    df['ForwardClose'] = df.groupby('Ticker')['Close'].shift(-horizon)
    df['ForwardReturn'] = df['ForwardClose'] / df['Close'] - 1

    # drop last `horizon` rows per ticker to avoid NaN
    # df = df.groupby('Ticker', group_keys=False).apply(lambda g: g.iloc[:-horizon])
    logger.info("Forward returns computed. Valid rows: %d", df['ForwardReturn'].notna().sum())
    return df

def apply_membership(df: pd.DataFrame, membership_df: pd.DataFrame) -> pd.DataFrame:
    """Snapshot membership: all dates use the first row of membership"""
    logger.info("Applying snapshot membership...")
    tradable_tickers = set(membership_df.iloc[0][membership_df.iloc[0]==1].index)
    df['Tradable'] = df['Ticker'].isin(tradable_tickers).astype(int)
    logger.info("Applied membership; tradable tickers=%d", len(tradable_tickers))
    # Filter out non-tradable tickers immediately
    return df[df['Tradable'] == 1].drop(columns=['Tradable'])

def filter_by_dollar_volume(df: pd.DataFrame, window: int = 20, top_n: int = 50) -> pd.DataFrame:
    """
    Filter universe to top N stocks by average dollar volume.
    """
    logger.info(f"Filtering universe to top {top_n} by {window}-day dollar volume...")
    df = df.copy()
    df['DollarVolume'] = df['Close'] * df['Volume']
    
    # Calculate rolling dollar volume
    df['AvgDollarVolume'] = df.groupby('Ticker')['DollarVolume'].transform(
        lambda x: x.rolling(window, min_periods=window).mean()
    )

    # Rank tickers by dollar volume for each date
    df = df.dropna(subset=['AvgDollarVolume'])
    df['VolumeRank'] = df.groupby('Date')['AvgDollarVolume'].rank(ascending=False, method='first')

    # Filter for top N
    filtered_df = df[df['VolumeRank'] <= top_n].copy()

    # Clean up intermediate columns
    filtered_df = filtered_df.drop(columns=['DollarVolume', 'AvgDollarVolume', 'VolumeRank'])

    logger.info("Dollar volume filtering complete. Rows changed from %d to %d", len(df), len(filtered_df))
    return filtered_df

def label_top_performers(df: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    # Split into labeled (historical) and unlabeled (recent inference) sets
    labeled_mask = df['ForwardReturn'].notna()
    df_labeled = df[labeled_mask].copy()
    df_unlabeled = df[~labeled_mask].copy()

    if df_labeled.empty:
        logger.warning("No rows to label!")
    else:
        df_labeled['Rank'] = df_labeled.groupby('Date')['ForwardReturn'].rank(method='first', ascending=False)
        df_labeled['Label'] = (df_labeled['Rank'] <= top_k).astype(int)
        logger.info("Top-%d performers labeled: %d positives over %d dates",
                    top_k, df_labeled['Label'].sum(), df_labeled['Date'].nunique())
    
    # For unlabeled data, set Rank and Label to NaN
    df_unlabeled['Rank'] = np.nan
    df_unlabeled['Label'] = np.nan

    # Combine back
    df_final = pd.concat([df_labeled, df_unlabeled], axis=0)
    return df_final.sort_values(['Date', 'Ticker'])

def save_outputs(df: pd.DataFrame):
    os.makedirs(os.path.dirname(LABELED_PANEL_FILE), exist_ok=True)
    df.to_csv(LABELED_PANEL_FILE, index=False)
    if not df.empty:
        summary = df.groupby('Date').agg(
            universe_size=('Ticker','nunique'),
            n_labeled=('Label','sum'),
            avg_forward_return=('ForwardReturn','mean')
        ).reset_index()
    else:
        summary = pd.DataFrame(columns=['Date','universe_size','n_labeled','avg_forward_return'])
    summary.to_csv(SUMMARY_FILE, index=False)
    logger.info("Saved panel: %s (%d rows), summary: %s (%d dates)",
                LABELED_PANEL_FILE, len(df), SUMMARY_FILE, len(summary))

# ---------------- Main Pipeline ---------------- #
def run_pipeline(horizon: int = 22, top_k: int = 10):
    logger.info("Loading input files...")
    price_data = pd.read_csv(PRICE_FILE)
    if 'date' in price_data.columns:
        price_data.rename(columns={'date':'Date'}, inplace=True)
    membership_data = pd.read_csv(MEMBERSHIP_FILE, index_col=0)

    logger.info("Running labeling pipeline...")
    price_data = compute_forward_returns(price_data, horizon=horizon)
    price_data = apply_membership(price_data, membership_data)
    price_data = filter_by_dollar_volume(price_data) # <-- New step
    labeled_data = label_top_performers(price_data, top_k=top_k)
    save_outputs(labeled_data)
    logger.info("Pipeline completed successfully.")

# ---------------- Entry ---------------- #
if __name__ == "__main__":
    run_pipeline(horizon=22, top_k=10)
