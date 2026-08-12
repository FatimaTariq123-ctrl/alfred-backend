-- Migration Script: ML Feature Tables

-- clax_oep_features stores the daily curated features for the Optimal Entry Price model.
-- We explicitly define it so it can be managed via migrations rather than relying solely on Pandas' to_sql table creation.
CREATE TABLE IF NOT EXISTS clax_oep_features (
    "Date" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    "Ticker" VARCHAR(20) NOT NULL,
    "Direction" BIGINT NOT NULL,
    "Close" DOUBLE PRECISION,
    "Target" DOUBLE PRECISION,
    -- ECOD/Derivative Features
    "StockPct_22" DOUBLE PRECISION,
    "StockPct_132" DOUBLE PRECISION,
    "StockPct_252" DOUBLE PRECISION,
    "CPIAUCSL_pct_22" DOUBLE PRECISION,
    "CPIAUCSL_pct_132" DOUBLE PRECISION,
    "CPIAUCSL_pct_252" DOUBLE PRECISION,
    "GS10_diff_22d" DOUBLE PRECISION,
    "GS10_diff_132d" DOUBLE PRECISION,
    "GS10_diff_252d" DOUBLE PRECISION,
    "DGS5_diff_22d" DOUBLE PRECISION,
    "DGS5_diff_132d" DOUBLE PRECISION,
    "DGS5_diff_252d" DOUBLE PRECISION,
    "DGS2_diff_22d" DOUBLE PRECISION,
    "DGS2_diff_132d" DOUBLE PRECISION,
    "DGS2_diff_252d" DOUBLE PRECISION,
    "UNRATE_diff_22d" DOUBLE PRECISION,
    "UNRATE_diff_132d" DOUBLE PRECISION,
    "UNRATE_diff_252d" DOUBLE PRECISION,
    "UNRATE_cycle_sin" DOUBLE PRECISION,
    "UNRATE_cycle_cos" DOUBLE PRECISION,
    "FEDFUNDS_cycle_sin" DOUBLE PRECISION,
    "FEDFUNDS_cycle_cos" DOUBLE PRECISION,
    "Sentiment_22" DOUBLE PRECISION,
    "Dispersion_22" DOUBLE PRECISION,
    "Sentiment_132" DOUBLE PRECISION,
    "Dispersion_132" DOUBLE PRECISION,
    "Sentiment_252" DOUBLE PRECISION,
    "Dispersion_252" DOUBLE PRECISION,
    "dow_sin" DOUBLE PRECISION,
    "month_sin" DOUBLE PRECISION,
    "day_sin" DOUBLE PRECISION,
    -- Orthogonal PCA components will be dynamically added as PCA_1, PCA_2, etc. by pandas to_sql,
    -- but we establish the primary key and base structure here.
    PRIMARY KEY ("Date", "Ticker", "Direction")
);

-- Index for fast single-ticker inference lookup
CREATE INDEX IF NOT EXISTS idx_oep_ticker_dir_date ON clax_oep_features ("Ticker", "Direction", "Date" DESC);


-- clax_top10_features stores the curated features for the Top 10 Monthly Picks LSTM model.
CREATE TABLE IF NOT EXISTS clax_top10_features (
    "Date" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    "Ticker" VARCHAR(20) NOT NULL,
    "Close" DOUBLE PRECISION,
    "Volume" DOUBLE PRECISION,
    "Return_22d" DOUBLE PRECISION,
    "Volume_22d" DOUBLE PRECISION,
    "Return_132d" DOUBLE PRECISION,
    "Volume_132d" DOUBLE PRECISION,
    "Return_252d" DOUBLE PRECISION,
    "Volume_252d" DOUBLE PRECISION,
    "CPI_22d" DOUBLE PRECISION,
    "Unemployment_22d" DOUBLE PRECISION,
    "10Y_Yield_22d" DOUBLE PRECISION,
    "5Y_Yield_22d" DOUBLE PRECISION,
    "2Y_Yield_22d" DOUBLE PRECISION,
    "CPI_132d" DOUBLE PRECISION,
    "Unemployment_132d" DOUBLE PRECISION,
    "10Y_Yield_132d" DOUBLE PRECISION,
    "5Y_Yield_132d" DOUBLE PRECISION,
    "2Y_Yield_132d" DOUBLE PRECISION,
    "CPI_252d" DOUBLE PRECISION,
    "Unemployment_252d" DOUBLE PRECISION,
    "10Y_Yield_252d" DOUBLE PRECISION,
    "5Y_Yield_252d" DOUBLE PRECISION,
    "2Y_Yield_252d" DOUBLE PRECISION,
    "Sentiment" DOUBLE PRECISION,
    "Dispersion" DOUBLE PRECISION,
    "dow_sin" DOUBLE PRECISION,
    "month_sin" DOUBLE PRECISION,
    "day_sin" DOUBLE PRECISION,
    PRIMARY KEY ("Date", "Ticker")
);

-- Index for fast date-based lookup (e.g. trailing 66 days)
CREATE INDEX IF NOT EXISTS idx_top10_date ON clax_top10_features ("Date" DESC);
