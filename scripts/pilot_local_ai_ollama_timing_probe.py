"""Manual, synthetic-only Ollama cold/warm timing observation; never an acceptance test.

Two identical, code-owned trivial prompts to fixed IPv4 loopback, with a bounded
one-minute warm model retention. Prints only finite counts and timings, never
model response, registry metadata, private user content, prompts, or exceptions.
"""
from __future__ import annotations

import http.client
import json
import sys
from time import monotonic_ns
from typing import Any, Callable

_MODEL = "qwen3:1.7b"
_HOST = "127.0.0.1"
_PORT = 11434
_TIMEOUT_SECONDS = 90
_MAX_RESPONSE_BYTES = 65_536
_TRIALS = 2
_FLAGS = ["--run-fixed-synthetic-ollama-timing-probe"]
_TIMING_KEYS = ("load_duration", "prompt_eval_duration", "eval_duration", "total_duration")


class LocalTimingProbeError(RuntimeError):
    """Internal fixed code only; no untrusted text is ever printed."""


def _one_fixed_probe(connection_factory: Callable[..., Any]) -> dict[str, int]:
    payload = {
        "model": _MODEL,
        "prompt": "Invented diagnostic only. Reply with OK.",
        "stream": False,
        "think": False,
        "keep_alive": "1m",
        "options": {"num_ctx": 4096, "num_predict": 16, "temperature": 0},
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    started = monotonic_ns()
    conn = connection_factory(_HOST, _PORT, timeout=_TIMEOUT_SECONDS)
    try:
        conn.request("POST", "/api/generate", body=body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
        })
        response = conn.getresponse()
        if response.status != 200:
            raise LocalTimingProbeError("local_runtime_unavailable")
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise LocalTimingProbeError("invalid_model_response")
    except LocalTimingProbeError:
        raise
    except (OSError, TimeoutError, http.client.HTTPException):
        raise LocalTimingProbeError("local_runtime_unavailable") from None
    finally:
        conn.close()
    elapsed_ms = max(0, (monotonic_ns() - started) // 1_000_000)
    try:
        result = json.loads(raw)
        if (type(result) is not dict or result.get("model") != _MODEL
                or result.get("done") is not True
                or type(result.get("response")) is not str):
            raise LocalTimingProbeError("invalid_model_response")
        timing = {}
        for key in _TIMING_KEYS:
            value = result.get(key)
            if type(value) is not int or not 0 <= value <= 1_000_000_000_000:
                raise LocalTimingProbeError("invalid_model_response")
            timing[key.replace("_duration", "_ms_observed")] = value // 1_000_000
        count = result.get("eval_count")
        if type(count) is not int or not 0 <= count <= 100_000:
            raise LocalTimingProbeError("invalid_model_response")
    except (ValueError, UnicodeDecodeError, TypeError):
        raise LocalTimingProbeError("invalid_model_response") from None
    return {"wall_ms_observed": elapsed_ms, "output_tokens_observed": count, **timing}


def fixed_two_trial_observation(
    connection_factory: Callable[..., Any] = http.client.HTTPConnection,
) -> dict[str, Any]:
    """No arbitrary text/paths, no model prose disclosure or persistence."""
    trials = []
    for i in range(1, _TRIALS + 1):
        try:
            row = {"trial": i, "status": "measured", **_one_fixed_probe(connection_factory)}
        except LocalTimingProbeError as exc:
            category = exc.args[0] if len(exc.args) == 1 else "invalid_model_response"
            if category not in {"local_runtime_unavailable", "invalid_model_response"}:
                category = "invalid_model_response"
            row = {"trial": i, "status": "rejected", "rejection_category": category}
        trials.append(row)
    return {
        "scope": "synthetic_localhost_trivial_prompt_timing_only",
        "expected_model_tag_unverified": _MODEL,
        "keep_alive_requested": "1m",
        "first_trial_known_cold": False,
        "second_trial_proven_warm": False,
        "ollama_native_timings_independently_attested": False,
        "model_artifact_independently_attested": False,
        "model_execution_independently_attested": False,
        "network_egress_isolation_verified": False,
        "expert_ground_truth_approved": False,
        "human_review_completed": False,
        "pilot_accepted": False,
        "all_trials_measured": all(row["status"] == "measured" for row in trials),
        "trials": trials,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != _FLAGS:
        print("local_ollama_timing_probe_explicit_opt_in_required")
        return 2
    try:
        result = fixed_two_trial_observation()
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["all_trials_measured"] else 1
    except Exception:
        print("local_ollama_timing_probe_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
