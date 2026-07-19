from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sys
import os

sys.path.append('/home/ummara/clax/investor-dna')

from db.schema import save_profile, get_profile
from generator.generator import generate_profile

app = FastAPI()

class OnboardingAnswers(BaseModel):
    user_id: str
    q1: int
    q2: int
    q3: int
    q3_followup: int
    q4: int
    q4_followup: int

@app.post("/profile/create")
def create_profile(data: OnboardingAnswers):
    answers = {
        "q1": data.q1,
        "q2": data.q2,
        "q3": data.q3,
        "q3_followup": data.q3_followup,
        "q4": data.q4,
        "q4_followup": data.q4_followup
    }
    profile = generate_profile(data.user_id, answers)
    save_profile(profile)
    return {"status": "success", "profile": profile}

@app.get("/profile/{user_id}")
def fetch_profile(user_id: str):
    profile = get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "success", "profile": profile}


@app.get("/profile/questions/onboarding")
def get_onboarding_questions():
    return {
        "questions": [
            {
                "id": "q1",
                "voice": "What is this money for?",
                "title": "What is this money for?",
                "options": [
                    {"value": 1, "label": "Growing my savings over time"},
                    {"value": 2, "label": "Building extra monthly income"},
                    {"value": 3, "label": "A goal in the next 1–3 years"},
                    {"value": 4, "label": "Learning with a small amount first"}
                ]
            },
            {
                "id": "q2",
                "voice": "In the next 12 months, what kind of growth would feel right for you?",
                "title": "What kind of growth would feel right?",
                "options": [
                    {"value": 1, "label": "A steadier path, even if growth is lower"},
                    {"value": 2, "label": "A balanced path with moderate growth"},
                    {"value": 3, "label": "A more ambitious path with higher upside"},
                    {"value": 4, "label": "I'm not sure yet — help me choose"}
                ]
            },
            {
                "id": "q3",
                "voice": "If your account went down, at what point would it stop feeling okay?",
                "title": "At what point would loss stop feeling okay?",
                "options": [
                    {"value": 1, "label": "If I lost even a little, I'd be stressed"},
                    {"value": 2, "label": "I can handle small ups and downs"},
                    {"value": 3, "label": "I can accept bigger swings for bigger upside"},
                    {"value": 4, "label": "I understand losses happen if the long-term upside is worth it"}
                ]
            },
            {
                "id": "q3_followup",
                "voice": "Which feels closer to you?",
                "title": "Which feels closer to you?",
                "options": [
                    {"value": 1, "label": "Protect my money first"},
                    {"value": 2, "label": "Grow steadily"},
                    {"value": 3, "label": "Grow faster, even with bigger swings"}
                ]
            },
            {
                "id": "q4",
                "voice": "After your normal monthly costs, how much room do you comfortably have to invest?",
                "title": "How much room do you have to invest?",
                "options": [
                    {"value": 1, "label": "Very little — I'm testing with a small amount"},
                    {"value": 2, "label": "Some room — I can invest regularly"},
                    {"value": 3, "label": "Good room — I can invest without affecting my lifestyle"}
                ]
            },
            {
                "id": "q4_followup",
                "voice": "Do you already have money set aside for emergencies?",
                "title": "Do you have an emergency fund?",
                "options": [
                    {"value": 1, "label": "No"},
                    {"value": 2, "label": "A little"},
                    {"value": 3, "label": "Yes, at least 3 months"},
                    {"value": 4, "label": "Yes, more than 6 months"}
                ]
            }
        ]
    }