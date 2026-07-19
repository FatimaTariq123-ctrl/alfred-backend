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
    with Timer("macro-context-agent", "gemini_api_call"):
        response = requests.post(GEMINI_URL, json=payload, timeout=30)
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return f"Error calling Gemini: {json.dumps(data)}"


def run_macro_context(user_question: str, investor_dna: dict) -> dict:
    archetype = investor_dna.get("archetype", "Balanced Builder")
    why = investor_dna.get("insights", {}).get("why", {}).get("body", "")
    risk = investor_dna.get("insights", {}).get("risk", {}).get("body", "")
    target = investor_dna.get("target_reference", "~15% over 12 months")

    prompt = f"""
You are a world-class macro economist and fundamental analyst working for a personal wealth management AI called Alfred.

USER QUESTION: {user_question}

INVESTOR PROFILE:
- Archetype: {archetype}
- Why they invest: {why}
- Risk comfort: {risk}
- Target: {target}

Your job:
1. Provide a clear, plain-language macro/fundamental analysis of the topic.
2. Cover relevant geopolitics, commodities, sector trends, or earnings if applicable.
3. Explain cause-and-effect patterns across crypto, stocks, HK/China markets if relevant.
4. End with a section called "What this means for {archetype}" that directly connects the analysis to this user's profile.

Rules:
- Write for someone aged 12-80. No jargon without explanation.
- Short paragraphs. Clear language.
- Be honest about uncertainty.
- Never guarantee returns.
- Always mention risk.

Return your response as a JSON object with these exact fields:
{{
  "analysis": "your main macro analysis here",
  "what_this_means": "personalized section for {archetype}",
  "risk_note": "one sentence risk reminder",
  "ui_card": {{
    "title": "short title for the card",
    "body": "2-3 sentence summary for the UI card",
    "action_buttons": []
  }},
  "voice_script": "spoken version of the response, conversational tone, 3-4 sentences max"
}}

Return ONLY the JSON. No markdown. No explanation outside the JSON.
"""

    with Timer("macro-context-agent", "full_analysis", {"archetype": archetype}):
        raw = call_gemini(prompt)

    try:
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
    except Exception:
        result = {
            "analysis": raw,
            "what_this_means": "",
            "risk_note": "Always consider your risk tolerance before making decisions.",
            "ui_card": {
                "title": "Macro Analysis",
                "body": raw[:200],
                "action_buttons": []
            },
            "voice_script": raw[:300]
        }

    result["archetype"] = archetype
    result["user_question"] = user_question
    return result