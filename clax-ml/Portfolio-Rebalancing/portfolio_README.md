# Portfolio Rebalancing Agent — Testing Guide

## What This Agent Does
A global portfolio optimizer that combines US stocks, crypto (BTC, ETH, SOL, ADA, XRP, DOGE), Hong Kong, and Shanghai stocks. Uses Markowitz theory to calculate mathematically optimal money allocation across assets, then generates specific BUY/SELL rebalancing instructions.

## Pipeline Flow
```
w01 (Tickers) → w02 (Alpaca) → w03 (FRED) → w04 (Crypto) → w05 (HK) → w06 (Shanghai) → w04a (Markowitz Labels) → w05 (Merge) → w06 (Features) → w07 (Train) → w08 (Predict & Rebalance)
```

## Prerequisites
- Python 3.12
- Virtual environment activated
- `.env` file with:
```
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
FRED_API_KEY=your_fred_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

## Environment Setup
```bash
"/c/Users/<you>/AppData/Local/Programs/Python/Python312/python.exe" -m venv venv
source venv/Scripts/activate
grep -v "jupyterlab-plotly" requirements.txt | grep -v "pypfopt" > requirements_fixed.txt
pip install -r requirements_fixed.txt
pip install pyportfolioopt
```

## How to Run
```bash
# Data loaders
python Data_loaders/w01_SP500_Tickers_and_Membership.py
python Data_loaders/w02_Alpaca.py        # Created locally — Yahoo geo-blocked
python Data_loaders/w03_Fred.py
python Data_loaders/w04_Crypto.py
python Data_loaders/w05_HongKong.py      # Returns empty if Yahoo geo-blocked
python Data_loaders/w06_Shanghai.py      # Returns empty if Yahoo geo-blocked

# Pipeline
python Pipeline/w04a_Markowitz_Labels.py
python Pipeline/w05_merge_price_macro.py
python Pipeline/w06_Feature_Engg.py
python Pipeline/w07_train_model.py
python Pipeline/w08_predict_and_rebalance.py
```

Or run the test script:
```bash
python test_pipeline.py
```

## Test Results

### Data Loaders
| Script | Status | Output |
|--------|--------|--------|
| w01 — S&P500 Tickers | ✅ PASS | 500 tickers verified via Alpaca |
| w02 — Alpaca Stock Data (IEX) | ✅ PASS | 73,731 rows fetched |
| w03 — FRED Macro | ✅ PASS | 3,029 rows, 2015→2026 |
| w04 — Crypto (BTC/ETH/SOL/ADA/XRP/DOGE) | ✅ PASS | 5,903 rows |
| w05 — Hong Kong Stocks | ❌ SKIP | Yahoo geo-blocked — empty placeholder used |
| w06 — Shanghai Stocks | ❌ SKIP | Yahoo geo-blocked — empty placeholder used |

### Pipeline
| Script | Status | Output |
|--------|--------|--------|
| w04a — Markowitz Labels | ✅ PASS | 95,600 rows |
| w05 — Merge Price + Macro | ✅ PASS | 95,600 rows × 32 cols (US only) |
| w06 — Feature Engineering | ✅ PASS | 95,600 rows × 77 features |
| w07 — Train Model | ✅ PASS | 100 epochs — MAE: 0.020, Cosine Sim: 0.637 |
| w08 — Predict & Rebalance | ✅ PASS | Portfolio weights + BUY/SELL instructions generated |

### Final Portfolio Output (Sample)
```
Date        Ticker  Predicted_Weight
2026-06-18  AAPL    0.021469
2026-06-18  ABT     0.023799
2026-06-18  ALL     0.023525
2026-06-18  AME     0.022803

Rebalancing Instructions:
AAPL  BUY   +0.0015
AXP   SELL  -0.0031
ABT   BUY   +0.0038
```
~2% allocation across 50 diversified US stocks with specific BUY/SELL signals per ticker.

### Issues Encountered & Resolved
| Issue | Fix |
|-------|-----|
| jupyterlab-plotly not found | Removed from requirements |
| pypfopt not found | Replaced with pyportfolioopt |
| Yahoo geo-blocked (HK/Shanghai) | Used empty CSV placeholders |
| Alpaca SIP subscription error | Added `feed="iex"` to get_bars() |
| Timezone mismatch in date merge | Stripped UTC with `dt.tz_localize(None)` |
| 02_Yahoo_Extras.csv missing | Created empty placeholder |

## Output Files
```
outputs/01_SP500_Tickers_list.csv
outputs/02_Yahoo_Stocks.csv               (5.4MB — Alpaca IEX)
outputs/03_fred_features.csv
outputs/04_Crypto_OHLCV.csv               (393KB)
outputs/04_markowitz_labels.csv           (2.9MB)
outputs/05_label_macro_features_OEP.csv   (13MB)
outputs/06_final_features.csv             (93MB)
outputs/08_predicted_portfolio_weights.csv
outputs/08_rebalance_instructions.csv
models/portfolio_weights_model.pth        (15MB)
models/scaler_X.pkl
models/trained_tickers.csv
```
