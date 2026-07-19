import sys
sys.path.append('/home/ummara/clax/fact-guard-agent')
sys.path.append('/home/ummara/clax/investor-dna')

import json
import asyncio
import traceback
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from fact_guard_agent import run_fact_guard

app = Server("fact-guard-agent")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_fact_guard",
            description="Mandatory final quality and compliance gate. ALWAYS call this last before Alfred responds. Checks factual accuracy, compliance language, tone, and alignment with Investor DNA profile. Returns PASS, MINOR_FIX, or REJECT.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_output": {
                        "type": "object",
                        "description": "The full output from any MOE agent to be checked"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID to fetch Investor DNA profile for alignment check"
                    }
                },
                "required": ["agent_output", "user_id"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "run_fact_guard":
        user_id = arguments["user_id"]
        agent_output = arguments["agent_output"]

        # Lazy import to avoid startup connection issues
        try:
            from db.schema import get_profile
            investor_dna = get_profile(user_id)
            if not investor_dna:
                investor_dna = {"archetype": "Balanced Builder"}
        except Exception:
            investor_dna = {"archetype": "Balanced Builder"}

        # Run fact guard check
        result = run_fact_guard(agent_output, investor_dna)

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
