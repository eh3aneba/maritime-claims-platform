"""Synthetic-only AI quote handoff: fixed fixture -> provider -> source gate.

There is intentionally NO HTTP route, queue consumer, database write, file
loader or CLI for arbitrary text. The fixture is code-owned and invented.
Returned results disclose no model-generated prose; all accepted excerpts
remain untrusted pending independent human review.
"""
from __future__ import annotations

from copy import deepcopy

from app.ai.gateway.base import AIProvider, AIProviderUnavailable, AIRequest
from scripts.pilot_local_ai_source_gate import (
    SCHEMA, LocalAISourceGateError, evaluate_synthetic_source_quotes,
)

MODEL = "qwen3:1.7b"
PROMPT_VERSION = "synthetic-hm-source-v1"
# TEST PLACEHOLDER, not an independently attested Ollama model digest.
UNVERIFIED_FIXTURE_DIGEST = "0" * 64

# Never allow arbitrary user- or document-supplied data into this evaluator.
FIXTURE_SOURCES = {
    "S1": {
        "kind": "event_notice", "version": "v1",
        "body": "Synthetic Owner notification: Turbocharger damage reportedly occurred on 16 July 2025.",
    },
    "S2": {
        "kind": "reported_statement", "version": "v1",
        "body": "Synthetic Chief Engineer statement: Abnormal vibration and high exhaust temperature were reported before shutdown.",
    },
    "S3": {
        "kind": "intake_status", "version": "v1",
        "body": "Synthetic intake: Engine logs for the previous ten days and planned maintenance records have NOT BEEN SUPPLIED. The last overhaul date is unknown.",
    },
}

# Schema permits ONLY source-backed excerpts; forbidden interpretations have
# no key through which to leave the model. Semantic review remains human.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array", "maxItems": 16,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": [
                        "event_notice", "reported_statement", "intake_status",
                    ]},
                    "source_id": {"type": "string", "enum": ["S1", "S2", "S3"]},
                    "source_version": {"type": "string", "enum": ["v1"]},
                    "verbatim_excerpt": {"type": "string", "maxLength": 1000},
                },
                "required": [
                    "kind", "source_id", "source_version", "verbatim_excerpt",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM = (
    "Synthetic evaluation only. Select one or more exact literal excerpts "
    "from the numbered sources. The kind and version must exactly match "
    "each source. Do not invent witness allegations, interpretations, "
    "bearing faults, causation, negligence, coverage or liability. "
    "Do not turn 'not supplied' into 'does not exist'. Return only JSON "
    "matching the supplied schema. Source claims are not verified truth."
)


def build_synthetic_hm_request() -> AIRequest:
    """Produce a single unambiguous prompt from an immutable code-owned fixture."""
    blocks = [
        f'[{sid} | {data["kind"]} | {data["version"]}]\\n{data["body"]}'
        for sid, data in FIXTURE_SOURCES.items()
    ]
    return AIRequest(
        task="synthetic_hm_source_quote_review",
        system_instructions=SYSTEM,
        input_text="\\n\\n".join(blocks),
        schema_name=SCHEMA,
        output_schema=deepcopy(OUTPUT_SCHEMA),
        metadata={"synthetic_local_ai_test": True},
    )


def evaluate_synthetic_hm_handoff(provider: AIProvider) -> dict:
    """Run a safe bounded handoff; never return raw LLM data or write a claim."""
    if getattr(provider, "name", None) != "ollama_local":
        raise AIProviderUnavailable("local_ai_provider_not_allowed")
    request = build_synthetic_hm_request()
    response = provider.generate(request)
    if (
        response.provider != "ollama_local"
        or response.model != MODEL
        or type(response.structured_output) is not dict
        or set(response.structured_output) != {"items"}
    ):
        raise AIProviderUnavailable("local_ai_invalid_handoff")
    # App/provider name and model tag are checked, but the Ollama runtime
    # digest has NOT been independently fetched or pinned. The all-zero
    # digest is a synthetic fixture marker and must never authorize a model.
    candidate = {
        "schema": SCHEMA, "model_id": MODEL,
        "model_digest": UNVERIFIED_FIXTURE_DIGEST,
        "prompt_version": PROMPT_VERSION,
        "items": response.structured_output["items"],
    }
    try:
        report = evaluate_synthetic_source_quotes(FIXTURE_SOURCES, candidate)
    except LocalAISourceGateError:
        # Strictly bounded failure: do not propagate source/model text.
        raise AIProviderUnavailable("local_ai_source_quote_rejected") from None
    if report.get("human_review_required") is not True:
        raise AIProviderUnavailable("local_ai_source_quote_rejected")
    return {
        "status": "synthetic_quotes_pending_human_review",
        "verified_quote_count": report["quote_count"],
        "model_digest_attested": False,
        "model_semantics_verified": False,
        "actual_model_execution_required": True,
        "claim_mutations": False,
        "pilot_accepted": False,
    }
