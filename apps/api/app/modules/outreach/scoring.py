WEIGHTS = {
    "machinery_claim_volume_score": 20,
    "pain_intensity_score": 25,
    "buyer_access_score": 20,
    "data_availability_score": 15,
    "security_fit_score": 10,
    "pilot_willingness_score": 10,
}


def calculate_qualification_score(values: dict) -> int:
    total = 0.0
    for field, weight in WEIGHTS.items():
        score = max(0, min(5, int(values.get(field, 0) or 0)))
        total += (score / 5.0) * weight
    return round(total)


def qualification_band(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def recommended_action(score: int, stage: str) -> str:
    if stage == "no_fit":
        return "Do not pursue unless new evidence changes fit."
    band = qualification_band(score)
    return {
        "A": "Prioritize founder outreach and seek discovery within 14 days.",
        "B": "Pursue after A-tier accounts; validate buyer access and claim volume.",
        "C": "Nurture only; resolve qualification gaps before demo.",
        "D": "Do not spend active founder time yet.",
    }[band]
