"""Post-blind, manual synthetic-only local model quote preview.

The *only* printable excerpts are reconstructed from invented, code-owned
source strings after strict source-ID/version/verbatim validation.
No real claim loader, storage, reviewer decision or external AI.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from app.ai.gateway.base import AIProvider, AIProviderUnavailable, AIResponse
from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider
from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, scenario_names, synthetic_source_catalog,
)
from scripts.pilot_local_ai_hm_critical_quote_coverage import observe_required_literal_quote_coverage
from scripts.pilot_local_ai_hm_loopback_smoke import (
    MODEL, _safe_rejection_category, build_fixed_scenario_request,
)
from scripts.pilot_local_ai_hm_neutral_blind_packet import fixed_neutral_blind_hm_phase_one_packet
from scripts.pilot_local_ai_source_gate import LocalAISourceGateError

_CASE_CODES = ("CASE-01", "CASE-02", "CASE-03")
_ACCEPTED = "source_quotes_accepted_for_human_review"
_INCOMPLETE = "source_quotes_incomplete_for_review"
_MAX_ITEMS = 16


def run_fixed_postblind_synthetic_quote_view(provider: AIProvider) -> dict[str, Any]:
    """Exactly three invented source-based calls, never print invalid LLM text."""
    if getattr(provider, "name", None) != "ollama_local":
        raise AIProviderUnavailable("local_ai_provider_not_allowed")
    packet = fixed_neutral_blind_hm_phase_one_packet()
    if (
        type(packet) is not dict
        or packet.get("scope") != "invented_hm_neutral_blind_phase_one_only"
        or packet.get("packet_version") != "hm-neutral-phase-one-v1"
        or packet.get("reviewer_blindness_verified") is not False
        or packet.get("expert_labels_collected") is not False
        or packet.get("review_completed") is not False
        or packet.get("pilot_accepted") is not False
        or type(packet.get("cases")) is not list
        or [x.get("case_code") for x in packet["cases"] if type(x) is dict] != list(_CASE_CODES)
    ):
        raise ValueError("untrusted_synthetic_phase_one_packet")
    cases: list[dict[str, Any]] = []
    for code, scenario in zip(_CASE_CODES, scenario_names()):
        try:
            response = provider.generate(build_fixed_scenario_request(scenario))
            if (
                not isinstance(response, AIResponse)
                or response.provider != "ollama_local"
                or response.model != MODEL
                or type(response.structured_output) is not dict
                or set(response.structured_output) != {"items"}
            ):
                raise AIProviderUnavailable("local_ai_invalid_handoff")
            candidate = deterministic_reference_candidate(scenario)
            candidate["items"] = response.structured_output["items"]
            # The existing gate rejects unsupported text, wrong lineage, extra
            # fields, oversized items, duplicates and false claims authority.
            report = observe_required_literal_quote_coverage(scenario, candidate)
            if len(candidate["items"]) > _MAX_ITEMS:
                raise LocalAISourceGateError("invalid_items")
            source_catalog = synthetic_source_catalog(scenario)
            safe_excerpts: list[dict[str, Any]] = []
            for item in candidate["items"]:
                source = source_catalog[item["source_id"]]
                start = source["body"].find(item["verbatim_excerpt"])
                if start < 0:
                    raise LocalAISourceGateError("unsupported_quote")
                end = start + len(item["verbatim_excerpt"])
                # Never forward model text directly. Reconstruct only from
                # the already validated, fixed invented source catalog.
                safe_excerpts.append({
                    "source_id": item["source_id"],
                    "source_version": source["version"],
                    "kind": source["kind"],
                    "source_offset_start": start,
                    "source_offset_end": end,
                    "invented_source_excerpt": source["body"][start:end],
                })
            cases.append({
                "case_code": code,
                "status": (
                    _ACCEPTED if report["critical_literal_coverage_observed"]
                    else _INCOMPLETE
                ),
                "critical_literal_coverage_observed": report["critical_literal_coverage_observed"],
                "context_pairs_same_excerpt_missing": report["context_pairs_same_excerpt_missing"],
                "model_selected_source_excerpts": safe_excerpts,
                "expert_semantic_review_completed": False,
            })
        except (AIProviderUnavailable, LocalAISourceGateError) as error:
            cases.append({
                "case_code": code, "status": "rejected",
                "rejection_category": _safe_rejection_category(error),
                "expert_semantic_review_completed": False,
            })
    return {
        "scope": "invented_hm_postblind_source_quotes_only",
        "packet_version": "hm-postblind-quotes-v1",
        "phase_one_packet_sha256_observed": packet["packet_sha256_observed"],
        "phase_one_packet_digest_independently_attested": False,
        "independent_reference_frozen_verified": False,
        "expert_labels_collected": False,
        "expert_semantic_review_completed": False,
        "model_tag_unverified": MODEL,
        "model_execution_independently_attested": False,
        "model_digest_attested": False,
        "network_egress_isolation_verified": False,
        "real_claims_processed": False,
        "coverage_or_liability_decisions": False,
        "pilot_accepted": False,
        "all_source_quotes_valid_for_review": all(c["status"] == _ACCEPTED for c in cases),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--reveal-fixed-synthetic-ollama-quotes-for-postblind-review"]:
        print("postblind_synthetic_hm_explicit_opt_in_required")
        return 2
    try:
        provider = OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=512)
        result = run_fixed_postblind_synthetic_quote_view(provider)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if result["all_source_quotes_valid_for_review"] else 1
    except Exception:
        print("postblind_synthetic_hm_quote_view_unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
