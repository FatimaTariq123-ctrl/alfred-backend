# Alfred

Alfred is the parent repository containing the following sub-projects:

- **alfred-openclaw** — core backend infrastructure shared across agents
- **clax-agents** — collection of trading and analysis agents
- **clax-ml** — machine learning based agents

## Repository Structure

```
Alfred/
├── alfred-openclaw/
│   ├── app/
│   ├── scripts/
│   ├── workspace/
│   ├── main.py
│   └── openclaw.json
│
├── clax-agents/
│   ├── Fact-Guard-Agent/
│   ├── guardrail_guard_agent/
│   ├── Investor-DNA-Agent/
│   ├── Macro-Context-Agent/
│   ├── order-router-agent/
│   └── quant-bridge-agent/
│
└── clax-ml/
    ├── Optimal-Entry-Price/
    ├── Portfolio-Rebalancing/
    └── Top-10-monthly-picks/
```

## Prerequisites

- Python 3.12+
- PostgreSQL (or Neon database)
- Redis
- Node.js (for `pg` driver in database_service)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/ummara-clax/ALFRED.git
cd ALFRED
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set the required values:

| Variable | Required | Description |
|----------|----------|-------------|
| `JWT_SECRET` | Yes | Random string for signing JWT tokens |
| `OPENCLAW_GATEWAY_TOKEN` | Yes | Must match the value in `openclaw.json` |
| `NEON_DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql+psycopg2://...`) |
| `DATABASE_URL` | Yes | PostgreSQL connection string for Redis-Gateway |
| `AWS_ACCESS_KEY_ID` | Yes | AWS credentials for S3 cloud storage |
| `AWS_SECRET_ACCESS_KEY` | Yes | AWS credentials for S3 cloud storage |

Optional variables have sensible defaults in `.env.example`.

### 5. Run database migrations (optional)

```bash
export NEON_DATABASE_URL="your_connection_string"
cd alfred-openclaw
python scripts/run_migration.py
python scripts/run_sanctions_migration.py
```

### 6. Start the application

From the `alfred-openclaw/` directory:

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

## Module Overview

### alfred-openclaw
Core backend infrastructure shared across all agents. Includes the FastAPI gateway, workspace configuration, `openclaw.json` for project settings, and `backend_services` providing centralized services used by clax-agents and clax-ml.

### clax-agents
| Module | Description |
|---|---|
| `Fact-Guard-Agent` | Verifies factual claims and data integrity before they are used downstream. |
| `guardrail_guard_agent` | Enforces safety and compliance guardrails across agent actions. |
| `Investor-DNA-Agent` | Builds an investor profile to tailor recommendations to individual risk and goals. |
| `Macro-Context-Agent` | Supplies macroeconomic context and trends to inform trading decisions. |
| `order-router-agent` | Routes and executes trade orders to the appropriate venue. |
| `quant-bridge-agent` | Bridges quantitative models with the agent pipeline for signal generation. |

### clax-ml
| Module | Description |
|---|---|
| `Optimal-Entry-Price` | Identifies optimal entry points for trades using ML-driven signals. |
| `Portfolio-Rebalancing` | Automates portfolio rebalancing based on target allocations and market conditions. |
| `Top-10-monthly-picks` | Generates a ranked list of the top 10 investment picks each month. |


