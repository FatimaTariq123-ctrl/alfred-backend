import sys
import asyncio
import json

# Replace these paths with the absolute paths to the respective agent repositories
sys.path.append('./fact-guard-agent')
sys.path.append('./investor-dna')

from mcp_server import call_tool

async def run():
    print("Testing 'run_fact_guard' MCP Tool...")
    args = {
        "user_id": "test_user_001",
        "agent_output": {
            "ui_card": {"title": "Investment Opportunity", "body": "This is a guaranteed return!"},
            "voice_script": "I guarantee this will make you money."
        }
    }
    result = await call_tool("run_fact_guard", args)
    print("\n--- Result ---")
    print(result[0].text)

if __name__ == "__main__":
    asyncio.run(run())
