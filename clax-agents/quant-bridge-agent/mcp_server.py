import os
import sys
import json
import asyncio
import traceback

sys.path.append(os.path.dirname(__file__))

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from quant_bridge_agent import call_optimal_entry, call_top10_monthly_picks, call_rebalance_portfolio

app = Server("quant-bridge-agent")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_optimal_entry",
            description="Provides the optimal entry and exit price signals for a given equity or crypto ticker (e.g. AAPL, BTC-USD) from the Optimal Entry Price ML model.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "The ticker symbol of the equity or crypto asset to evaluate (e.g., AAPL, BTC-USD)."
                    }
                },
                "required": ["ticker"]
            }
        ),
        types.Tool(
            name="get_top10_monthly_picks",
            description="Retrieves the latest top-10 stock predictions, identifying stocks expected to outperform the S&P 500 index for the upcoming monthly period (next 22 trading days).",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Optional date in YYYY-MM-DD format. If omitted, uses the latest available date automatically."
                    }
                }
            }
        ),
        types.Tool(
            name="rebalance_portfolio",
            description="Analyzes current portfolio holdings and returns optimization recommendations from the Portfolio Rebalancing ML model based on a target ROI and optional constraints.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The unique ID of the user."
                    },
                    "portfolio_id": {
                        "type": "string",
                        "description": "The unique ID of the portfolio."
                    },
                    "target_roi": {
                        "type": "number",
                        "description": "The target Return on Investment (ROI) for the portfolio (must be non-negative)."
                    },
                    "holdings": {
                        "type": "array",
                        "description": "List of current holdings in the portfolio.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "symbol": {
                                    "type": "string",
                                    "description": "Ticker symbol of the holding (e.g., AAPL)."
                                },
                                "quantity": {
                                    "type": "number",
                                    "description": "Number of shares or units held."
                                },
                                "current_price": {
                                    "type": "number",
                                    "description": "Current market price of the asset."
                                }
                            },
                            "required": ["symbol", "quantity", "current_price"]
                        }
                    },
                    "rebalance_type": {
                        "type": "string",
                        "description": "Optional rebalancing strategy/risk type. Defaults to 'moderate'.",
                        "enum": ["conservative", "moderate", "aggressive"]
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Optional portfolio optimization constraints.",
                        "properties": {
                            "max_single_stock_weight": {
                                "type": "number",
                                "description": "Maximum weight allowed for a single stock (0.0 to 1.0)."
                            },
                            "long_only": {
                                "type": "boolean",
                                "description": "Whether to restrict the portfolio to long-only positions. Defaults to true."
                            }
                        }
                    }
                },
                "required": ["user_id", "portfolio_id", "target_roi", "holdings"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "get_optimal_entry":
            ticker = arguments["ticker"]
            result = call_optimal_entry(ticker)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )
            ]
        elif name == "get_top10_monthly_picks":
            date = arguments.get("date")
            result = call_top10_monthly_picks(date)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )
            ]
        elif name == "rebalance_portfolio":
            result = call_rebalance_portfolio(arguments)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )
            ]
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        error_response = {
            "error": "ToolExecutionError",
            "detail": str(e),
            "traceback": traceback.format_exc()
        }
        return [
            types.TextContent(
                type="text",
                text=json.dumps(error_response, indent=2)
            )
        ]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise
