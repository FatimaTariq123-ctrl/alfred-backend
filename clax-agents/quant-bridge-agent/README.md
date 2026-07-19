# Quant Bridge Agent

An MCP-enabled bridge agent that exposes the three core quantitative Machine Learning services as Model Context Protocol (MCP) tools over `stdio`. This allows OpenClaw to interact directly with these quantitative and predictive models without bypassing the MCP architecture.

## Architecture

- `config.py` holds endpoint configurations, URLs, and timeout settings.
- `quant_bridge_agent.py` contains the helper methods to call the corresponding FastAPI endpoints with robust timeout and exception handling.
- `mcp_server.py` implements the MCP stdio server and exposes three tools: `get_optimal_entry`, `get_top10_monthly_picks`, and `rebalance_portfolio`.

## Exposed MCP Tools

### 1. `get_optimal_entry`
- **Description:** Provides the optimal entry and exit price signals for a given equity or crypto ticker (e.g. AAPL, BTC-USD) from the Optimal Entry Price ML model.
- **Parameters:**
  - `ticker` (string, required): Ticker symbol of the asset to evaluate.
- **Underlying Endpoint:** `POST http://localhost:8001/optimal-entry-exit-price`

### 2. `get_top10_monthly_picks`
- **Description:** Retrieves the latest top-10 stock predictions, identifying stocks expected to outperform the S&P 500 index for the upcoming monthly period (next 22 trading days).
- **Parameters:**
  - `date` (string, optional): Target date in `YYYY-MM-DD` format. Uses the latest available date if omitted.
- **Underlying Endpoint:** `GET http://localhost:8002/predict/top10`

### 3. `rebalance_portfolio`
- **Description:** Analyzes current portfolio holdings and returns optimization recommendations from the Portfolio Rebalancing ML model based on a target ROI and optional constraints.
- **Parameters:**
  - `user_id` (string, required): Unique ID of the user.
- **Underlying Endpoint:** `POST http://localhost:8003/api/v1/portfolio/rebalance`

## Setup and MCP Integration

To run the MCP server locally over stdio:

```bash
cd /home/ummara/Alfred/clax-agents/quant-bridge-agent
python3 mcp_server.py
```

## Resilience

Each tool handler is built with robust error handling and request timeouts. If any downstream FastAPI ML service is offline, timed out, or returns an HTTP validation error, the agent intercepts the exception and returns a structured JSON error response (including specific `error` categories and detailed descriptions) rather than throwing unhandled exceptions.
