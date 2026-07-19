# Pipeline/w06_Feature_Engg.py

import os
import logging
import pandas as pd
import numpy as np
from sklearn.decomposition import PCA
import joblib

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

INPUT_PATH = "outputs/05_label_macro_features_OEP.csv"
OUT_PATH = "outputs/06_final_features.csv"


# ---------------- LOAD ---------------- #
def load_data():
    df = pd.read_csv(INPUT_PATH, parse_dates=["Date"])
    logger.info(f"Loaded data: {df.shape}")
    return df


# ---------------- RETURNS ---------------- #
def add_pct_change(df):
    logger.info("Adding return features...")

    price_cols = ["Open", "High", "Low", "Close", "Volume"]

    for col in price_cols:
        if col in df.columns:
            df[f"{col}_ret_1"] = df.groupby(["Market", "Ticker"])[col].pct_change(1)
            df[f"{col}_ret_5"] = df.groupby(["Market", "Ticker"])[col].pct_change(5)
            df[f"{col}_ret_22"] = df.groupby(["Market", "Ticker"])[col].pct_change(22)

    return df


# ---------------- ECOD ---------------- #
def ecod(df):
    logger.info("Applying ECOD normalization...")

    exclude = ["Date", "Ticker", "Direction", "Market",
               "Open", "High", "Low", "Close", "Volume", "Adj Close"]

    feature_cols = [c for c in df.columns
                    if c not in exclude
                    and df[c].dtype in [np.float64, np.int64]]

    for col in feature_cols:
        df[f"{col}_ecod"] = df.groupby(["Market", "Ticker"])[col].transform(
            lambda x: x.rank(pct=True)
        )

    return df


# ---------------- PCA ---------------- #
def apply_pca(df):
    logger.info("Applying PCA...")

    exclude = ["Date", "Ticker", "Direction", "Market"]

    feature_cols = [c for c in df.columns
                    if c not in exclude
                    and df[c].dtype in [np.float64, np.int64]
                    and not c.startswith("PCA_")]

    if len(feature_cols) < 5:
        logger.warning("Not enough features for PCA")
        return df

    # IMPORTANT: Use Market separation to avoid mixing distributions
    pca_results = []

    for market in df["Market"].unique():

        df_m = df[df["Market"] == market]

        df_pivot = df_m.pivot_table(index="Date", columns="Ticker", values=feature_cols)
        df_pivot.columns = ["_".join(map(str, c)) for c in df_pivot.columns]

        df_pivot = df_pivot.ffill().bfill().fillna(0)
        df_pivot = df_pivot.replace([np.inf, -np.inf], 0)

        if df_pivot.shape[1] < 5:
            logger.warning(f"Skipping PCA for {market} (not enough features)")
            continue

        pca = PCA(n_components=0.95)
        X_pca = pca.fit_transform(df_pivot)

        # Save model per market
        os.makedirs("models", exist_ok=True)
        joblib.dump(pca, f"models/pca_{market}.joblib")

        pca_df = pd.DataFrame(
            X_pca,
            index=df_pivot.index,
            columns=[f"PCA_{market}_{i+1}" for i in range(X_pca.shape[1])]
        ).reset_index()

        pca_df["Market"] = market
        pca_results.append(pca_df)

        logger.info(f"{market} PCA → {X_pca.shape[1]} components")

    # Merge PCA back
    for pca_df in pca_results:
        df = df.merge(pca_df, on=["Date", "Market"], how="left")

    return df


# ---------------- MAIN ---------------- #
def build_features():

    df = load_data()

    # Step 1: Returns
    df = add_pct_change(df)

    # Step 2: ECOD
    df = ecod(df)

    # Step 3: PCA (market-wise)
    df = apply_pca(df)

    # Cleanup
    df = df.replace([np.inf, -np.inf], 0).fillna(0)

    print("\n📊 MARKET DISTRIBUTION:")
    print(df["Market"].value_counts())

    print("\n📊 SAMPLE:")
    print(df[["Date", "Ticker", "Market"]].head())

    os.makedirs("outputs", exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    logger.info(f"✅ Final features saved: {df.shape}")


# ---------------- RUN ---------------- #
if __name__ == "__main__":
    build_features()
