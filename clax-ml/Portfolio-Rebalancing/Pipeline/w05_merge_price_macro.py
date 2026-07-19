# Pipeline/w05_merge_price_macro.py

import pandas as pd
import numpy as np
import os
import logging

# ---------------- Logging ---------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------- PATHS ---------------- #
PANEL_PATH = "outputs/04_markowitz_labels.csv"
FRED_PATH = "outputs/03_fred_features.csv"
EXTRAS_PATH = "outputs/02_Yahoo_Extras.csv"
SHANGHAI_PATH = "outputs/06_Shanghai_OHLCV.csv"
HK_PATH = "outputs/05_HongKong_OHLCV.csv"
OUT_PATH = "outputs/05_label_macro_features_OEP.csv"


# ---------------- MAIN FUNCTION ---------------- #
def build_feature_panel():

    logger.info("🚀 Starting feature pipeline...")

    # ---------------- Load US Panel ---------------- #
    panel_df = pd.read_csv(PANEL_PATH)

    # Fix Date column
    if "Date" not in panel_df.columns:
        if "DATE" in panel_df.columns:
            panel_df = panel_df.rename(columns={"DATE": "Date"})
        elif "date" in panel_df.columns:
            panel_df = panel_df.rename(columns={"date": "Date"})
        else:
            raise ValueError(f"❌ {PANEL_PATH} has no Date column")

    panel_df["Date"] = pd.to_datetime(panel_df["Date"])

    if "Direction" not in panel_df.columns:
        panel_df["Direction"] = "long"

    if "Market" not in panel_df.columns:
        panel_df["Market"] = "US"

    # ---------------- Load Asia Data ---------------- #
    asia_frames = []

    # -------- Shanghai -------- #
    if os.path.exists(SHANGHAI_PATH):
        sh = pd.read_csv(SHANGHAI_PATH)

        if "Date" not in sh.columns:
            if "DATE" in sh.columns:
                sh = sh.rename(columns={"DATE": "Date"})
            elif "date" in sh.columns:
                sh = sh.rename(columns={"date": "Date"})
            else:
                raise ValueError(f"❌ {SHANGHAI_PATH} has no Date column")

        sh["Date"] = pd.to_datetime(sh["Date"])

        # Fix Adj Close
        if "Adj Close" in sh.columns:
            sh["Adj Close"] = sh["Adj Close"].fillna(sh["Close"])

        # Ensure ticker exists
        if "Ticker" not in sh.columns or sh["Ticker"].isna().all():
            sh["Ticker"] = "SH_UNKNOWN"

        sh["Ticker"] = sh["Ticker"].astype(str)

        sh["Market"] = "Shanghai"
        sh["Direction"] = "long"

        asia_frames.append(sh)
        logger.info(f"✅ Shanghai loaded: {sh.shape}")

    # -------- Hong Kong -------- #
    if os.path.exists(HK_PATH):
        hk = pd.read_csv(HK_PATH)

        if "Date" not in hk.columns:
            if "DATE" in hk.columns:
                hk = hk.rename(columns={"DATE": "Date"})
            elif "date" in hk.columns:
                hk = hk.rename(columns={"date": "Date"})
            else:
                raise ValueError(f"❌ {HK_PATH} has no Date column")

        hk["Date"] = pd.to_datetime(hk["Date"])

        # Fix Adj Close
        if "Adj Close" in hk.columns:
            hk["Adj Close"] = hk["Adj Close"].fillna(hk["Close"])

        # Ensure ticker exists
        if "Ticker" not in hk.columns or hk["Ticker"].isna().all():
            hk["Ticker"] = "HK_UNKNOWN"

        hk["Ticker"] = hk["Ticker"].astype(str)

        hk["Market"] = "HongKong"
        hk["Direction"] = "long"

        asia_frames.append(hk)
        logger.info(f"✅ Hong Kong loaded: {hk.shape}")

    # ---------------- SAFE MERGE ---------------- #
    if asia_frames:
        asia_df = pd.concat(asia_frames, ignore_index=True)

        # Clean column names
        asia_df.columns = [c.strip() for c in asia_df.columns]
        panel_df.columns = [c.strip() for c in panel_df.columns]

        # Create full column set
        all_cols = set(panel_df.columns).union(set(asia_df.columns))

        # Add missing columns
        for col in all_cols:
            if col not in panel_df.columns:
                panel_df[col] = np.nan
            if col not in asia_df.columns:
                asia_df[col] = np.nan

        # Align
        asia_df = asia_df[panel_df.columns]

        # Combine
        panel_df = pd.concat([panel_df, asia_df], ignore_index=True)

    logger.info(f"✅ Combined dataset shape: {panel_df.shape}")

    # ---------------- Load Macro ---------------- #
    fred_df = pd.read_csv(FRED_PATH)

    if "DATE" in fred_df.columns:
        fred_df = fred_df.rename(columns={"DATE": "Date"})
    elif "date" in fred_df.columns:
        fred_df = fred_df.rename(columns={"date": "Date"})

    fred_df["Date"] = pd.to_datetime(fred_df["Date"])

    extras_df = pd.read_csv(EXTRAS_PATH)

    if "date" in extras_df.columns:
        extras_df = extras_df.rename(columns={"date": "Date"})

    extras_df["Date"] = pd.to_datetime(extras_df["Date"])

    if "Ticker" in extras_df.columns:
        extras_df = extras_df.drop(columns=["Ticker"])

    # ---------------- Merge Macro ---------------- #
    macro_df = pd.merge(fred_df, extras_df, on="Date", how="outer")
    macro_df = macro_df.sort_values("Date").ffill().bfill()

    merged = pd.merge(panel_df, macro_df, on="Date", how="left")

    # ---------------- SAFE MACRO HANDLING ---------------- #
    exclude_cols = ["Date", "Ticker", "Direction", "Market",
                    "Open", "High", "Low", "Close", "Volume", "Adj Close"]

    macro_cols = [c for c in macro_df.columns if c not in exclude_cols]
    macro_cols = [c for c in macro_cols if c in merged.columns]

    merged = merged.sort_values(["Ticker", "Direction", "Date"])

    if macro_cols:
        merged[macro_cols] = merged.groupby(["Ticker", "Direction"])[macro_cols].transform(
            lambda x: x.ffill().bfill()
        )

    # ---------------- Macro Diff Features ---------------- #
    for col in macro_cols:
        if any(k in col.lower() for k in ["rate", "yield", "unemp"]):
            merged[f"{col}_diff_1"] = merged.groupby("Ticker")[col].diff(1)
            merged[f"{col}_diff_12"] = merged.groupby("Ticker")[col].diff(12)
            merged[f"{col}_diff_24"] = merged.groupby("Ticker")[col].diff(24)

    # ---------------- FINAL ---------------- #
    merged = merged.fillna(0)

    # 🔍 DEBUG CHECK
    print("\n📊 MARKET DISTRIBUTION:")
    print(merged["Market"].value_counts())

    print("\n📊 ASIA SAMPLE:")
    print(merged[merged["Market"] != "US"][["Date", "Ticker", "Market"]].head())

    logger.info("✅ Asia + US data successfully merged")

    # ---------------- Save ---------------- #
    os.makedirs("outputs", exist_ok=True)
    merged.to_csv(OUT_PATH, index=False)

    logger.info(f"🎯 Saved final dataset: {merged.shape}")


# ---------------- RUN ---------------- #
if __name__ == "__main__":
    build_feature_panel()
