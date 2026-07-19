# Order Router Agent

A lightweight MCP-enabled agent that translates conversational trade intent into a strict structured order payload for downstream guardrail and execution systems.

## Architecture

- `order_router_agent.py` contains the strict Pydantic payload model, LLM extraction path, and deterministic validation layer.
- `mcp_wrapper.py` exposes the `translate_trade_intent` MCP tool over stdio.
- `tests/` covers positive and negative payload examples.

## Responsibilities

This agent only translates user intent into a structured order payload. It does not execute orders, perform compliance checks, persist state, manage confirmation UI, or implement lifecycle tracking.

## Request Flow

1. The MCP tool receives `user_text` and optional `user_id`.
2. The router calls the configured LLM extraction path to produce a JSON object.
3. The payload is validated against the strict schema.
4. A structured response is returned with `valid`, `payload`, and `errors`.
5. If valid, the payload can be handed to downstream Guardrail Guard logic without transformation.

## Payload Schema

The router uses the following schema:

```json
{
  "ticker": "AAPL",
  "asset_class": "US_EQUITY",
  "action": "BUY",
  "order_type": "MARKET",
  "quantity": 10,
  "cash_allocation": 1000
}
```

Supported asset classes:
- `HK_EQUITY`
- `US_EQUITY`
- `VIRTUAL_ASSET`

Supported actions:
- `BUY`
- `SELL`
- `REBALANCE`

Supported order types:
- `MARKET`
- `LIMIT`
- `CONDITIONAL`

## Validation Flow

Validation ensures:
- required fields are present
- asset classes are supported
- order types are supported
- ticker is syntactically valid
- quantity is greater than zero
- cash allocation is greater than zero when supplied
- decimal precision is suitable for the asset type
- the final object conforms to the Pydantic schema

Invalid payloads return structured validation errors rather than silent correction.

## Guardrail Handoff

The router emits a guardrail-compatible payload shape through `guardrail_handoff` in the MCP response. The downstream guardrail component remains responsible for execution blocking and compliance checks.

## MCP Usage

Run locally:

```bash
cd /home/ummara/Alfred/clax/order-router-agent
python3 mcp_wrapper.py
```

Example MCP tool input:

```json
{
  "user_text": "Buy 10 shares of AAPL",
  "user_id": "user-123"
}
```

Example MCP tool response:

```json
{
  "valid": true,
  "payload": {
    "ticker": "AAPL",
    "asset_class": "US_EQUITY",
    "action": "BUY",
    "order_type": "MARKET",
    "quantity": 10
  },
  "errors": [],
  "guardrail_handoff": {
    "ticker": "AAPL",
    "asset_class": "US_EQUITY",
    "action": "BUY",
    "order_type": "MARKET",
    "quantity": 10
  }
}
```

## Integration Notes

- OpenClaw registration metadata is prepared in `openclaw_registration.json`.
- The agent is intentionally scoped to translation and validation only.
