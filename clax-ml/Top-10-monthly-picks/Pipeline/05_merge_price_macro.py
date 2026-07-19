# Pipeline/04_merge_panel_macro.py
"""
Labeling Panel + FRED
---------------------
Features Builder
-----------------
Merge stock-level labeling panel with macroeconomic data (FRED),
creating a unified stock-level feature dataset for modeling.
"""

import os
import pandas as pd


# ------------------------------
# Core function
# ------------------------------
def build_feature_panel(
    panel_path="outputs/04_labeled_panel.csv",
    fred_path="outputs/03_fred_features.csv",
    out_path="outputs/05_label_macro_features.csv"
):
    """
    Merge stock-level labeling panel with FRED macro data.

    Args:
        panel_path (str): Path to labeled panel CSV
        fred_path (str): Path to FRED macro dataset CSV
        out_path (str): Output path for merged stock-level panel

    Returns:
        pd.DataFrame: Final stock-level feature panel
    """
    print("📂 Loading datasets...")

    # Load labeling panel
    panel_df = pd.read_csv(panel_path, parse_dates=["Date"])
    print(f"   → Labeling panel shape: {panel_df.shape}")

    # Load FRED macro data
    fred_df = pd.read_csv(fred_path)
    if 'DATE' in fred_df.columns:
        fred_df.rename(columns={"DATE": "Date"}, inplace=True)
    elif 'Date' not in fred_df.columns:
        raise ValueError("FRED CSV has no 'Date' or 'DATE' column")
    fred_df['Date'] = pd.to_datetime(fred_df['Date'])
    print(f"   → FRED dataset shape: {fred_df.shape}")

    # Merge on Date (macro gets broadcast across tickers)
    merged = pd.merge(panel_df, fred_df, on="Date", how="left")

    # Forward-fill missing macro values per ticker
    merged = merged.sort_values(["Ticker", "Date"])
    merged = merged.groupby("Ticker").apply(lambda g: g.ffill().bfill()).reset_index(drop=True)

    # Verify merging
    print("✅ Merging check:")
    macro_cols = fred_df.columns.drop("Date")[:3].tolist()
    print(merged.head()[["Date", "Ticker", "Label"] + macro_cols])

    print(f"✅ Final feature panel shape: {merged.shape}")
    print(f"📅 Date range: {merged['Date'].min().date()} → {merged['Date'].max().date()}")
    print(f"🪙 Example columns: {list(merged.columns)[:10]} ...")

    # Save
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    merged.to_csv(out_path, index=False)
    print(f"💾 Saved merged stock-level panel → {os.path.abspath(out_path)}")

    return merged

# ------------------------------
# Script entry
# ------------------------------
if __name__ == "__main__":
    build_feature_panel()
