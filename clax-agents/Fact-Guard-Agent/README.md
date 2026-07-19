# Fact Guard Agent Testing Guide

This document contains the testing script and instructions for the `fact-guard-agent` MCP server.

## Prerequisites
1. OpenClaw MCP dependencies (`mcp`) must be installed.
2. The agent expects a `.env` file with `GEMINI_API_KEY` to run the compliance LLM check.
3. The script needs visibility of the `investor-dna` dependency to analyze the output against the target user's risk tolerance profile.

## How to Test
1. Save the python code below as `test_mcp.py`.
2. Run it via `python3 test_mcp.py`.
3. The script passes a mocked non-compliant payload (e.g., guaranteed returns) to the `run_fact_guard` tool and evaluates the response.

## Testing Code (`test_mcp.py`)
```python
import sys
import asyncio
import json

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
```
