# Macro Context Agent Test

This directory contains the testing script for the `macro-context-agent` MCP server.

## Prerequisites
1. OpenClaw MCP dependencies (`mcp`) must be installed.
2. The agent expects `.env` file with `GEMINI_API_KEY` (if not provided, it will return an API error gracefully).
3. Requires access to `investor-dna` code to fetch user profiles.

## How to Test
1. Make sure Python paths are properly configured to find both `macro-context-agent` and `investor-dna` dependencies.
2. Execute the test script:
```bash
   python3 test_mcp.py
```
This script acts as a simulated MCP client and directly calls the tool logic `run_macro_context` exactly how OpenClaw does, providing a `user_id` and a `user_question`.
