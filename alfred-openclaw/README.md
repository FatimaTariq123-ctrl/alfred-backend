# Alfred

Alfred is the parent repository containing the following sub-projects:

- **Alfred-openclaw** — core backend infrastructure shared across agents
- **Clax-agents** — collection of trading and analysis agents
- **Clax-ml** — machine learning based agents

## Repository Structure

```
Alfred/
├── Alfred-openclaw/
│   ├── app/
│   ├── scripts/
│   └── workspace/
│   └── main.py
│   └── openclaw.json
│
├── Clax-agents/
│   ├── fact-guard-agent/
│   ├── guardrail-guard-agent/
│   ├── investor-dna/
│   ├── macro-context-agent/
│   ├── order-router-agent/
│   └── quant-bridge-agent/
│
└── Clax-ml/
    ├── Optimal-entry-agent/
    ├── Portfolio-Rebalancing-agent/
    └── Top-10-monthly-picks/
```

## Module Overview

### Alfred-openclaw
Core backend infrastructure shared across all agents. Includes the workspace configuration, `openclaw.json` for project settings, and `backend_services` providing centralized services used by Clax-agents and Clax-ml.

### Clax-agents
| Module | Description |
|---|---|
| `fact-guard-agent` | Verifies factual claims and data integrity before they are used downstream. |
| `guardrail-guard-agent` | Enforces safety and compliance guardrails across agent actions. |
| `investor-dna` | Builds an investor profile to tailor recommendations to individual risk and goals. |
| `macro-context-agent` | Supplies macroeconomic context and trends to inform trading decisions. |
| `order-router-agent` | Routes and executes trade orders to the appropriate venue. |
| `quant-bridge-agent` | Bridges quantitative models with the agent pipeline for signal generation. |

### Clax-ml
| Module | Description |
|---|---|
| `Optimal-entry-agent` | Identifies optimal entry points for trades using ML-driven signals. |
| `Portfolio-Rebalancing-agent` | Automates portfolio rebalancing based on target allocations and market conditions. |
| `Top-10-monthly-picks` | Generates a ranked list of the top 10 investment picks each month. |
