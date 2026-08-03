from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

router = APIRouter()

class Option(BaseModel):
    id: str
    value: int
    label: str

class Question(BaseModel):
    id: str
    voice: str
    title: str
    options: List[Option]

class QuestionsResponse(BaseModel):
    questions: List[Question]

class AnswerItem(BaseModel):
    question_id: str
    option_id: str
    value: int

class AnswersRequest(BaseModel):
    answers: List[AnswerItem]

class ProfileInfo(BaseModel):
    id: str
    name: str
    tagline: str
    target_reference: str

class TraitInfo(BaseModel):
    key: str
    section_label: str
    title: str
    description: str

class TraitSummary(BaseModel):
    section_label: str
    short_value: str

class SummaryInfo(BaseModel):
    Profile: ProfileInfo
    trait_summary: List[TraitSummary]
    guidance: List[str]
    closing_line: str

class FIEResultFull(BaseModel):
    profile: ProfileInfo
    traits: List[TraitInfo]
    summary: SummaryInfo

mock_profile = ProfileInfo(
    id="steady_builder",
    name="Steady Builder",
    tagline="Growth that feels thoughtful, steady, and in control.",
    target_reference="~10% ROI / 12 months"
)

mock_traits = [
    TraitInfo(
        key="why",
        section_label="YOUR WHY",
        title="Goal-driven with a medium-term mindset",
        description="You're not chasing random moves. You want your money working toward something meaningful, with enough time to grow without feeling locked in."
    ),
    TraitInfo(
        key="risk_comfort",
        section_label="YOUR RISK COMFORT",
        title="Balanced with lower market swings",
        description="You can tolerate some movement, but clarity and control matter. CLAX will focus on logical, lower-volatility setups."
    )
]

mock_summary = SummaryInfo(
    Profile=mock_profile,
    trait_summary=[
        TraitSummary(section_label="YOUR WHY", short_value="Meaningful growth"),
        TraitSummary(section_label="YOUR RISK COMFORT", short_value="Measured swings")
    ],
    guidance=[
        "Prioritize low-volatility opportunities",
        "Rebalance with discipline"
    ],
    closing_line="Your best strategy is one you can stay with."
)

@router.get("/questions", response_model=QuestionsResponse)
async def get_questions():
    """
    Returns an array of 7 questions for the FIE onboarding flow.
    Includes the standard investor DNA questions + experience level, along with their options.
    """
    return QuestionsResponse(
        questions=[
            {
                "id": "q1",
                "voice": "What is this money for?",
                "title": "What is this money for?",
                "options": [
                    {"id": "o1_1", "value": 1, "label": "Growing my savings over time"},
                    {"id": "o1_2", "value": 2, "label": "Building extra monthly income"},
                    {"id": "o1_3", "value": 3, "label": "A goal in the next 1-3 years"},
                    {"id": "o1_4", "value": 4, "label": "Learning with a small amount first"}
                ]
            },
            {
                "id": "q2",
                "voice": "In the next 12 months, what kind of growth would feel right for you?",
                "title": "What kind of growth would feel right?",
                "options": [
                    {"id": "o2_1", "value": 1, "label": "A steadier path, even if growth is lower"},
                    {"id": "o2_2", "value": 2, "label": "A balanced path with moderate growth"},
                    {"id": "o2_3", "value": 3, "label": "A more ambitious path with higher upside"},
                    {"id": "o2_4", "value": 4, "label": "I'm not sure yet - help me choose"}
                ]
            },
            {
                "id": "q3",
                "voice": "If your account went down, at what point would it stop feeling okay?",
                "title": "At what point would loss stop feeling okay?",
                "options": [
                    {"id": "o3_1", "value": 1, "label": "If I lost even a little, I'd be stressed"},
                    {"id": "o3_2", "value": 2, "label": "I can handle small ups and downs"},
                    {"id": "o3_3", "value": 3, "label": "I can accept bigger swings for bigger upside"},
                    {"id": "o3_4", "value": 4, "label": "I understand losses happen if the long-term upside is worth it"}
                ]
            },
            {
                "id": "q3_followup",
                "voice": "Which feels closer to you?",
                "title": "Which feels closer to you?",
                "options": [
                    {"id": "o3f_1", "value": 1, "label": "Protect my money first"},
                    {"id": "o3f_2", "value": 2, "label": "Grow steadily"},
                    {"id": "o3f_3", "value": 3, "label": "Grow faster, even with bigger swings"}
                ]
            },
            {
                "id": "q4",
                "voice": "After your normal monthly costs, how much room do you comfortably have to invest?",
                "title": "How much room do you have to invest?",
                "options": [
                    {"id": "o4_1", "value": 1, "label": "Very little - I'm testing with a small amount"},
                    {"id": "o4_2", "value": 2, "label": "Some room - I can invest regularly"},
                    {"id": "o4_3", "value": 3, "label": "Good room - I can invest without affecting my lifestyle"}
                ]
            },
            {
                "id": "q4_followup",
                "voice": "Do you already have money set aside for emergencies?",
                "title": "Do you have an emergency fund?",
                "options": [
                    {"id": "o4f_1", "value": 1, "label": "No"},
                    {"id": "o4f_2", "value": 2, "label": "A little"},
                    {"id": "o4f_3", "value": 3, "label": "Yes, at least 3 months"},
                    {"id": "o4f_4", "value": 4, "label": "Yes, more than 6 months"}
                ]
            },
            {
                "id": "q5",
                "voice": "What is your experience level with investing?",
                "title": "What is your experience level with investing?",
                "options": [
                    {"id": "o5_1", "value": 1, "label": "Beginner"},
                    {"id": "o5_2", "value": 2, "label": "Intermediate"},
                    {"id": "o5_3", "value": 3, "label": "Advanced"},
                    {"id": "o5_4", "value": 4, "label": "Expert"}
                ]
            }
        ]
    )

@router.post("/answers", response_model=FIEResultFull)
async def submit_answers(request: AnswersRequest):
    """
    Receives an array of answers for all the FIE questions in a single API call.
    Returns the investor DNA result based on the provided answers.
    """
    return FIEResultFull(
        profile=mock_profile,
        traits=mock_traits,
        summary=mock_summary
    )
