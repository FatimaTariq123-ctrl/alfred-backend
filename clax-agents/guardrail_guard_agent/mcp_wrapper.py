import asyncio
import json
import os
import sys
import traceback

sys.path.append(os.path.dirname(__file__))

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from guardrail_agent import run_guardrail_guard

app = Server("guardrail-guard-agent")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_guardrail_guard",
            description=(
                "Deterministic hard execution firewall. Call after order routing and before "
                "trade execution, paper ledger writes, database commits, or any real/simulated "
                "execution handoff."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action_request": {
                        "type": "object",
                        "description": "Structured action request payload to evaluate.",
                        "properties": {
                            "user_id": {"type": "string"},
                            "ticker": {"type": "string"},
                            "asset_class": {"type": "string"},
                            "action": {"type": "string"},
                            "quantity": {"type": "number"},
                            "order_type": {"type": "string"},
                            "execution_price": {"type": "number"},
                            "reference_price": {"type": "number"},
                            "market_price": {"type": "number"},
                            "market_timestamp": {
                                "description": "ISO-8601 datetime or epoch timestamp.",
                                "oneOf": [{"type": "string"}, {"type": "number"}],
                            },
                            "user_cash_balance": {"type": "number"},
                            "estimated_total": {"type": "number"},
                            "is_simulation": {"type": "boolean"},
                            "user_approved": {"type": "boolean"},
                            "market_open": {"type": "boolean"},
                            "restrictions": {
                                "description": "Restricted tickers/assets as a list, dict, or string.",
                                "oneOf": [
                                    {"type": "array"},
                                    {"type": "object"},
                                    {"type": "string"},
                                ],
                            },
                        },
                        "required": [
                            "ticker",
                            "asset_class",
                            "action",
                            "execution_price",
                            "market_timestamp",
                            "market_open",
                        ],
                    }
                },
                "required": ["action_request"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "run_guardrail_guard":
        result = run_guardrail_guard(arguments["action_request"])
        return [
            types.TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        ]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise
