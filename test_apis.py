import requests

def test_apis():
    print("Testing FIE GET Questions...")
    res = requests.get("http://127.0.0.1:8000/api/v1/fie/questions")
    print("FIE Questions:", res.status_code, res.json())
    
    print("Testing FIE POST Answers...")
    res = requests.post("http://127.0.0.1:8000/api/v1/fie/answers", json={
        "answers": [{"question_id": "q1", "option_id": "o1"}]
    })
    print("FIE Answers:", res.status_code, res.json())
    
    print("Testing Chat Open...")
    res = requests.post("http://127.0.0.1:8000/chat/open")
    print("Chat Open:", res.status_code, res.json())

    print("Testing Chat Messages...")
    res = requests.post("http://127.0.0.1:8000/chat/messages", json={
        "room_id": "room_1", "role": "user", "content": "hi", "created_at": "2026"
    })
    print("Chat Messages:", res.status_code, res.json())

if __name__ == "__main__":
    test_apis()
