import sys
import asyncio
import json

# Adjust the paths to point to where the agents are located
sys.path.append('../../workspace/new_agents/macro-context-agent')
sys.path.append('../../workspace/new_agents/investor-dna')

from mcp_server import call_tool

async def run():
    print("Testing 'run_macro_context' MCP Tool...")
    args = {
        "user_id": "test_user_001",
        "user_question": "Why is gold going up right now?"
    }
    result = await call_tool("run_macro_context", args)
    
    # Expected to either print valid gemini response or a gemini API error
    # but confirms tool execution mechanics.
    print("Result:", result[0].text)

if __name__ == "__main__":
    asyncio.run(run())
