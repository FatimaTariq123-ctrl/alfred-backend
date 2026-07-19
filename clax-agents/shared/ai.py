import os
import requests
from shared.logger import Timer

def call_gemini(prompt: str, service: str = "shared-ai") -> str:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key}"
    
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    with Timer(service, "gemini_api_call"):
        response = requests.post(gemini_url, json=payload, timeout=30)
    data = response.json()
    
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Failed to parse Gemini response: {data}. Error: {e}")
