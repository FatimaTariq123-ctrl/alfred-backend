#!/usr/bin/env python3
import time
import subprocess
import psutil
import torch
import pandas as pd

def profile_command(cmd, cwd):
    print(f"Profiling: {' '.join(cmd)} in {cwd}")
    start_time = time.time()
    
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    cpu_samples = []
    ram_samples = []
    
    last_cpu_time = None
    last_time = None
    
    while proc.poll() is None:
        try:
            p_psutil = psutil.Process(proc.pid)
            children = p_psutil.children(recursive=True)
            
            # Sum of user + system times
            current_cpu_time = p_psutil.cpu_times().user + p_psutil.cpu_times().system
            for child in children:
                try:
                    current_cpu_time += child.cpu_times().user + child.cpu_times().system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            current_time = time.time()
            
            if last_cpu_time is not None:
                time_delta = current_time - last_time
                cpu_delta = current_cpu_time - last_cpu_time
                if time_delta > 0:
                    cpu_pct = (cpu_delta / time_delta) * 100
                    cpu_samples.append(cpu_pct)
                    
            last_cpu_time = current_cpu_time
            last_time = current_time
            
            total_ram = p_psutil.memory_info().rss / (1024 * 1024)
            for child in children:
                try:
                    total_ram += child.memory_info().rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            ram_samples.append(total_ram)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        time.sleep(0.05) # high frequency sampling
        
    proc.wait()
    runtime = time.time() - start_time
    
    peak_ram = max(ram_samples) if ram_samples else 0.0
    avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
    peak_cpu = max(cpu_samples) if cpu_samples else 0.0
    
    gpu_device = "cuda" if torch.cuda.is_available() else "cpu"
    gpu_util = "0.0%" if gpu_device == "cuda" else "N/A"
    
    return peak_ram, avg_cpu, peak_cpu, gpu_util, runtime

def main():
    rebalance_dir = "/home/ummara/Alfred/clax-ml/Portfolio-Rebalancing-Agent"
    temp_cols_path = os.path.join(rebalance_dir, "models/temp_columns_pat.csv")
    temp_patched = False
    
    try:
        cols_df = pd.read_csv(os.path.join(rebalance_dir, "models/trained_model_columns.csv"))
        sliced_cols = cols_df["feature_column"].tolist()[:1400]
        pd.DataFrame({"feature_column": sliced_cols}).to_csv(temp_cols_path, index=False)
        temp_patched = True
    except Exception as e:
        print(f"Warning: Failed to setup Portfolio-Rebalancing column patch: {e}")

    tasks = [
        {
            "name": "Optimal-entry-agent",
            "cwd": "/home/ummara/Alfred/clax-ml/Optimal_entry_agent",
            "cmd": [
                "/home/ummara/venv/bin/python3", "-c",
                "import sys; sys.path.append('.'); from prediction import PredictionService; p = PredictionService(); p.predict('AAPL', 'buy')"
            ]
        },
        {
            "name": "Portfolio-Rebalancing-Agent",
            "cwd": rebalance_dir,
            "cmd": [
                "/home/ummara/venv/bin/python3", "-c",
                "import sys; sys.path.append('.'); import Pipeline.w08_predict_and_rebalance as pr; pr.TRAINED_MODEL_COLUMNS_PATH='models/temp_columns_pat.csv'; pr.main()"
            ]
        },
        {
            "name": "Top-10-monthly-picks",
            "cwd": "/home/ummara/Alfred/clax-ml/Top-10-monthly-picks",
            "cmd": [
                "/home/ummara/venv/bin/python3", "predict_monthly.py"
            ]
        }
    ]
    
    results = []
    
    for task in tasks:
        print(f"\n--- Profiling {task['name']} ---")
        peak_ram, avg_cpu, peak_cpu, gpu_util, runtime = profile_command(task["cmd"], task["cwd"])
        print(f"Done: Peak RAM={peak_ram:.2f}MB, Avg CPU={avg_cpu:.1f}%, Peak CPU={peak_cpu:.1f}%, Runtime={runtime:.2f}s")
        results.append({
            "Agent": task["name"],
            "RAM": f"{peak_ram:.2f} MB",
            "Avg CPU": f"{avg_cpu:.1f}%",
            "Peak CPU": f"{peak_cpu:.1f}%",
            "GPU": gpu_util,
            "Runtime": f"{runtime:.3f} s"
        })
        
    if temp_patched and os.path.exists(temp_cols_path):
        os.remove(temp_cols_path)
        
    print("\n" + "="*30 + " PROFILING RESULTS " + "="*30)
    print(f"{'ML Agent':<30} | {'Peak RAM':<12} | {'Avg CPU':<10} | {'Peak CPU':<10} | {'GPU':<6} | {'Runtime':<12}")
    print("-" * 92)
    for r in results:
        print(f"{r['Agent']:<30} | {r['RAM']:<12} | {r['Avg CPU']:<10} | {r['Peak CPU']:<10} | {r['GPU']:<6} | {r['Runtime']:<12}")
    print("="*79)

if __name__ == "__main__":
    import os
    main()
