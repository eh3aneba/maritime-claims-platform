"""Synthetic Persian OCR literal-probe disposition. Never infer missing words.

This is an engineering regression observation, not a claim-specific
quality classifier, transcript reconstruction or coverage decision.
"""
from __future__ import annotations

PROBES = ("توربوشارژر", "نیست")
# Fixed, public, invented HM-05 clause. Retrieval is NOT semantic validation.
SCOPED_NEGATION_PHRASE = "علت قطعی خرابی هنوز معلوم نیست و بررسی سوابق ضروری است."


def evaluate_literal_probe_retrieval(
    observations: dict[str, bool], *, scoped_phrase_retrieved: bool | None = None
) -> dict:
    if (
        type(observations) is not dict
        or set(observations) != set(PROBES)
        or any(type(x) is not bool for x in observations.values())
    ):
        raise ValueError("invalid_synthetic_persian_probe_observations")
    if scoped_phrase_retrieved is not None and type(scoped_phrase_retrieved) is not bool:
        raise ValueError("invalid_synthetic_scoped_phrase_observation")
    term_found = observations["توربوشارژر"]
    negation_found = observations["نیست"]
    return {
        "machinery_term_retrieved": term_found,
        "negation_retrieved": negation_found,
        "critical_negation_omission_observed": not negation_found,
        "both_literal_probes_retrieved": term_found and negation_found,
        # None means this extra check was not run; False means it was run
        # and no complete page-scoped phrase was retrieved.
        "scoped_negation_phrase_retrieved": scoped_phrase_retrieved,
        "scoped_negation_phrase_measured": scoped_phrase_retrieved is not None,
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
            else "scoped_negation_phrase_unretrieved_review_required"
            if scoped_phrase_retrieved is False
            else "two_literals_present_semantics_unverified"
        ),
        "pilot_accepted": False,
    }
