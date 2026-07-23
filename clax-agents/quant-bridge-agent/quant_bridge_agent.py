import requests
import json
from config import OPTIMAL_ENTRY_URL, TOP10_MONTHLY_PICKS_URL, PORTFOLIO_REBALANCE_URL, REQUEST_TIMEOUT

class QuantBridgeAgent:
    def route_to_quant_models(self, user_id: str, trade_intent: dict, investor_profile: dict, macro_context: dict):
        """
        Task 4 & 5: Propagate Risk Tier and Blocked Sectors into execution payloads.
        """
        user_risk_tier = investor_profile.get("archetype", "Balanced Builder")
        blocked_sectors = macro_context.get("restricted_sectors", [])
        
        execution_payload = {
            "intent": trade_intent,
            "constraints": {
                "max_risk_tier": user_risk_tier,
                "blocked_sectors": blocked_sectors
            }
        }
        
        return execution_payload

def call_optimal_entry(ticker: str) -> dict:
    payload = {"ticker": ticker}
    try:
        response = requests.post(OPTIMAL_ENTRY_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": "UnexpectedError", "detail": str(e)}
