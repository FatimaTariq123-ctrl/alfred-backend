# Pipeline/w05_merge_price_macro.py

# ---------------------
"""
Merge stock-level OEP labeling panel with FRED macro data.

Adapted for Optimal Entry Price (OEP):
- Expects a labeled panel with a continuous target (e.g. 'Target_EntryPct').
- Merges macro/ FRED features and broadcasts them to each ticker row.
- Adds raw diffs for interest/unemployment-like macro series at horizons (22, 132, 252).
- Does not assume any ranking/Label columns.
"""

from __future__ import annotations
import os
import logging
from typing import Iterable, List
import pandas as pd
import numpy as np

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------- Defaults / Paths ---------------- #
DEFAULT_PANEL_PATH = "outputs/04_labeled_panel_OEP.csv"   # OEP labeled panel (continuous target)
DEFAULT_FRED_PATH = "outputs/03_fred_features.csv"
DEFAULT_OUT_PATH = "outputs/05_label_macro_features_OEP.csv"
SUMMARY_PATH = "outputs/05_label_macro_features_summary_OEP.csv"

# ---------------- Utility helpers ---------------- #
def _identify_macro_groups(cols: Iterable[str]):
    """
    Heuristics to find interest-rate-like and unemployment-like macro columns.
    Returns two lists: (interest_cols, unemployment_cols, other_macro_cols)
    """
    interest_keywords = ("rate", "yield", "interest", "treasury", "ffr", "fedfund", "bond")
    unemploy_keywords = ("unemp", "unemployment", "UNRATE")

    interest_cols = []
    unemployment_cols = []
    other_cols = []

    for c in cols:
        lc = c.lower()
        if any(k in lc for k in unemploy_keywords):
            unemployment_cols.append(c)
        elif any(k in lc for k in interest_keywords):
            interest_cols.append(c)
        else:
            other_cols.append(c)

    return interest_cols, unemployment_cols, other_cols

def _make_diff_features(df: pd.DataFrame, col: str, horizons: List[int]):
    """
    Compute raw difference over specified forward/backward horizons for a macro series.
    Differences computed as value_t - value_{t-h}, i.e., backward-looking diffs,
    using groupby(None) because macro series are time-indexed (same across tickers).
    """
    # Ensure temporal ordering
    s = df[['Date', col]].drop_duplicates(subset=['Date']).sort_values('Date').set_index('Date')[col]
    diffs = pd.DataFrame(index=s.index)
    for h in horizons:
        diffs[f"{col}_diff_{h}d"] = s.diff(periods=h)
    diffs = diffs.reset_index()
    return diffs

