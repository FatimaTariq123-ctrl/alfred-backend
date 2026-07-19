# Top-10 Monthly Picks Agent — Testing Guide

## What This Agent Does
Scans 500 S&P 500 stocks monthly, analyzes price patterns and macroeconomic data, and recommends the top 10 stocks to buy that month.

## Pipeline Flow
```
w01 (Tickers) → w02 (Stock Prices) → w03 (FRED Macro) → 04 (Labels) → 05 (Merge) → 06 (Features) → 07 (Train)
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
```

## How to Run
```bash
# Data loaders
python Data_loaders/w01_SP500_Tickers_and_Membership.py
python Data_loaders/w02_Yahoo.py        # Replace with Alpaca if Yahoo geo-blocked
python Data_loaders/w03_Fred.py

# Pipeline
python Pipeline/04_Labels.py
python Pipeline/05_merge_price_macro.py
python Pipeline/06_Feature_Engg.py
python Pipeline/07_train_model.py
```

Or run the test script:
```bash
python test_pipeline.py
```

## Test Results

### Data Loaders
| Script | Status | Output |
|--------|--------|--------|
| w01 — S&P500 Tickers | ✅ PASS | 503 tickers fetched, 501 verified via Alpaca |
| w02 — Stock Data (Alpaca IEX) | ✅ PASS | 73,731 rows fetched |
| w03 — FRED Macro | ✅ PASS | 3,029 rows, 2015→2026 |

### Pipeline
| Script | Status | Output |
|--------|--------|--------|
| 04 — Labels | ✅ PASS | 71,321 rows labeled |
| 05 — Merge Price + Macro | ✅ PASS | 71,321 rows × 18 cols |
| 06 — Feature Engineering | ✅ PASS | 71,321 rows × 81 features, PCA 16 components |
| 07 — Train Model | ✅ PASS | 5 epochs, NDCG@10: 0.5790 (epoch 1) |

### Model Performance
```
Epoch 1/5 — Train Loss: 18564.90 | Val Loss: 17966.23 | NDCG@10: 0.5790
Epoch 2/5 — Train Loss: 18562.61 | Val Loss: 17967.02 | NDCG@10: 0.5631
Epoch 5/5 — Train Loss: 18555.48 | Val Loss: 17970.29 | NDCG@10: 0.5423
```

### Issues Encountered & Resolved
| Issue | Fix |
|-------|-----|
| Python 3.14 package incompatibility | Downgraded to Python 3.12 |
| Yahoo Finance geo-blocked (Pakistan) | Switched to Alpaca IEX feed |
| Timezone mismatch in date merge | Stripped UTC with `dt.tz_localize(None)` |
| 100 epoch training too slow on CPU | Capped at 5 epochs for local testing |

## Output Files
```
outputs/01_SP500_Tickers_list.csv
outputs/01_SP500_membership_matrix.csv
outputs/02_Yahoo_Stocks.csv          (5.4MB)
outputs/02_top50_universe.csv
outputs/03_fred_features.csv
outputs/04_labeled_panel.csv         (6.5MB)
outputs/05_label_macro_features.csv  (8.4MB)
outputs/06_final_features.csv        (90MB)
models/top10_model.pth               (4.4MB)
models/feature_scaler.joblib
```
