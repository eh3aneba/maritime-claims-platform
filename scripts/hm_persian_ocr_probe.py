"""Synthetic Persian OCR literal-probe disposition. Never infer missing words.

This is an engineering regression observation, not a claim-specific
quality classifier, transcript reconstruction or coverage decision.
"""
from __future__ import annotations

PROBES = ("توربوشارژر", "نیست")


def evaluate_literal_probe_retrieval(observations: dict[str, bool]) -> dict:
    if (
        type(observations) is not dict
        or set(observations) != set(PROBES)
        or any(type(x) is not bool for x in observations.values())
    ):
        raise ValueError("invalid_synthetic_persian_probe_observations")
    term_found = observations["توربوشارژر"]
    negation_found = observations["نیست"]
    return {
        "machinery_term_retrieved": term_found,
        "negation_retrieved": negation_found,
        "critical_negation_omission_observed": not negation_found,
        "both_literal_probes_retrieved": term_found and negation_found,
        # Do not equate lexical match with semantic confidence.
        "human_bilingual_review_required": True,
        "full_transcription_verified": False,
        "negation_scope_verified": False,
        "critical_fact_authorization_granted": False,
        "quality_disposition": (
            "technical_and_negation_missing_review_required"
            if not term_found and not negation_found
            else "technical_missing_review_required"
            if not term_found
            else "negation_missing_review_required"
            if not negation_found
            else "two_literals_present_semantics_unverified"
        ),
        "pilot_accepted": False,
    }
