import asyncio
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_a5_lifecycle():
    print("--- Testing A5 Idempotency Engine ---")
    headers = {
        "Authorization": "Bearer test_token",
        "X-Idempotency-Key": "test-uuid-1234"
    }
    payload = {"asset": "AAPL", "qty": 10}
    
    print("\n1. Testing Path A (First Request):")
    # For testing, we mock Redis or assume Redis is down (graceful fallback).
    # Since we are running this without the docker-compose redis up, 
    # it will hit the graceful fallback.
    response = client.post("/api/v1/orders/commit", headers=headers, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Body: {response.json()}")

test_a5_lifecycle()
