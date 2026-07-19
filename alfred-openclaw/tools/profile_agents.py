#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import time
import statistics
import psutil
from datetime import datetime

# Define paths
WORKSPACE_DIR = "/home/ummara/Alfred/alfred-openclaw"
CONFIG_PATH = os.path.join(WORKSPACE_DIR, "openclaw.json")
CLI_PATH = "/home/ummara/.npm-global/bin/openclaw"

def get_all_agent_scripts():
    """
    Loads all configured agent script paths from openclaw.json.
    Returns a dict of {agent_name: absolute_script_path}
    """
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"OpenClaw config not found at: {CONFIG_PATH}")
    
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    servers = config.get("mcp", {}).get("servers", {})
    agent_map = {}
    for name, srv in servers.items():
        args = srv.get("args", [])
        if args:
            agent_map[name] = os.path.abspath(os.path.expanduser(args[0]))
    return agent_map

def find_gateway_process():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = proc.info['name']
            cmdline = proc.info['cmdline']
            if name and 'openclaw-gateway' in name:
                return proc
            if cmdline and any('openclaw-gateway' in arg for arg in cmdline):
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

def find_active_agents(agent_script_map):
    active = {}
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline:
                for name, path in agent_script_map.items():
                    if any(path in arg for arg in cmdline):
                        active[name] = proc
                        break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return active

def cleanup_all_lingering_agents(agent_script_map):
    active = find_active_agents(agent_script_map)
    for name, proc in active.items():
        try:
            print(f"🧹 Killing lingering agent '{name}' (PID {proc.pid})")
            proc.kill()
        except Exception:
            pass

def restart_gateway(agent_script_map):
    print("\n🔄 Restarting openclaw-gateway service for a clean cold start...")
    start_time = time.time()
    subprocess.run(["systemctl", "--user", "restart", "openclaw-gateway.service"], check=True)
    
    time.sleep(3.0)
    gateway_proc = None
    for _ in range(10):
        gateway_proc = find_gateway_process()
        if gateway_proc:
            break
        time.sleep(1.0)
    
    if not gateway_proc:
        raise RuntimeError("Failed to locate openclaw-gateway process after restart")
        
    startup_time = time.time() - start_time
    print(f"✅ Found new gateway process with PID: {gateway_proc.pid} (Startup: {startup_time:.2f}s)")
    
    cleanup_all_lingering_agents(agent_script_map)
    return gateway_proc, startup_time

def get_system_snapshot():
    python_count = 0
    for p in psutil.process_iter(['name']):
        try:
            if 'python' in (p.info['name'] or '').lower():
                python_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
            
    vm = psutil.virtual_memory()
    return {
        "timestamp": datetime.now().isoformat(),
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_mb": vm.used / (1024 * 1024),
        "ram_pct": vm.percent,
        "running_processes": len(psutil.pids()),
        "python_processes": python_count,
        "disk_pct": psutil.disk_usage('/').percent
    }

def get_process_connections(proc):
    try:
        conns = proc.net_connections(kind='all')
        db_conns = 0
        http_conns = 0
        for c in conns:
            if c.raddr:
                port = c.raddr.port
                if port == 5432:
                    db_conns += 1
                elif port in [80, 443, 8080, 18789]:
                    http_conns += 1
        return len(conns), db_conns, http_conns
    except Exception:
        return 0, 0, 0

