from fastapi import APIRouter

onboarding_router = APIRouter()

@onboarding_router.get("/questions")
async def get_questions():
    return {"success": True, "data": {"questions": [{"id": "q_risk", "prompt": "How would you describe your investing style?", "options": ["Cautious Saver", "Steady Grower", "Ambitious Builder"]}]}}

@onboarding_router.post("/answers")
async def post_answers(answers: dict):
    return {"success": True, "data": {"investor_archetype": "Ambitious Builder", "onboarding_complete": True}}
