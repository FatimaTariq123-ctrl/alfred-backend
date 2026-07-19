import sys
sys.path.append('/home/ummara/clax/macro-context-agent')
sys.path.append('/home/ummara/clax/investor-dna')

import json
import asyncio
import traceback
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from macro_context_agent import run_macro_context

app = Server("macro-context-agent")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_macro_context",
            description="Deep macro, fundamental, and geopolitical analysis personalized to the user's Investor DNA profile. Use when user asks 'why is this moving', about oil, China, geopolitics, earnings, or sector trends.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_question": {
                        "type": "string",
                        "description": "The user's macro or fundamental question"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID to fetch Investor DNA profile"
                    }
                },
                "required": ["user_question", "user_id"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "run_macro_context":
        user_id = arguments["user_id"]
        user_question = arguments["user_question"]

        # Lazy import to avoid startup connection issues
        try:
            from db.schema import get_profile
            investor_dna = get_profile(user_id)
            if not investor_dna:
                investor_dna = {"archetype": "Balanced Builder"}
        except Exception:
            investor_dna = {"archetype": "Balanced Builder"}

        # Run macro analysis
        result = run_macro_context(user_question, investor_dna)

        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise
