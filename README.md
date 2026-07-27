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

- **Docker Desktop** (Windows/macOS) or **Docker Engine** (Linux)
- **Docker Compose**
- Python 3.12+ (Only if running manually without Docker)

### How to Install Docker
- **Windows:** Download and install from [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/).
- **macOS:** Download and install from [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/).
- **Linux:** Follow the instructions for your distribution at [Docker Engine for Linux](https://docs.docker.com/engine/install/).

*(Note: The project uses a cloud-hosted PostgreSQL database, so a local PostgreSQL installation is no longer required for Docker development.)*

## Setup (Docker - Recommended)

The Clax Backend is fully dockerized. You do **not** need to manually install Python, FastAPI, Uvicorn, or run `pip install` locally.

### 1. Clone the repository

```bash
git clone https://github.com/ummara-clax/ALFRED.git
cd ALFRED
```

### 2. Configure environment variables

```bash
cp .env.example .env
```
Edit `.env` and configure your cloud `DATABASE_URL` (and `NEON_DATABASE_URL`) along with other required secrets.

### 3. Build and start the project

```bash
docker compose up --build
```
This single command automatically builds and orchestrates all necessary containers:
- **Builds the Standard API Image (`Dockerfile`)**: Used by the FastAPI backend and reconciliation worker, installing dependencies from `requirements.txt`.
- **Builds the OpenClaw Gateway Image (`Dockerfile.openclaw`)**: Preserves customized OpenClaw runtime files.
- **Starts Redis**: Spins up the cache instance on port 6379.
- **Starts OpenClaw Gateway**: Available internally and locally on port 18789.
- **Starts FastAPI Backend**: Available on `http://localhost:8000`.
- **Starts Reconciliation Worker**: Runs the background reconciliation process.

### 4. Stopping the containers

To stop the running services, use `Ctrl+C` in the terminal where it's running, or run:
```bash
docker compose down
```

### 5. Rebuilding containers after dependency changes

If you add new libraries to `requirements.txt`, you must rebuild the image:
```bash
docker compose up --build
```

### Troubleshooting
- **Port 8000 / 6379 is already in use:** Ensure no local instances of Uvicorn or Redis are running on your host machine.
- **Database Connection Errors:** Verify that your `DATABASE_URL` in `.env` points to a valid cloud PostgreSQL instance.
- **Platform-specific Notes:** Windows users running WSL2 should ensure Docker Desktop is configured to use the WSL2 backend for better performance.

## Manual Setup (Without Docker)

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

