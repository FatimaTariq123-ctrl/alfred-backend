"""
Top-10 Monthly Picks Agent — Pipeline Test Script
==================================================
Runs the full data loader + pipeline sequence and verifies outputs exist.
"""

import os
import subprocess
import sys


def run_script(script_path):
    print(f"\n{'='*50}")
    print(f"Running: {script_path}")
    print('='*50)
    result = subprocess.run([sys.executable, script_path], capture_output=False)
    if result.returncode != 0:
        print(f"❌ FAILED: {script_path}")
        return False
    print(f"✅ PASSED: {script_path}")
    return True


def check_output(filepath, description):
    exists = os.path.exists(filepath)
    size = os.path.getsize(filepath) if exists else 0
    status = "✅" if exists and size > 0 else "❌"
    print(f"{status} {description}: {filepath} ({size:,} bytes)")
    return exists and size > 0


def run_pipeline_test():
    print("\n🚀 Starting Top-10 Monthly Picks Agent Pipeline Test")
    print("="*60)

    # === Data Loaders ===
    print("\n📥 PHASE 1: Data Loaders")
    scripts = [
        "Data_loaders/w01_SP500_Tickers_and_Membership.py",
        "Data_loaders/w02_Yahoo.py",   # Note: use Alpaca replacement if Yahoo geo-blocked
        "Data_loaders/w03_Fred.py",
    ]
    for script in scripts:
        if not run_script(script):
            print(f"\n❌ Pipeline aborted at {script}")
            return

    # === Pipeline ===
    print("\n⚙️  PHASE 2: Pipeline")
    pipeline_scripts = [
        "Pipeline/04_Labels.py",
        "Pipeline/05_merge_price_macro.py",
        "Pipeline/06_Feature_Engg.py",
        "Pipeline/07_train_model.py",
    ]
    for script in pipeline_scripts:
        if not run_script(script):
            print(f"\n❌ Pipeline aborted at {script}")
            return

    # === Output Verification ===
    print("\n📁 PHASE 3: Output Verification")
    outputs = [
        ("outputs/01_SP500_Tickers_list.csv", "S&P500 Tickers"),
        ("outputs/01_SP500_membership_matrix.csv", "Membership Matrix"),
        ("outputs/02_Yahoo_Stocks.csv", "Stock Price Data"),
        ("outputs/02_top50_universe.csv", "Top 50 Universe"),
        ("outputs/03_fred_features.csv", "FRED Macro Data"),
        ("outputs/04_labeled_panel.csv", "Labels"),
        ("outputs/05_label_macro_features.csv", "Merged Features"),
        ("outputs/06_final_features.csv", "Final Features"),
        ("models/top10_model.pth", "Trained Model"),
        ("models/feature_scaler.joblib", "Feature Scaler"),
    ]

    all_passed = all(check_output(path, desc) for path, desc in outputs)

    print("\n" + "="*60)
    if all_passed:
        print("✅ ALL TESTS PASSED — Pipeline complete!")
    else:
        print("❌ SOME OUTPUTS MISSING — Check errors above.")
    print("="*60)


if __name__ == "__main__":
    run_pipeline_test()
