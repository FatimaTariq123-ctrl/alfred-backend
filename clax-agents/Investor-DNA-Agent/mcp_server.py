import sys
sys.path.append('/home/ummara/clax/investor-dna')

import json
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from db.schema import save_profile, get_profile
from generator.generator import generate_profile

app = Server("investor-dna")

async def warmup():
    try:
        from db.schema import get_pool
        get_pool()
        print("✅ DB connection pool warmed up")
    except Exception as e:
        print(f"⚠️ Warmup failed: {e}")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="create_investor_profile",
            description="Run onboarding classification and save Investor DNA profile for a user.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Unique user ID"},
                    "q1": {"type": "integer", "description": "Answer to Q1 (1-4)"},
                    "q2": {"type": "integer", "description": "Answer to Q2 (1-4)"},
                    "q3": {"type": "integer", "description": "Answer to Q3 (1-4)"},
                    "q3_followup": {"type": "integer", "description": "Answer to Q3 follow-up (1-3)"},
                    "q4": {"type": "integer", "description": "Answer to Q4 (1-3)"},
                    "q4_followup": {"type": "integer", "description": "Answer to Q4 follow-up (1-4)"}
                },
                "required": ["user_id", "q1", "q2", "q3", "q3_followup", "q4", "q4_followup"]
            }
        ),
        types.Tool(
            name="get_investor_profile",
            description="Fetch the full Investor DNA profile for a user. Inject this into every conversation and agent call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Unique user ID"}
                },
                "required": ["user_id"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "create_investor_profile":
        answers = {
            "q1": arguments["q1"],
            "q2": arguments["q2"],
            "q3": arguments["q3"],
            "q3_followup": arguments["q3_followup"],
            "q4": arguments["q4"],
            "q4_followup": arguments["q4_followup"]
        }
        profile = generate_profile(arguments["user_id"], answers)
        save_profile(profile)
        return [types.TextContent(
            type="text",
            text=json.dumps(profile, indent=2)
        )]

    elif name == "get_investor_profile":
        profile = get_profile(arguments["user_id"])
        if not profile:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "Profile not found for user: " + arguments["user_id"]})
            )]
        return [types.TextContent(
            type="text",
            text=json.dumps(profile, indent=2)
        )]

async def main():
    await warmup()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())