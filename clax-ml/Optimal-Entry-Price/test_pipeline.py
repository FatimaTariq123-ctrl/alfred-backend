"""
Optimal Entry Price Agent — Pipeline Test Script
=================================================
Runs the full data loader + pipeline sequence and verifies outputs exist.
"""

import os
import subprocess
import sys


def run_script(script_path):
    print(f"\n{'='*50}")
    print(f"Running: {script_path}")
    print('='*50)
    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=False
    )
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
    print("\n🚀 Starting Optimal Entry Price Agent Pipeline Test")
    print("="*60)

    # === Data Loaders ===
    print("\n📥 PHASE 1: Data Loaders")
    scripts = [
        "Data_loaders/w01_SP500_Tickers_and_Membership.py",
        "Data_loaders_alt/w02_Alpaca.py",
        "Data_loaders_alt/w02b_Extras.py",
        "Data_loaders/w03_Fred.py",
    ]
    for script in scripts:
        if not run_script(script):
            print(f"\n❌ Pipeline aborted at {script}")
            return

    # === Pipeline ===
    print("\n⚙️  PHASE 2: Pipeline")
    pipeline_scripts = [
        "Pipeline/w04_Labels.py",
        "Pipeline/w05_merge_price_macro.py",
        "Pipeline/w06_Feature_Engg.py",
        "Pipeline/w07_model.py",
        "Pipeline/w08_train_model.py",
    ]
    for script in pipeline_scripts:
        if not run_script(script):
            print(f"\n❌ Pipeline aborted at {script}")
            return

    # === Output Verification ===
    print("\n📁 PHASE 3: Output Verification")
    outputs = [
        ("outputs/01_SP500_Tickers_list.csv", "S&P500 Tickers"),
        ("outputs/02_Yahoo_Stocks.csv", "Alpaca Stock Data"),
        ("outputs/02_Extras.csv", "Extras (FRED + Gold)"),
        ("outputs/03_fred_features.csv", "FRED Macro Data"),
        ("outputs/04_labeled_panel_OEP.csv", "OEP Labels"),
        ("outputs/05_label_macro_features_OEP.csv", "Merged Features"),
        ("outputs/06_final_features.csv", "Final Features"),
        ("models/oep_regressor.pth", "Trained Model"),
        ("models/scaler_X.pkl", "Feature Scaler"),
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
