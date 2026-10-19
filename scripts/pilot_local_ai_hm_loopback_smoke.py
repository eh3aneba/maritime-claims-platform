"""Explicit opt-in, synthetic-only, local Ollama H&M scenario smoke.

No customer input, no document/file loader, no persistence, no external API.
CLI sends only three fixed invented scenarios to the existing 127.0.0.1
development adapter and prints bounded counters instead of model text.
"""
from __future__ import annotations

from copy import deepcopy
import json
import sys
from time import monotonic
from typing import Any

from app.ai.gateway.base import AIProvider, AIProviderUnavailable, AIRequest
from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider
from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, evaluate_synthetic_scenario,
    scenario_names, synthetic_source_catalog,
)
from scripts.pilot_local_ai_source_gate import SCHEMA, LocalAISourceGateError
from scripts.pilot_local_ai_synthetic_handoff import MODEL, OUTPUT_SCHEMA, SYSTEM

_EXPECTED_RESPONSE_KEYS = frozenset({"items"})
_MAX_SCENARIO_INPUT_CHARS = 4096


def build_fixed_scenario_request(scenario: str) -> AIRequest:
    """Build only from code-owned inputs; never accept raw text or file paths."""
    sources = synthetic_source_catalog(scenario)
    blocks = [
        f'[{sid} | {source["kind"]} | {source["version"]}]\n{source["body"]}'
        for sid, source in sources.items()
    ]
    input_text = "\n\n".join(blocks)
    if not 1 <= len(input_text) <= _MAX_SCENARIO_INPUT_CHARS:
        raise AIProviderUnavailable("local_ai_synthetic_request_invalid")
    return AIRequest(
        task="synthetic_hm_source_quote_review",
        system_instructions=SYSTEM,
        input_text=input_text,
        schema_name=SCHEMA,
        output_schema=deepcopy(OUTPUT_SCHEMA),
        metadata={"synthetic_local_ai_test": True},
    )


def run_fixed_three_scenario_smoke(provider: AIProvider) -> dict[str, Any]:
    """Run every fixed scenario, retaining only attribution counts and timings.

    Even a returned 'pass' verifies neither semantic truth nor real model
    identity: an injected test double may impersonate the provider name.
    """
    if getattr(provider, "name", None) != "ollama_local":
        raise AIProviderUnavailable("local_ai_provider_not_allowed")
    results: list[dict[str, Any]] = []
    for scenario in scenario_names():
        request = build_fixed_scenario_request(scenario)
        started = monotonic()
        try:
            response = provider.generate(request)
            if (
                response.provider != "ollama_local"
                or response.model != MODEL
                or type(response.structured_output) is not dict
                or set(response.structured_output) != _EXPECTED_RESPONSE_KEYS
            ):
                raise AIProviderUnavailable("local_ai_invalid_handoff")
            candidate = deterministic_reference_candidate(scenario)
            candidate["items"] = response.structured_output["items"]
            report = evaluate_synthetic_scenario(scenario, candidate)
            result = {
                "scenario": scenario,
                "status": "source_quotes_accepted_for_human_review",
                "quote_count": report["validated_quote_count"],
                "literal_baseline_match_count": report["reference_match_count"],
                "literal_baseline_missing_count": report["reference_missing_count"],
                "other_source_backed_quote_count": report["other_source_backed_quote_count"],
            }
        except (AIProviderUnavailable, LocalAISourceGateError):
            # No model text, request body, traceback, network exception or path.
            result = {"scenario": scenario, "status": "rejected"}
        result["elapsed_ms_observed"] = max(0, int((monotonic() - started) * 1000))
        results.append(result)

    return {
        "scope": "synthetic_development_only",
        "model_tag_unverified": MODEL,
        "local_transport_attested": False,
        "model_digest_attested": False,
        "expert_ground_truth_approved": False,
        "human_review_completed": False,
        "real_claims_processed": False,
        "pilot_accepted": False,
        "all_accepted_for_human_review": all(
            r["status"] == "source_quotes_accepted_for_human_review"
            for r in results
        ),
        "scenarios": results,
    }


def main(argv: list[str] | None = None) -> int:
    """Explicit manual-only invocation; importing this module never connects."""
    arguments = sys.argv[1:] if argv is None else argv
    if arguments != ["--run-fixed-synthetic-ollama"]:
        print("local_ai_explicit_synthetic_opt_in_required")
        return 2
    try:
        provider = OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=512)
        report = run_fixed_three_scenario_smoke(provider)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0 if report["all_accepted_for_human_review"] else 1
    except Exception:
        # CLI failure must not disclose a local API response or model prose.
        print("local_ai_synthetic_smoke_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
