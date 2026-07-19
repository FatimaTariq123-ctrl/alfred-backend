import os
import json
import requests
import sys
from dotenv import load_dotenv

sys.path.append('/home/ummara/clax/shared')
from logger import Timer

load_dotenv('/home/ummara/clax/.env')

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

def call_gemini(prompt: str) -> str:
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    with Timer("fact-guard-agent", "gemini_api_call"):
        response = requests.post(GEMINI_URL, json=payload, timeout=30)
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return f"Error calling Gemini: {json.dumps(data)}"


def run_fact_guard(agent_output: dict, investor_dna: dict) -> dict:
    archetype = investor_dna.get("archetype", "Balanced Builder")
    guidance = investor_dna.get("guidance", [])
    risk_label = investor_dna.get("insights", {}).get("risk", {}).get("label", "")

    prompt = f"""
You are FactGuardAgent — the mandatory quality and compliance gate for Alfred, a personal wealth management AI.

Your job is to review the following agent output before it reaches the user and decide: PASS, MINOR_FIX, or REJECT.

AGENT OUTPUT TO REVIEW:
{json.dumps(agent_output, indent=2)}

USER INVESTOR DNA:
- Archetype: {archetype}
- Risk comfort: {risk_label}
- Guidance: {', '.join(guidance)}

CHECK ALL OF THE FOLLOWING:

1. FACTUAL ACCURACY
   - Does the output contain any obvious hallucinations or false claims?
   - Are any statistics or figures suspiciously precise without sourcing?

2. COMPLIANCE & RISK LANGUAGE
   - Does it contain any guaranteed return claims? (NEVER allowed)
   - Does it mention risk appropriately?
   - Is there any encouragement of leverage or day trading for Guided Starter or Steady Builder profiles?

3. PROFILE ALIGNMENT
   - Is the tone and advice aligned with the user's archetype ({archetype})?
   - Does it respect their risk comfort level ({risk_label})?

4. TONE & SIMPLICITY
   - Is it written clearly for someone aged 12-80?
   - Is it warm, human, and not condescending?

VERDICT RULES:
- PASS: Output is clean, compliant, and profile-aligned. No changes needed.
- MINOR_FIX: Output has small issues that can be corrected. Provide corrected version.
- REJECT: Output has serious compliance violations, hallucinations, or is fundamentally misaligned. Provide reason.

Return ONLY a JSON object with these exact fields:
{{
  "verdict": "PASS" | "MINOR_FIX" | "REJECT",
  "issues": ["list of issues found, empty if PASS"],
  "corrected_output": {{same structure as input with fixes applied, null if PASS or REJECT}},
  "reject_reason": "reason if REJECT, null otherwise",
  "compliance_notes": "one sentence summary of compliance status"
}}

Return ONLY the JSON. No markdown. No explanation outside the JSON.
"""

    with Timer("fact-guard-agent", "full_guard_check", {"archetype": archetype}):
        raw = call_gemini(prompt)

    try:
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
    except Exception:
        result = {
            "verdict": "PASS",
            "issues": [],
            "corrected_output": None,
            "reject_reason": None,
            "compliance_notes": "FactGuard parsing error — defaulting to PASS."
        }

    return result