"""Code-owned synthetic H&M fixture matrix for *offline* source-quote tests.

Not a runtime AI interface, expert reference adjudication, customer Evidence
reader, real reviewer, approval queue or claim assessment. Never calls a model.
"""
from __future__ import annotations

from copy import deepcopy

from scripts.pilot_local_ai_source_gate import (
    SCHEMA, LocalAISourceGateError, evaluate_synthetic_source_quotes,
)

MODEL_TAG_UNVERIFIED = "qwen3:1.7b"
PROMPT_VERSION = "synthetic-hm-source-v1"
UNVERIFIED_DIGEST = "0" * 64

# All text is invented in code. Versioned references have NOT been adjudicated
# by an independent H&M claims expert; they are test expectations only.
_SCENARIOS = {
    "complete_records": {
        "S1": {"kind": "event_notice", "version": "v1",
               "body": "Synthetic Owner notice: Turbocharger damage was reported on 16 July 2025."},
        "S2": {"kind": "reported_statement", "version": "v1",
               "body": "Synthetic engine-log extract: Alarm at 11:30 and shutdown at 11:35 were recorded."},
        "S3": {"kind": "intake_status", "version": "v1",
               "body": "Synthetic intake: Engine logs and planned-maintenance extracts were supplied for review; their accuracy is unverified."},
    },
    "missing_engine_records": {
        "S1": {"kind": "event_notice", "version": "v1",
               "body": "Synthetic Owner notice: Turbocharger damage reportedly occurred on 16 July 2025."},
        "S2": {"kind": "reported_statement", "version": "v1",
               "body": "Synthetic engineer account: Abnormal vibration and high exhaust temperature were reported before shutdown."},
        "S3": {"kind": "intake_status", "version": "v1",
               "body": "Synthetic intake: Engine logs for the previous ten days and maintenance records have NOT BEEN SUPPLIED; their existence is unknown."},
    },
    "conflicting_alarm_times": {
        "S1": {"kind": "reported_statement", "version": "v1",
               "body": "Synthetic engineer statement: The turbocharger alarm occurred at 11:30 according to the engineer."},
        "S2": {"kind": "reported_statement", "version": "v1",
               "body": "Synthetic workshop statement: The turbocharger alarm occurred at 11:55 according to the workshop."},
        "S3": {"kind": "intake_status", "version": "v1",
               "body": "Synthetic intake: The two reported alarm times conflict and no independent resolution was supplied."},
    },
}


def scenario_names() -> tuple[str, ...]:
    return tuple(_SCENARIOS)


def _sources(scenario: object) -> dict:
    if type(scenario) is not str or scenario not in _SCENARIOS:
        raise LocalAISourceGateError("unknown_synthetic_scenario")
    return _SCENARIOS[scenario]


def synthetic_source_catalog(scenario: object) -> dict:
    """Copy only built-in invented source data; never accept caller source text."""
    return deepcopy(_sources(scenario))


def deterministic_reference_candidate(scenario: object) -> dict:
    """Code-owned literal-quote baseline, not an expert label or AI inference."""
    sources = _sources(scenario)
    items = [
        {"kind": source["kind"], "source_id": sid,
         "source_version": source["version"],
         "verbatim_excerpt": source["body"]}
        for sid, source in sources.items()
    ]
    return {
        "schema": SCHEMA, "model_id": MODEL_TAG_UNVERIFIED,
        "model_digest": UNVERIFIED_DIGEST,
        "prompt_version": PROMPT_VERSION, "items": items,
    }


def evaluate_synthetic_scenario(scenario: object, candidate: object) -> dict:
    """Evaluate exact-source attribution against an unreviewed code baseline.

    No prompt, source text, candidate prose or claim identifiers in results.
    Never use these metrics as quality accreditation or Pilot GO.
    """
    sources = _sources(scenario)
    report = evaluate_synthetic_source_quotes(sources, candidate)
    if (
        type(candidate["model_id"]) is not str
        or candidate["model_id"] != MODEL_TAG_UNVERIFIED
        or type(candidate["model_digest"]) is not str
        or candidate["model_digest"] != UNVERIFIED_DIGEST
        or type(candidate["prompt_version"]) is not str
        or candidate["prompt_version"] != PROMPT_VERSION
    ):
        raise LocalAISourceGateError("synthetic_model_metadata_mismatch")

    reference = deterministic_reference_candidate(scenario)["items"]
    expected = {(x["source_id"], x["source_version"], x["verbatim_excerpt"]) for x in reference}
    actual = {(x["source_id"], x["source_version"], x["verbatim_excerpt"]) for x in candidate["items"]}
    matches = len(expected & actual)
    return {
        "scope": "synthetic_development_only",
        "scenario": scenario,
        "validated_quote_count": report["quote_count"],
        "reference_quote_count": len(expected),
        "reference_match_count": matches,
        "reference_missing_count": len(expected) - matches,
        "other_source_backed_quote_count": len(actual - expected),
        "reference_expert_approved": False,
        "model_digest_attested": False,
        "real_model_executed": False,
        "human_review_required": True,
        "authoritative_fact_updates": False,
        "coverage_or_liability_decisions": False,
        "pilot_accepted": False,
    }