def format_markdown_report(args, results):
    """
    Generates the final multi-section Markdown report.
    """
    sys_before = results["system_snapshot_before"]
    sys_after = results["system_snapshot_after"]
    gw_stats = results["gateway_profile"]
    workflow = results["workflow_summary"]
    agents = results["per_agent_metrics"]
    bt = chr(96)
    
    md = f"""# Profiling Summary Report
**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Mode:** {results['mode'].capitalize()}  
"""
    if results['mode'] == 'single':
        md += f"**Agent:** {args.agent}  \n**Query:** \"{args.message}\"  \n**Iterations:** {args.iterations}\n"
    else:
        md += f"**Prompts:** {len(workflow['step_details'])} steps executed\n"
        
    md += f"""
---

## 1. System Summary
| System Metric | Before Benchmark | After Benchmark | Delta |
| :--- | :---: | :---: | :---: |
| **Total CPU Usage (%)** | {sys_before['cpu_pct']:.1f}% | {sys_after['cpu_pct']:.1f}% | {sys_after['cpu_pct'] - sys_before['cpu_pct']:.1f}% |
| **Total System RAM (MB)** | {sys_before['ram_used_mb']:.1f} | {sys_after['ram_used_mb']:.1f} | {sys_after['ram_used_mb'] - sys_before['ram_used_mb']:.1f} MB |
| **Total Running Processes** | {sys_before['running_processes']} | {sys_after['running_processes']} | {sys_after['running_processes'] - sys_before['running_processes']} |
| **Active Python Processes** | {sys_before['python_processes']} | {sys_after['python_processes']} | {sys_after['python_processes'] - sys_before['python_processes']} |
| **Disk Space Util (%)** | {sys_before['disk_pct']:.1f}% | {sys_after['disk_pct']:.1f}% | {sys_after['disk_pct'] - sys_before['disk_pct']:.1f}% |
| **Total Network I/O (KB)** | - | - | Sent: {workflow['total_net_sent_bytes']/1024:.1f} / Recv: {workflow['total_net_recv_bytes']/1024:.1f} |

---

## 2. Gateway Profile
| Metric | Value |
| :--- | :--- |
| **Idle RAM (MB)** | {gw_stats['idle_ram_mb']:.1f} |
| **Peak RAM (MB)** | {gw_stats['peak_ram_mb']:.1f} |
| **Avg CPU (%)** | {gw_stats['avg_cpu_pct']:.1f}% |
| **Peak CPU (%)** | {gw_stats['peak_cpu_pct']:.1f}% |
| **Startup Time (s)** | {gw_stats['startup_time_sec']:.2f} |

---

## 3. Agent Profiles
| Agent | Startup RAM (MB) | Peak RAM (MB) | Avg CPU (%) | Peak CPU (%) | Response Time (s) | Persistent |
| :--- | ---: | ---: | ---: | ---: | ---: | :---: |
"""
    for name, s in agents.items():
        md += f"| {bt}{name}{bt} | {s['startup_ram_mb']:.1f} | {s['peak_ram_mb']:.1f} | {s['avg_cpu_pct']:.1f} | {s['peak_cpu_pct']:.1f} | {s['response_time_sec']:.2f} | {'Yes' if s['persistent'] else 'No'} |\n"

    md += f"""
---

## 4. Workflow Summary
| Metric | Value |
| :--- | :--- |
| **Workflow Latency (s)** | {workflow['total_response_time_sec']:.2f} |
| **Number of Agents Launched** | {workflow['agents_launched_count']} |
| **Total Disk Read (KB)** | {workflow['total_disk_read_bytes']/1024:.1f} |
| **Total Disk Write (KB)** | {workflow['total_disk_write_bytes']/1024:.1f} |
| **API Requests** | Not Available |
| **API Latency** | Not Available |
| **DB Queries** | Not Available |
| **DB Time** | Not Available |
"""
    if results['mode'] == 'workflow':
        md += f"\n### Step-by-Step Log\n| Step | Trigger Prompt | Turn Duration (s) |\n| :---: | :--- | :---: |\n"
        for s in workflow['step_details']:
            md += f"| {s['step']} | \"{s['prompt']}\" | {s['duration_sec']:.3f} |\n"

    return md