# ---------------- Core function ---------------- #
def build_feature_panel(
    panel_path: str = DEFAULT_PANEL_PATH,
    fred_path: str = DEFAULT_FRED_PATH,
    out_path: str = DEFAULT_OUT_PATH,
    summary_path: str = SUMMARY_PATH,
    macro_diff_horizons: List[int] = (22, 132, 252)
) -> pd.DataFrame:
    """
    Merge the labeled stock panel with FRED macro data and produce macro diff features.

    Args:
        panel_path: CSV containing the labeled stock panel (expects Date, Ticker, Target_EntryPct).
        fred_path: CSV containing macro series with a Date column.
        out_path: Output path for the merged stock-level panel with macro features.
        summary_path: Output path for a lightweight summary CSV.
        macro_diff_horizons: Horizons (in trading days) for raw macro diffs.

    Returns:
        merged_df: pd.DataFrame merged stock-level panel with macro columns and macro diffs.
    """
    logger.info("Loading labeling panel from %s", panel_path)
    panel_df = pd.read_csv(panel_path, parse_dates=["Date"])
    logger.info("Panel shape: %s", panel_df.shape)

    logger.info("Loading FRED macro data from %s", fred_path)
    fred_df = pd.read_csv(fred_path)
    # Accept both DATE / Date
    if 'DATE' in fred_df.columns and 'Date' not in fred_df.columns:
        fred_df = fred_df.rename(columns={'DATE': 'Date'})
    if 'Date' not in fred_df.columns:
        raise ValueError("FRED CSV must contain a 'Date' or 'DATE' column.")
    fred_df['Date'] = pd.to_datetime(fred_df['Date'])
    logger.info("FRED shape: %s", fred_df.shape)

    # Detect macro columns
    macro_cols = [c for c in fred_df.columns if c != 'Date']
    logger.info("Detected macro columns: %s", macro_cols)

    # Merge: broadcast macro values to every ticker row on matching Date
    logger.info("Merging panel with macro data on 'Date' (left join).")
    
    # Remove timezone info from panel_df dates to match FRED dates (which are naive)
    panel_df['Date'] = pd.to_datetime(panel_df['Date']).dt.tz_localize(None)
    
    merged = pd.merge(panel_df, fred_df, on='Date', how='left')
    logger.info("Post-merge shape: %s", merged.shape)

    # Sort and forward-fill/back-fill macro data per ticker to ensure no intermittent NaNs
    merged = merged.sort_values(['Ticker', 'Direction', 'Date'])
    # Forward/back-fill only the macro columns (do not overwrite per-ticker fields)
    def _ffill_macros(group):
        group[macro_cols] = group[macro_cols].ffill().bfill()
        return group
    merged = merged.groupby(['Ticker', 'Direction'], group_keys=False).apply(_ffill_macros).reset_index(drop=True)
    logger.info("Applied forward/backfill of macro columns per ticker and direction.")

    # Generate raw difference features for interest/unemployment-like macro series
    interest_cols, unemployment_cols, other_macro_cols = _identify_macro_groups(macro_cols)
    logger.info("Interest-like columns: %s", interest_cols)
    logger.info("Unemployment-like columns: %s", unemployment_cols)
    logger.info("Other macro columns (no diffs by default): %s", other_macro_cols)

    # Compute diffs for interest + unemployment columns (per OEP C2)
    # We'll compute diffs as backward-looking differences (t - t-h), then merge back on Date
    diff_frames = []
    for col in interest_cols + unemployment_cols:
        try:
            diffs = _make_diff_features(fred_df[['Date', col]], col, list(macro_diff_horizons))
            diff_frames.append(diffs)
            logger.info("Computed diffs for macro column '%s'", col)
        except Exception as e:
            logger.warning("Could not compute diffs for column '%s': %s", col, str(e))

    if diff_frames:
        # Merge all diffs into a single macro-diff frame keyed on Date
        diffs_merged = diff_frames[0][['Date']].copy()
        for dfc in diff_frames:
            # join on Date preserving all dates
            diffs_merged = diffs_merged.merge(dfc, on='Date', how='left')
        # Broadcast diffs into the merged stock panel (by Date)
        merged = merged.merge(diffs_merged, on='Date', how='left')
        logger.info("Merged macro diffs into stock-level panel. New shape: %s", merged.shape)
        # forward-fill diffs per ticker in case of sparse macro updates
        merged = merged.sort_values(['Ticker', 'Direction', 'Date'])
        merged = merged.groupby(['Ticker', 'Direction'], group_keys=False).apply(lambda g: g.ffill().bfill()).reset_index(drop=True)
    else:
        logger.info("No macro diffs were computed (no interest/unemployment-like columns found).")

    # Remove rows where the main regression target is missing to avoid unlabeled training rows
    possible_target_names = ['Target']
    existing_targets = [t for t in possible_target_names if t in merged.columns]
    if not existing_targets:
        logger.warning("No recognized continuous target column found among %s. Proceeding without dropping unlabeled rows.",
                       possible_target_names)
    else:
        target_col = existing_targets[0]
        before = len(merged)
        merged = merged.dropna(subset=[target_col])
        after = len(merged)
        logger.info("Dropped %d rows without target '%s' (kept %d rows).", (before - after), target_col, after)

    # Basic verification / quick sample print in logs (avoid printing whole frames)
    sample_macro_preview = [c for c in merged.columns if c in macro_cols][:5]
    logger.info("Sample columns in merged df: %s", list(merged.columns)[:12])
    if sample_macro_preview:
        logger.info("Example macro columns present: %s", sample_macro_preview)

    # Persist outputs
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    merged.to_csv(out_path, index=False)
    logger.info("Saved merged panel to: %s (rows=%d, cols=%d)", out_path, merged.shape[0], merged.shape[1])

    # Save a small summary (counts and basic macro stats per date)
    try:
        summary = (
            merged.groupby('Date')
            .agg(n_tickers=('Ticker', 'nunique'))
            .reset_index()
        )
        # Add mean of one of the macro columns as a quick health check (if present)
        if macro_cols:
            sample_macro = macro_cols[0]
            # Calculate the mean of the sample macro column per date
            daily_macro_mean = merged.groupby('Date')[sample_macro].mean().reset_index()
            summary = pd.merge(summary, daily_macro_mean, on='Date', how='left')
            summary = summary.rename(columns={sample_macro: f"mean_{sample_macro}"})
        summary.to_csv(summary_path, index=False)
        logger.info("Saved summary to: %s", summary_path)
    except Exception:
        logger.exception("Could not write summary file; continuing.")

    return merged


# ---------------- Script entry ---------------- #
if __name__ == "__main__":
    build_feature_panel()
