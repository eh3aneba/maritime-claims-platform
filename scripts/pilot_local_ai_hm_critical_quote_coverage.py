"""Minimum invented-evidence quote coverage for offline synthetic H&M smoke.

Exact literal anchor observations only. No claim inference, source authority,
semantic assessment, or external AI invocation; always unreviewed by an H&M
expert. This is a *stricter development signal*, never an approval.
"""
from __future__ import annotations

from scripts.pilot_local_ai_hm_fixture_matrix import (
    evaluate_synthetic_scenario, synthetic_source_catalog,
)

# Each phrase is an exact code-owned substring of its source. Individual
# requirements are intentionally independent: S1 and S2 must both appear
# for a contradiction; "not supplied" must not be read as "nonexistent".
_REQUIRED_LITERAL_QUOTES = {
    "complete_records": (
        ("S1", "Turbocharger damage was reported"),
        ("S2", "Alarm at 11:30 and shutdown at 11:35"),
        ("S3", "were supplied for review"),
        ("S3", "accuracy is unverified"),
    ),
    "missing_engine_records": (
        ("S1", "Turbocharger damage reportedly occurred"),
        ("S2", "Abnormal vibration and high exhaust temperature"),
        ("S3", "NOT BEEN SUPPLIED"),
        ("S3", "existence is unknown"),
    ),
    "conflicting_alarm_times": (
        ("S1", "alarm occurred at 11:30"),
        ("S2", "alarm occurred at 11:55"),
        ("S3", "no independent resolution was supplied"),
    ),
}

# An *observational* signal: important epistemic qualifiers must accompany
# their related claim within ONE attributed excerpt. Two separately valid
# snippets can each pass substring checks while obscuring that connection.
# This is NOT an expert semantic check and does NOT change the quote gate.
_CONTEXT_PAIRS_SAME_EXCERPT = {
    "complete_records": (
        ("S1", "Turbocharger damage", "was reported"),
        ("S2", "Alarm at 11:30", "shutdown at 11:35"),
        ("S3", "were supplied for review", "accuracy is unverified"),
    ),
    "missing_engine_records": (
        ("S1", "Turbocharger damage", "reportedly occurred"),
        ("S2", "Abnormal vibration", "were reported before shutdown"),
        ("S3", "NOT BEEN SUPPLIED", "existence is unknown"),
    ),
    "conflicting_alarm_times": (
        ("S1", "alarm occurred at 11:30", "according to the engineer"),
        ("S2", "alarm occurred at 11:55", "according to the workshop"),
        ("S3", "reported alarm times conflict", "no independent resolution was supplied"),
    ),
}


def observe_required_literal_quote_coverage(scenario: object, candidate: object) -> dict:
    """Count code-authored critical phrases *within validated quoted excerpts*.

    An anchor matched inside a source-backed excerpt is not a truth finding,
    human judgement or semantic verification. Return fixed counters only.
    """
    report = evaluate_synthetic_scenario(scenario, candidate)
    inventory = synthetic_source_catalog(scenario)
    requirements = _REQUIRED_LITERAL_QUOTES[scenario]
    # Development integrity guard: no requirement may drift outside its source.
    if any(source_id not in inventory or phrase not in inventory[source_id]["body"]
           for source_id, phrase in requirements):
        raise RuntimeError("synthetic_reference_integrity_failure")

    pairs = _CONTEXT_PAIRS_SAME_EXCERPT[scenario]
    if any(
        source_id not in inventory
        or left not in inventory[source_id]["body"]
        or right not in inventory[source_id]["body"]
        for source_id, left, right in pairs
    ):
        raise RuntimeError("synthetic_context_reference_integrity_failure")

    context_pairs_observed = sum(
        any(
            item["source_id"] == source_id
            and left in item["verbatim_excerpt"]
            and right in item["verbatim_excerpt"]
            for item in candidate["items"]
        )
        for source_id, left, right in pairs
    )
    observed = 0
    for source_id, phrase in requirements:
        if any(item["source_id"] == source_id and phrase in item["verbatim_excerpt"]
               for item in candidate["items"]):
            observed += 1
    return {
        "scenario": scenario,
        "validated_quote_count": report["validated_quote_count"],
        "literal_baseline_match_count": report["reference_match_count"],
        "literal_baseline_missing_count": report["reference_missing_count"],
        "other_source_backed_quote_count": report["other_source_backed_quote_count"],
        "critical_literal_requirements_total": len(requirements),
        "critical_literal_requirements_observed": observed,
        "critical_literal_requirements_missing": len(requirements) - observed,
        "critical_literal_coverage_observed": observed == len(requirements),
        "context_pairs_total": len(pairs),
        "context_pairs_same_excerpt_observed": context_pairs_observed,
        "context_pairs_same_excerpt_missing": len(pairs) - context_pairs_observed,
        "context_preservation_expert_verified": False,
        "expert_ground_truth_approved": False,
        "semantic_claims_verified": False,
        "coverage_or_liability_decisions": False,
        "pilot_accepted": False,
    }
