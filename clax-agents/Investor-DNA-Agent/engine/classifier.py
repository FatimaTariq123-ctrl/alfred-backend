def classify_investor(answers: dict) -> dict:
    """
    Decision tree classifier based on onboarding answers.
    answers = {
        "q1": 1-4,
        "q2": 1-4,
        "q3": 1-4,
        "q3_followup": 1-3,
        "q4": 1-3,
        "q4_followup": 1-4
    }
    """
    q1 = answers.get("q1")
    q2 = answers.get("q2")
    q3 = answers.get("q3")
    q3f = answers.get("q3_followup")
    q4 = answers.get("q4")
    q4f = answers.get("q4_followup")

    # --- DECISION TREE ---

    # Guided Starter: learning with small amount OR not sure + stressed at loss + very little room
    if q1 == 4 or (q2 == 4 and q3 == 1 and q4 == 1):
        return _build_result("Guided Starter", answers)

    # Steady Builder: steadier path + protect first + little financial room
    if q2 == 1 and q3f == 1 and q4 in [1, 2]:
        return _build_result("Steady Builder", answers)

    # Ambitious Builder: ambitious path + bigger swings okay + good financial room + emergency fund
    if q2 == 3 and q3 in [3, 4] and q3f == 3 and q4 == 3 and q4f in [3, 4]:
        return _build_result("Ambitious Builder", answers)

    # Balanced Builder: default middle ground
    return _build_result("Balanced Builder", answers)


def _build_result(archetype: str, answers: dict) -> dict:
    profiles = {
        "Guided Starter": {
            "profile_subtitle": "Let's start small, learn together, and build your confidence.",
            "target_reference": "~5% over 12 months",
            "time_horizon_months": 12,
            "why_label": "Learning & exploring",
            "why_body": "You want to understand investing before committing more.",
            "risk_label": "Very cautious",
            "risk_body": "Any loss feels uncomfortable right now, and that's okay.",
            "room_label": "Starting small",
            "room_body": "You're testing with a small amount — smart and safe.",
            "growth_label": "Gentle start",
            "growth_body": "Slow and steady wins — we'll grow your confidence first.",
            "aha_line": "Every expert was once a beginner. Let's begin.",
            "guidance": [
                "start with low-risk assets",
                "focus on education first",
                "avoid complex instruments",
                "build emergency fund before investing more"
            ]
        },
        "Steady Builder": {
            "profile_subtitle": "Growth that feels safe, protected, and in control.",
            "target_reference": "~8% over 12 months",
            "time_horizon_months": 24,
            "why_label": "Protection & stability",
            "why_body": "You want your money to grow without keeping you up at night.",
            "risk_label": "Low risk",
            "risk_body": "Small, controlled movements are acceptable. Big swings are not.",
            "room_label": "Consistent room",
            "room_body": "You invest regularly without affecting your lifestyle.",
            "growth_label": "Conservative growth",
            "growth_body": "Steady, reliable returns with capital protection in focus.",
            "aha_line": "Slow money is smart money.",
            "guidance": [
                "prioritize capital protection",
                "stick to low-volatility assets",
                "avoid leverage entirely",
                "rebalance quarterly"
            ]
        },
        "Balanced Builder": {
            "profile_subtitle": "Growth that feels thoughtful, steady, and in control.",
            "target_reference": "~15% over 12 months",
            "time_horizon_months": 36,
            "why_label": "Meaningful growth",
            "why_body": "You want your money working toward something real.",
            "risk_label": "Measured swings",
            "risk_body": "You can handle movement, as long as it feels controlled.",
            "room_label": "Consistent room",
            "room_body": "You have enough flexibility to invest without pressure.",
            "growth_label": "Balanced growth",
            "growth_body": "A measured path with selective upside and risk kept in view.",
            "aha_line": "Your best strategy is one you can stay with.",
            "guidance": [
                "prioritize balanced opportunities",
                "keep risk visible",
                "rebalance with discipline",
                "reduce emotional decisions"
            ]
        },
        "Ambitious Builder": {
            "profile_subtitle": "Bold moves, calculated risks, and serious upside.",
            "target_reference": "~25% over 12 months",
            "time_horizon_months": 48,
            "why_label": "Aggressive growth",
            "why_body": "You want serious returns and you're willing to accept the ride.",
            "risk_label": "High tolerance",
            "risk_body": "You understand losses happen and focus on long-term upside.",
            "room_label": "Strong financial base",
            "room_body": "You invest comfortably without touching your lifestyle or safety net.",
            "growth_label": "High growth",
            "growth_body": "Maximum upside with calculated, eyes-open risk.",
            "aha_line": "Fortune favors the prepared.",
            "guidance": [
                "pursue high-growth opportunities",
                "diversify across sectors",
                "monitor positions actively",
                "keep 20% in stable assets as anchor"
            ]
        }
    }

    p = profiles[archetype]
    return {
        "archetype": archetype,
        "profile_subtitle": p["profile_subtitle"],
        "target_reference": p["target_reference"],
        "time_horizon_months": p["time_horizon_months"],
        "insights": {
            "why": {
                "title": "Your Why",
                "label": p["why_label"],
                "body": p["why_body"]
            },
            "risk": {
                "title": "Your Risk Comfort",
                "label": p["risk_label"],
                "body": p["risk_body"]
            },
            "financial_room": {
                "title": "Your Financial Room",
                "label": p["room_label"],
                "body": p["room_body"]
            },
            "growth_style": {
                "title": "Your Growth Style",
                "label": p["growth_label"],
                "body": p["growth_body"]
            }
        },
        "guidance": p["guidance"],
        "aha_line": p["aha_line"],
        "raw_answers": answers
    }