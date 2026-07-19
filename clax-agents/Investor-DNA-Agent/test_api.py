import requests
import json

def test_create_profile():
    url = "http://localhost:8000/profile/create"
    payload = {
        "user_id": "test_user_001",
        "q1": 1,
        "q2": 2,
        "q3": 3,
        "q3_followup": 2,
        "q4": 2,
        "q4_followup": 3
    }
    print("Testing create profile endpoint...")
    try:
        response = requests.post(url, json=payload)
        print("Status Code:", response.status_code)
        print("Response Body:", json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_create_profile()
