import asyncio
import json
import os
import sys
import traceback

sys.path.append(os.path.dirname(__file__))

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from order_router_agent import OrderRouterAgent

app = Server("order-router-agent")
agent = OrderRouterAgent()


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="translate_trade_intent",
            description=(
                "Convert conversational trade intent into a strict structured order payload. "
                "This tool only translates and validates; guardrail, execution, and persistence remain downstream."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_text": {"type": "string", "description": "The conversational trade request."},
                    "user_id": {"type": "string", "description": "Optional user identifier."},
                },
                "required": ["user_text"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "translate_trade_intent":
        result = agent.translate(arguments.get("user_text", ""), arguments.get("user_id"))
        response = {
            "valid": result.valid,
            "payload": result.payload.model_dump() if result.payload else None,
            "errors": [error.model_dump() for error in result.errors],
            "guardrail_handoff": result.payload.to_guardrail_payload(arguments.get("user_id")) if result.payload else None,
        }
        return [
            types.TextContent(
                type="text",
                text=json.dumps(response, indent=2),
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
