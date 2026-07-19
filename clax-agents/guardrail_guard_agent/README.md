# Guardrail Guard Agent

Guardrail Guard is a deterministic execution firewall for CLAX/OpenClaw action requests.
It runs after the multi-asset order router and before trade execution, paper trading ledger
writes, database commits, or any simulated/real execution handoff.

This agent is intentionally separate from FactGuard. FactGuard reviews language quality and
factual response content. Guardrail Guard reviews structured execution payloads and returns a
machine-readable decision only.

## Files

- `guardrail_agent.py` - deterministic validation logic and local test block.
- `mcp_wrapper.py` - MCP stdio wrapper exposing `run_guardrail_guard`.
- `__init__.py` - package exports for direct imports.

## MVP Checks

- Market closed block.
- Simulation-only enforcement.
- Stale price block with configurable freshness threshold.
- BUY balance check.
- User approval confirmation requirement.
- Restricted ticker block.
- Slippage protection by asset class.

## Local Test

Run:

```bash
python3 guardrail_guard_agent/guardrail_agent.py
```

The script prints sample decisions for approve, block, confirmation, stale price,
insufficient balance, restricted asset, and excessive slippage cases.
