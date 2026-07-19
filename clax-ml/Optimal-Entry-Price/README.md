# Optimal Entry Price Agent — Testing Guide

## What This Agent Does
Takes stock picks and predicts the optimal price point and timing to buy or sell — finding the best entry moment for maximum return using OEP (Optimal Entry Point) labeling.

## Pipeline Flow
```
w01 (Tickers) → w02 (Alpaca) → w02b (Extras) → w03 (FRED) → w04 (Labels) → w05 (Merge) → w06 (Features) → w07 (Model) → w08 (Train)
```

## Prerequisites
- Python 3.12
- Virtual environment activated
- `.env` file with:
```
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
FRED_API_KEY=your_fred_key
```

## Environment Setup
```bash
"/c/Users/<you>/AppData/Local/Programs/Python/Python312/python.exe" -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
pip install pandas==2.2.2        # Required for pandas-datareader compatibility
```

## How to Run
```bash
# Data loaders
python Data_loaders/w01_SP500_Tickers_and_Membership.py
python Data_loaders_alt/w02_Alpaca.py       # Alpaca IEX — Yahoo geo-blocked
python Data_loaders_alt/w02b_Extras.py
python Data_loaders/w03_Fred.py

# Pipeline
python Pipeline/w04_Labels.py
python Pipeline/w05_merge_price_macro.py
python Pipeline/w06_Feature_Engg.py
python Pipeline/w07_model.py
python Pipeline/w08_train_model.py
```

Or run the test script:
```bash
python test_pipeline.py
```

## Test Results

### Data Loaders
| Script | Status | Output |
|--------|--------|--------|
| w01 — S&P500 Tickers | ✅ PASS | 501 tickers verified via Alpaca |
| w02 — Alpaca Stock Data (IEX) | ✅ PASS | 72,848 rows fetched |
| w02b — Extras (FRED + Gold) | ✅ PASS | 19 series, 53,431 rows |
| w03 — FRED Macro | ✅ PASS | 3,029 rows, 2015→2026 |

### Pipeline
| Script | Status | Output |
|--------|--------|--------|
| w04 — OEP Labels | ✅ PASS | 145,696 rows, 491 tickers |
| w05 — Merge Price + Macro | ✅ PASS | 145,696 rows × 22 cols |
| w06 — Feature Engineering | ✅ PASS | 145,696 rows × 151 features |
| w07 — Model Training | ✅ PASS | 10 epochs, SELL success rate: 63% |
| w08 — Model Training v2 | ✅ PASS | 10 epochs, SELL success rate: 60% |

### Model Performance
```
w07:
  Epoch 1/10  — Train RMSE: 0.1886 | Val RMSE: 0.1575
  Epoch 9/10  — Val RMSE: 0.1349 (best)
  BUY  — Hit Ratio: 0.4405 | Price Deviation: 0.0330
  SELL — Hit Ratio: 0.6311 | Price Deviation: 0.0202

w08:
  Epoch 10/10 — Val RMSE: 0.5469 (best)
  SELL — Hit Ratio: 0.6091 | Price Deviation: 0.0204
```

### Issues Encountered & Resolved
| Issue | Fix |
|-------|-----|
| Yahoo Finance geo-blocked (Pakistan) | Switched to Alpaca IEX feed |
| Alpaca SIP subscription error | Added `feed="iex"` to all `get_bars()` calls |
| pandas-datareader incompatibility | Downgraded pandas to 2.2.2 |
| Timezone mismatch in date merge | Stripped UTC with `dt.tz_localize(None)` |

## Output Files
```
outputs/01_SP500_Tickers_list.csv
outputs/02_Yahoo_Stocks.csv              (4.4MB — Alpaca IEX)
outputs/02_Extras.csv                    (3.5MB)
outputs/03_fred_features.csv
outputs/04_labeled_panel_OEP.csv         (8.3MB)
outputs/05_label_macro_features_OEP.csv  (9.7MB)
outputs/06_final_features.csv            (151MB)
models/oep_regressor.pth                 (5MB)
models/scaler_X.pkl
models/scaler_y.pkl
```
