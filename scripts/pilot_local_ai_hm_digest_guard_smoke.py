"""Opt-in synthetic three-round Ollama smoke with pre/post local-tag drift guard.

This *does not* attest the model weights or prove the same model was used
during inference. It merely observes two untrusted, read-only tag snapshots
around exactly nine fixed, invented H&M inference calls. No files or claim data.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Callable

from app.ai.gateway.base import AIProvider
from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider
from scripts.pilot_local_ai_model_inventory import inspect_fixed_local_model_inventory
from scripts.pilot_local_ai_hm_repeat_smoke import (
    MODEL, run_three_fixed_rounds,
)

_DIGEST_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ROUNDS = 3
_SCENARIOS = 3


def _observed_unattested_digest(observation: object) -> str:
    """Accept only a strict local-registry observation, never self-attest."""
    if (
        type(observation) is not dict
        or observation.get("scope") != "synthetic_local_pc_inventory_only"
        or observation.get("registry") != "ollama_loopback_tag_listing"
        or observation.get("expected_model_tag") != MODEL
        or observation.get("model_tag_observed") is not True
        or any(observation.get(field) is not False for field in (
            "observed_digest_source_attested",
            "model_artifact_independently_attested",
            "model_execution_verified",
            "network_egress_isolation_verified",
            "human_review_completed",
            "pilot_accepted",
        ))
    ):
        raise ValueError("invalid_local_model_observation")
    digest = observation.get("observed_digest_sha256")
    if type(digest) is not str or _DIGEST_HEX.fullmatch(digest) is None:
        raise ValueError("invalid_local_model_observation")
    return digest


def run_fixed_digest_guarded_smoke(
    provider: AIProvider,
    observe_inventory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Check before and after nine requests, retaining only bounded counts."""
    before = _observed_unattested_digest(observe_inventory())
    repeat = run_three_fixed_rounds(provider)
    if (
        type(repeat) is not dict
        or repeat.get("rounds_observed") != _ROUNDS
        or repeat.get("fixed_scenarios_per_round") != _SCENARIOS
        or repeat.get("pilot_accepted") is not False
        or repeat.get("model_digest_attested") is not False
        or repeat.get("expert_ground_truth_approved") is not False
        or type(repeat.get("all_rounds_source_quotes_accepted_for_review")) is not bool
    ):
        raise ValueError("invalid_local_repeat_report")
    scenarios = repeat.get("scenarios")
    if type(scenarios) is not list or len(scenarios) != _SCENARIOS:
        raise ValueError("invalid_local_repeat_report")
    names = ("complete_records", "missing_engine_records", "conflicting_alarm_times")
    safe_rows: list[dict[str, Any]] = []
    for index, item in enumerate(scenarios):
        if type(item) is not dict or item.get("scenario") != names[index]:
            raise ValueError("invalid_local_repeat_report")
        row: dict[str, Any] = {"scenario": names[index]}
        for key in ("accepted_rounds", "incomplete_rounds", "rejected_rounds"):
            count = item.get(key)
            if type(count) is not int or not 0 <= count <= _ROUNDS:
                raise ValueError("invalid_local_repeat_report")
            row[key] = count
        if sum(row[k] for k in ("accepted_rounds", "incomplete_rounds", "rejected_rounds")) != _ROUNDS:
            raise ValueError("invalid_local_repeat_report")
        for key in (
            "context_complete_rounds", "context_incomplete_rounds",
            "context_not_evaluated_rounds", "context_pairs_missing_total",
        ):
            number = item.get(key)
            if type(number) is not int or not 0 <= number <= (
                _ROUNDS * _SCENARIOS if key == "context_pairs_missing_total" else _ROUNDS
            ):
                raise ValueError("invalid_local_repeat_report")
            row[key] = number
        if (
            row["context_complete_rounds"] + row["context_incomplete_rounds"]
            + row["context_not_evaluated_rounds"] != _ROUNDS
            or row["context_not_evaluated_rounds"] != row["rejected_rounds"]
            or (row["context_incomplete_rounds"] == 0) !=
                (row["context_pairs_missing_total"] == 0)
        ):
            raise ValueError("invalid_local_repeat_report")
        safe_rows.append(row)
    after = _observed_unattested_digest(observe_inventory())
    unchanged = before == after
    all_quotes = repeat["all_rounds_source_quotes_accepted_for_review"]
    # Results never output either digest itself or any model-generated text.
    return {
        "scope": "synthetic_development_only",
        "model_tag_unverified": MODEL,
        "rounds_observed": _ROUNDS,
        "fixed_scenarios_per_round": _SCENARIOS,
        "local_tag_digest_same_before_after": unchanged,
        "all_rounds_source_quotes_accepted_for_review": all_quotes,
        "guarded_observation_accepted_for_human_review": unchanged and all_quotes,
        "model_digest_attested": False,
        "model_execution_independently_attested": False,
        "model_artifact_independently_attested": False,
        "network_egress_isolation_verified": False,
        "repeatability_proven": False,
        "expert_ground_truth_approved": False,
        "context_preservation_expert_verified": False,
        "human_review_completed": False,
        "pilot_accepted": False,
        "scenarios": safe_rows,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--run-fixed-synthetic-ollama-digest-guard"]:
        print("local_model_digest_guard_explicit_opt_in_required")
        return 2
    try:
        provider = OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=512)
        result = run_fixed_digest_guarded_smoke(provider, inspect_fixed_local_model_inventory)
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0 if result["guarded_observation_accepted_for_human_review"] else 1
    except Exception:
        # No HTTP body, model text, registry contents, path or traceback.
        print("local_model_digest_guard_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
