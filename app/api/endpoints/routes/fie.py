from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class Option(BaseModel):
    id: str
    label: str
    value: str

class Question(BaseModel):
    id: str
    order: int
    text: str
    options: List[Option]

class QuestionsResponse(BaseModel):
    questions: List[Question]

class AnswerItem(BaseModel):
    question_id: str
    option_id: str

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

class FIEResultSummary(BaseModel):
    profile: ProfileInfo
    summary: SummaryInfo

# Dummy Data
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
    ),
    TraitInfo(
        key="financial_room",
        section_label="YOUR FINANCIAL ROOM",
        title="Built for consistent, comfortable investing",
        description="You can invest without stressing your daily life, giving CLAX room to work with discipline."
    ),
    TraitInfo(
        key="growth_style",
        section_label="YOUR GROWTH STYLE",
        title="Steady growth",
        description="Measured progress, selective upside, low volatility — fits your comfort level and risk tolerance."
    )
]

mock_summary = SummaryInfo(
    Profile=mock_profile,
    trait_summary=[
        TraitSummary(section_label="YOUR WHY", short_value="Meaningful growth"),
        TraitSummary(section_label="YOUR RISK COMFORT", short_value="Measured swings"),
        TraitSummary(section_label="YOUR FINANCIAL ROOM", short_value="Consistent room"),
        TraitSummary(section_label="YOUR GROWTH STYLE", short_value="Balanced Growth")
    ],
    guidance=[
        "Prioritize low-volatility opportunities",
        "Rebalance with discipline",
        "Keep risk visible and easy to understand",
        "Reduce emotional decision-making"
    ],
    closing_line="Your best strategy is one you can stay with."
)

@router.get("/questions", response_model=QuestionsResponse)
async def get_questions():
    return QuestionsResponse(
        questions=[
            Question(
                id="q1", order=1, text="What is your main investing goal?",
                options=[
                    Option(id="o1_1", label="Growing savings", value="1"),
                    Option(id="o1_2", label="Monthly income", value="2"),
                    Option(id="o1_3", label="Goal in 1-3 years", value="3"),
                    Option(id="o1_4", label="Learning", value="4")
                ]
            ),
            Question(
                id="q2", order=2, text="What type of path are you looking for?",
                options=[
                    Option(id="o2_1", label="Steadier path", value="1"),
                    Option(id="o2_2", label="Balanced", value="2"),
                    Option(id="o2_3", label="Ambitious", value="3"),
                    Option(id="o2_4", label="Not sure", value="4")
                ]
            ),
            Question(
                id="q3", order=3, text="How do you feel about market swings?",
                options=[
                    Option(id="o3_1", label="Stressed at any loss", value="1"),
                    Option(id="o3_2", label="Small swings ok", value="2"),
                    Option(id="o3_3", label="Bigger swings ok", value="3"),
                    Option(id="o3_4", label="Long-term focus", value="4")
                ]
            ),
            Question(
                id="q3_followup", order=4, text="Which is more important to you?",
                options=[
                    Option(id="o3f_1", label="Protect first", value="1"),
                    Option(id="o3f_2", label="Grow steadily", value="2"),
                    Option(id="o3f_3", label="Grow faster", value="3")
                ]
            ),
            Question(
                id="q4", order=5, text="How much financial room do you have for investing?",
                options=[
                    Option(id="o4_1", label="Very little", value="1"),
                    Option(id="o4_2", label="Some room", value="2"),
                    Option(id="o4_3", label="Good room", value="3")
                ]
            ),
            Question(
                id="q4_followup", order=6, text="What is the status of your emergency fund?",
                options=[
                    Option(id="o4f_1", label="No emergency fund", value="1"),
                    Option(id="o4f_2", label="A little", value="2"),
                    Option(id="o4f_3", label="3 months", value="3"),
                    Option(id="o4f_4", label="6+ months", value="4")
                ]
            ),
            Question(
                id="q5", order=7, text="What is your experience level with investing?",
                options=[
                    Option(id="o5_1", label="Beginner", value="1"),
                    Option(id="o5_2", label="Intermediate", value="2"),
                    Option(id="o5_3", label="Advanced", value="3"),
                    Option(id="o5_4", label="Expert", value="4")
                ]
            )
        ]
    )

@router.post("/answers", response_model=FIEResultFull)
async def submit_answers(request: AnswersRequest):
    return FIEResultFull(
        profile=mock_profile,
        traits=mock_traits,
        summary=mock_summary
    )

@router.get("/result", response_model=FIEResultSummary)
async def get_result():
    return FIEResultSummary(
        profile=mock_profile,
        summary=mock_summary
    )