def run_profiler(args, agent_script_map, prompts):
    """
    Core profiler engine handling both Single and Workflow modes seamlessly.
    """
    print("\n" + "="*60)
    print(f"🌊 Starting Profiler ({args.mode.upper()} MODE) with {len(prompts)} steps")
    for idx, pr in enumerate(prompts, 1):
        print(f"  Step {idx}: \"{pr}\"")
    print("="*60 + "\n")
    
    # 1. Baseline System
    global_sys_before = get_system_snapshot()
    net_start = psutil.net_io_counters()
    
    # 2. Restart Gateway and track its profile
    gateway_proc, gw_startup_time = restart_gateway(agent_script_map)
    time.sleep(1.0)
    
    gw_idle_ram = 0.0
    try:
        gw_idle_ram = gateway_proc.memory_info().rss / (1024 * 1024)
        gateway_proc.cpu_percent(interval=None) # calibrate
    except Exception:
        pass

    gw_cpu_samples = []
    gw_ram_samples = []

    workflow_start_time = time.time()
    
    agent_metric_history = {} 
    distinct_agents_launched = set()
    step_details = []
    
    # Loop over prompts (in single mode, prompts = iterations of the same message)
    for step_num, prompt in enumerate(prompts, 1):
        print(f"\n🌊 [Step {step_num}/{len(prompts)}] Executing: \"{prompt}\"")
        step_start = time.time()
        
        # Trigger
        cli_args = [CLI_PATH, "agent", "--agent", "main", "--message", prompt]
        cli_proc = subprocess.Popen(
            cli_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        while cli_proc.poll() is None:
            # Poll Gateway
            try:
                gw_cpu = gateway_proc.cpu_percent(interval=None)
                gw_ram = gateway_proc.memory_info().rss / (1024 * 1024)
                gw_cpu_samples.append(gw_cpu)
                gw_ram_samples.append(gw_ram)
            except Exception:
                pass
                
            # Scan active agents
            active_agents = find_active_agents(agent_script_map)
            for name, proc in active_agents.items():
                distinct_agents_launched.add(name)
                
                # Initialize agent tracking
                if name not in agent_metric_history:
                    try:
                        io = proc.io_counters()
                        dr_start = io.read_bytes
                        dw_start = io.write_bytes
                    except Exception:
                        dr_start = dw_start = 0
                        
                    agent_metric_history[name] = {
                        "cpu": [],
                        "ram": [],
                        "first_seen_time": time.time(),
                        "last_seen_time": time.time(),
                        "startup_ram_mb": None,
                        "total_conns": [],
                        "db_conns": [],
                        "http_conns": [],
                        "disk_read_start": dr_start,
                        "disk_read_delta": 0,
                        "disk_write_start": dw_start,
                        "disk_write_delta": 0,
                        "persistent": False
                    }
                    try:
                        agent_metric_history[name]["startup_ram_mb"] = proc.memory_info().rss / (1024 * 1024)
                        proc.cpu_percent(interval=None) # calibrate
                    except Exception:
                        pass
                    
                # Poll metrics
                try:
                    cpu_val = proc.cpu_percent(interval=None)
                    ram_val = proc.memory_info().rss / (1024 * 1024)
                    tot, db, http = get_process_connections(proc)
                    
                    hist = agent_metric_history[name]
                    hist["cpu"].append(cpu_val)
                    hist["ram"].append(ram_val)
                    hist["total_conns"].append(tot)
                    hist["db_conns"].append(db)
                    hist["http_conns"].append(http)
                    hist["last_seen_time"] = time.time()
                    
                    io = proc.io_counters()
                    hist["disk_read_delta"] = max(hist["disk_read_delta"], io.read_bytes - hist["disk_read_start"])
                    hist["disk_write_delta"] = max(hist["disk_write_delta"], io.write_bytes - hist["disk_write_start"])
                except Exception:
                    pass
            
            time.sleep(0.05)
            
        cli_proc.wait()
        step_duration = time.time() - step_start
        print(f"✅ Step {step_num} finished in {step_duration:.3f}s")
        step_details.append({
            "step": step_num,
            "prompt": prompt,
            "duration_sec": step_duration
        })
        time.sleep(1.0) # settle time between runs
        
    workflow_duration = time.time() - workflow_start_time
    global_sys_after = get_system_snapshot()
    
    net_end = psutil.net_io_counters()
    total_net_sent = net_end.bytes_sent - net_start.bytes_sent
    total_net_recv = net_end.bytes_recv - net_start.bytes_recv
    
    # Check persistence
    time.sleep(1.0)
    currently_active = find_active_agents(agent_script_map)
    for name in agent_metric_history.keys():
        agent_metric_history[name]["persistent"] = name in currently_active
        
    # Aggregate Agent stats
    agent_summary = {}
    for name, hist in agent_metric_history.items():
        cpu_l = hist["cpu"]
        ram_l = hist["ram"]
        
        agent_summary[name] = {
            "startup_ram_mb": hist["startup_ram_mb"] or 0.0,
            "peak_ram_mb": max(ram_l) if ram_l else 0.0,
            "avg_cpu_pct": sum(cpu_l)/len(cpu_l) if cpu_l else 0.0,
            "peak_cpu_pct": max(cpu_l) if cpu_l else 0.0,
            "response_time_sec": hist["last_seen_time"] - hist["first_seen_time"],
            "disk_read_bytes": hist["disk_read_delta"],
            "disk_write_bytes": hist["disk_write_delta"],
            "persistent": hist["persistent"]
        }
        
    total_disk_read = sum(h["disk_read_delta"] for h in agent_metric_history.values())
    total_disk_write = sum(h["disk_write_delta"] for h in agent_metric_history.values())
    
    # Compile Results JSON
    results = {
        "mode": args.mode,
        "timestamp": datetime.now().isoformat(),
        "system_snapshot_before": global_sys_before,
        "system_snapshot_after": global_sys_after,
        "gateway_profile": {
            "idle_ram_mb": gw_idle_ram,
            "peak_ram_mb": max(gw_ram_samples) if gw_ram_samples else gw_idle_ram,
            "avg_cpu_pct": sum(gw_cpu_samples)/len(gw_cpu_samples) if gw_cpu_samples else 0.0,
            "peak_cpu_pct": max(gw_cpu_samples) if gw_cpu_samples else 0.0,
            "startup_time_sec": gw_startup_time
        },
        "per_agent_metrics": agent_summary,
        "workflow_summary": {
            "total_response_time_sec": workflow_duration,
            "agents_launched_count": len(distinct_agents_launched),
            "total_disk_read_bytes": total_disk_read,
            "total_disk_write_bytes": total_disk_write,
            "total_net_sent_bytes": total_net_sent,
            "total_net_recv_bytes": total_net_recv,
            "step_details": step_details,
            "external_api_requests": "Not Available",
            "external_api_latency": "Not Available",
            "db_queries": "Not Available",
            "db_time": "Not Available"
        }
    }
    
    # Generate Output Files
    prefix = f"profile_{args.mode}_{args.agent if args.mode == 'single' else 'summary'}"
    
    # JSON
    json_path = os.path.join(args.output_dir, f"{prefix}.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Saved JSON report to: {json_path}")
    
    # CSV
    csv_path = os.path.join(args.output_dir, f"{prefix}_agents.csv")
    with open(csv_path, "w") as f:
        f.write("Agent,Startup_RAM_MB,Peak_RAM_MB,Avg_CPU_Pct,Peak_CPU_Pct,Response_Time_Sec,Persistent\n")
        for name, summ in agent_summary.items():
            f.write(f"{name},{summ['startup_ram_mb']:.2f},{summ['peak_ram_mb']:.2f},{summ['avg_cpu_pct']:.2f},{summ['peak_cpu_pct']:.2f},{summ['response_time_sec']:.2f},{summ['persistent']}\n")
    print(f"💾 Saved CSV Agent Breakdown to: {csv_path}")
    
    # Markdown
    md_content = format_markdown_report(args, results)
    md_path = os.path.join(args.output_dir, f"{prefix}.md")
    with open(md_path, "w") as f:
        f.write(md_content)
    print(f"💾 Saved Markdown summary report to: {md_path}")
    
    print("\n" + "="*30 + " FINAL REPORT " + "="*30)
    print(md_content)
    print("="*74)

def main():
    parser = argparse.ArgumentParser(description="OpenClaw Profiler for VM Capacity Planning")
    parser.add_argument("--mode", choices=["single", "workflow"], default="single", help="Profiling mode: single agent or sequential workflow")
    
    # Single mode args
    parser.add_argument("--agent", help="Name of the agent to profile (required in single mode)")
    parser.add_argument("--message", help="Test query/prompt to trigger agent execution (required in single mode)")
    parser.add_argument("--iterations", type=int, default=5, help="Number of iterations to run in single mode (default: 5)")
    
    # Workflow mode args
    parser.add_argument("--prompts", nargs="+", help="Sequence of prompts to execute in workflow mode")
    parser.add_argument("--workflow-json", help="Path to JSON file containing array of workflow prompts")
    
    parser.add_argument("--output-dir", default=".", help="Directory to save output reports")
    args = parser.parse_args()
    
    try:
        agent_script_map = get_all_agent_scripts()
    except Exception as e:
        print(f"❌ Error loading agent script configurations: {e}")
        sys.exit(1)
        
    os.makedirs(args.output_dir, exist_ok=True)
    
    prompts = []
    if args.mode == "single":
        if not args.agent or not args.message:
            parser.error("--agent and --message are required when --mode is 'single'")
        prompts = [args.message] * args.iterations
    elif args.mode == "workflow":
        if args.workflow_json:
            if not os.path.exists(args.workflow_json):
                raise FileNotFoundError(f"Workflow JSON not found: {args.workflow_json}")
            with open(args.workflow_json, "r") as f:
                data = json.load(f)
                prompts = data if isinstance(data, list) else data.get("prompts", [])
        elif args.prompts:
            prompts = args.prompts
        else:
            prompts = [
                "Analyze my investor profile",
                "What is the current macroeconomic outlook?",
                "Can you cross-reference my profile with the macro analysis?"
            ]
            
    run_profiler(args, agent_script_map, prompts)

if __name__ == "__main__":
    main()
