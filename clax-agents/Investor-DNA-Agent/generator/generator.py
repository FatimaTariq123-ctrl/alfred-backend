import uuid
from datetime import date, timedelta
from engine.classifier import classify_investor


def generate_profile(user_id: str, answers: dict) -> dict:
    """
    Takes user_id and raw onboarding answers.
    Returns the full Investor DNA JSON ready to store.
    """
    # Run classification
    classified = classify_investor(answers)

    # Calculate dates
    today = date.today()
    archetype = classified["archetype"]

    # Steady Builder gets 12 month reprofile, others 6 months
    if archetype == "Steady Builder":
        reprofile_due = today + timedelta(days=365)
    else:
        reprofile_due = today + timedelta(days=180)

    # Build full profile JSON
    profile = {
        "profile_id": str(uuid.uuid4()),
        "user_id": user_id,
        "created_date": str(today),
        "last_updated": str(today),
        "reprofile_due": str(reprofile_due),
        "archetype": classified["archetype"],
        "profile_subtitle": classified["profile_subtitle"],
        "target_reference": classified["target_reference"],
        "time_horizon_months": classified["time_horizon_months"],
        "insights": classified["insights"],
        "guidance": classified["guidance"],
        "aha_line": classified["aha_line"],
        "raw_answers": answers
    }

    return profile