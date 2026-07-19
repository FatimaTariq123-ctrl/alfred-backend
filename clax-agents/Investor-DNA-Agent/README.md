# Investor DNA Agent Test

This directory contains the testing script for the `investor-dna` agent.

## Prerequisites
1. The `investor-dna` FastAPI server must be running locally on port 8000.
2. The MCP server is also available and integrates closely with OpenClaw.

## How to Test
1. Make sure dependencies are installed (`fastapi`, `uvicorn`, `psycopg2-binary`, `python-dotenv`).
2. Run the main server using:
```bash
   python3 main.py
```
3. Execute the test script:
```bash
   python3 test_api.py
```
This will send a POST request to `/profile/create` and return the newly generated Investor DNA profile based on the questionnaire answers.
