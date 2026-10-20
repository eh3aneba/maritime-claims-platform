"""Bounded three-round synthetic localhost Ollama observation, opt-in only.

This development-only runner invokes exactly three rounds of the three
invented H&M source fixtures. No arbitrary input, customer Evidence, files,
stored raw output, external service, expert evaluation or pilot acceptance.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from app.ai.gateway.base import AIProvider
from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider
from scripts.pilot_local_ai_hm_fixture_matrix import scenario_names
from scripts.pilot_local_ai_hm_loopback_smoke import (
    MODEL, run_fixed_three_scenario_smoke,
)

_ROUNDS = 3
_ACCEPTED = "source_quotes_accepted_for_human_review"
_INCOMPLETE = "source_quotes_incomplete_for_review"
_REJECTED = "rejected"
_ALLOWED_STATUSES = frozenset({_ACCEPTED, _INCOMPLETE, _REJECTED})


def run_three_fixed_rounds(provider: AIProvider) -> dict[str, Any]:
    """Count repeat observations only; no source, prompt, or model text returned."""
    names = scenario_names()
    counts = {
        name: {
            "accepted_rounds": 0,
            "incomplete_rounds": 0,
            "rejected_rounds": 0,
            "min_elapsed_ms_observed": None,
            "max_elapsed_ms_observed": None,
        } for name in names
    }
    for _round in range(_ROUNDS):
        report = run_fixed_three_scenario_smoke(provider)
        rows = report["scenarios"]
        if (
            type(rows) is not list
            or len(rows) != len(names)
            or tuple(row.get("scenario") for row in rows if type(row) is dict) != names
        ):
            raise ValueError("invalid_synthetic_round_shape")
        for row in rows:
            name = row["scenario"]
            status = row["status"]
            elapsed = row["elapsed_ms_observed"]
            if (
                type(status) is not str or status not in _ALLOWED_STATUSES
                or type(elapsed) is not int or elapsed < 0
                or elapsed > 3600000
            ):
                raise ValueError("invalid_synthetic_round_value")
            summary = counts[name]
            key = {
                _ACCEPTED: "accepted_rounds",
                _INCOMPLETE: "incomplete_rounds",
                _REJECTED: "rejected_rounds",
            }[status]
            summary[key] += 1
            minimum = summary["min_elapsed_ms_observed"]
            maximum = summary["max_elapsed_ms_observed"]
            summary["min_elapsed_ms_observed"] = elapsed if minimum is None else min(minimum, elapsed)
            summary["max_elapsed_ms_observed"] = elapsed if maximum is None else max(maximum, elapsed)

    records = [{"scenario": name, **counts[name]} for name in names]
    return {
        "scope": "synthetic_development_only",
        "rounds_observed": _ROUNDS,
        "fixed_scenarios_per_round": len(names),
        "local_model_tag_unverified": MODEL,
        "model_digest_attested": False,
        "model_execution_independently_attested": False,
        "repeatability_proven": False,
        "expert_ground_truth_approved": False,
        "human_review_completed": False,
        "production_authorized": False,
        "pilot_accepted": False,
        "all_rounds_source_quotes_accepted_for_review": all(
            row["accepted_rounds"] == _ROUNDS for row in records
        ),
        "scenarios": records,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments != ["--run-fixed-synthetic-ollama-repeat-3"]:
        print("local_ai_explicit_synthetic_repeat_opt_in_required")
        return 2
    try:
        provider = OllamaLocalExperimentalProvider(model=MODEL, max_output_tokens=512)
        report = run_three_fixed_rounds(provider)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0 if report["all_rounds_source_quotes_accepted_for_review"] else 1
    except Exception:
        # Fail closed with one fixed error code; no dynamic exception detail.
        print("local_ai_synthetic_repeat_smoke_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
