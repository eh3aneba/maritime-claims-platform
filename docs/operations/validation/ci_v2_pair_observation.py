"""Offline timing readback for one CI v2 feasibility pair, never an acceptance gate.

Inputs are bounded API snapshots from completed, first-attempt workflow_dispatch
runs. This module does not access GitHub, dispatch jobs, download artifacts,
change workflows, or infer test-node equivalence from successful jobs.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re

SHARDS = {f"Backend tests shard {n}" for n in range(64)}
GATE = "Backend tests"
PRODUCER = "Backend collection manifest"
CLASSIFIER = "Classify backend changes"
NARROW = "Backend changed-test verification"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _timestamp(value: object) -> datetime:
    _require(isinstance(value, str), "missing_timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid_timestamp") from None
    _require(result.tzinfo is not None, "timezone_required")
    return result


def _minutes(row: dict) -> float:
    elapsed = (_timestamp(row.get("completed_at")) - _timestamp(row.get("started_at"))).total_seconds() / 60
    _require(elapsed >= 0, "negative_duration")
    return elapsed


def summarize_run(snapshot: dict, expected_sha: str, *, candidate: bool) -> dict:
    _require(isinstance(snapshot, dict), "invalid_snapshot")
    _require(snapshot.get("head_sha") == expected_sha, "wrong_commit")
    _require(snapshot.get("event") == "workflow_dispatch", "wrong_event")
    _require(type(snapshot.get("run_attempt")) is int and snapshot["run_attempt"] == 1, "rerun_not_comparable")
    _require(snapshot.get("status") == "completed" and snapshot.get("conclusion") == "success", "run_not_successful")
    _require(type(snapshot.get("id")) is int, "invalid_run_id")
    _require(isinstance(snapshot.get("observed_competing_workflows"), list), "missing_isolation_observation")
    jobs = snapshot.get("jobs")
    _require(isinstance(jobs, list) and all(isinstance(j, dict) for j in jobs), "invalid_jobs")
    names = [j.get("name") for j in jobs]
    ids = [j.get("id") for j in jobs]
    _require(all(isinstance(n, str) for n in names), "invalid_job_name")
    _require(all(type(i) is int for i in ids), "invalid_job_id")
    _require(len(set(names)) == len(names) and len(set(ids)) == len(ids), "duplicate_job")
    expected = SHARDS | {CLASSIFIER, GATE, NARROW} | ({PRODUCER} if candidate else set())
    _require(set(names) == expected, "missing_or_unexpected_job")
    by_name = {j["name"]: j for j in jobs}
    for name, job in by_name.items():
        _require(job.get("status") == "completed", "unfinished_job")
        _require(job.get("conclusion") == ("skipped" if name == NARROW else "success"), "required_validation_not_executed")
        if name in SHARDS or name == PRODUCER:
            _require(job.get("labels") == ["ubuntu-latest"], "runner_label_mismatch")
    executed = [j for j in jobs if j["conclusion"] != "skipped"]
    start = _timestamp(snapshot.get("created_at"))
    for job in executed:
        _require(_timestamp(job.get("started_at")) >= start, "job_before_dispatch")
        _minutes(job)
    shard_jobs = [by_name[n] for n in sorted(SHARDS)]
    for job in shard_jobs + ([by_name[PRODUCER]] if candidate else []):
        steps = job.get("steps")
        _require(isinstance(steps, list) and all(isinstance(s, dict) for s in steps), "invalid_step_metadata")
        required_steps = ["Install backend dependencies"]
        if job["name"] == PRODUCER:
            required_steps += ["Collect exact-commit backend manifest", "Upload current-run collection manifest"]
        else:
            required_steps += ["Run backend test shard"]
            if candidate:
                required_steps += ["Download current-run collection manifest"]
        for name in required_steps:
            matches = [s for s in steps if s.get("name") == name]
            _require(len(matches) == 1 and matches[0].get("conclusion") == "success", "required_step_missing_or_duplicated")
            step = matches[0]
            _minutes(step)
            _require(_timestamp(step.get("started_at")) >= _timestamp(job["started_at"]), "step_before_job")
            _require(_timestamp(step.get("completed_at")) <= _timestamp(job["completed_at"]), "step_after_job")
    producer_minutes = _minutes(by_name[PRODUCER]) if candidate else 0.0
    shard_minutes = sum(_minutes(j) for j in shard_jobs)
    steps = [s for j in executed for s in j.get("steps", [])]
    _require(all(isinstance(s, dict) for s in steps), "invalid_step_metadata")
    # This combined step includes collection/selection AND pytest. Do not call
    # its duration collection-only cost or use it to establish a 90% saving.
    combined = [s for s in steps if s.get("name") == "Run backend test shard"]
    _require(len(combined) == 64 and all(s.get("conclusion") == "success" for s in combined), "missing_shard_execution_step")
    installs = [s for s in steps if s.get("name") == "Install backend dependencies"]
    _require(len(installs) == (65 if candidate else 64) and all(s.get("conclusion") == "success" for s in installs), "missing_dependency_install")
    return {
        "run_id": snapshot["id"], "head_sha": expected_sha, "all_64_shards_successful": True,
        "dispatch_to_last_job_wall_minutes": (max(_timestamp(j["completed_at"]) for j in executed) - start).total_seconds() / 60,
        "shard_runner_minutes": shard_minutes, "producer_runner_minutes": producer_minutes,
        "backend_runner_minutes_including_producer": shard_minutes + producer_minutes,
        "all_executed_job_runner_minutes": sum(_minutes(j) for j in executed),
        "dependency_install_step_minutes": sum(_minutes(s) for s in installs),
        "combined_selection_and_test_step_minutes": sum(_minutes(s) for s in combined),
        "producer_collection_and_manifest_step_minutes": sum(_minutes(s) for s in steps if s.get("name") == "Collect exact-commit backend manifest"),
        "artifact_transfer_step_minutes": sum(_minutes(s) for s in steps if s.get("name") in {"Upload current-run collection manifest", "Download current-run collection manifest"}),
        "dispatch_to_first_shard_start_minutes": (min(_timestamp(j["started_at"]) for j in shard_jobs) - start).total_seconds() / 60,
        "dispatch_to_producer_completion_minutes": (_timestamp(by_name[PRODUCER]["completed_at"]) - start).total_seconds() / 60 if candidate else None,
        "shard_start_spread_minutes": (max(_timestamp(j["started_at"]) for j in shard_jobs) - min(_timestamp(j["started_at"]) for j in shard_jobs)).total_seconds() / 60,
        "observed_competing_workflows": snapshot.get("observed_competing_workflows", []),
    }


def compare_pair(preflight: dict, baseline: dict, candidate: dict) -> dict:
    _require(isinstance(preflight, dict), "invalid_preflight")
    for key in ("baseline_sha", "candidate_sha", "app_tree", "candidate_app_tree"):
        _require(isinstance(preflight.get(key), str) and re.fullmatch(r"[0-9a-f]{40}", preflight[key]) is not None, "invalid_source_identity")
    _require(preflight.get("matched_application_tests_locks") is True and preflight.get("classifier_unchanged") is True, "unmatched_source_contract")
    _require(preflight["app_tree"] == preflight["candidate_app_tree"], "application_tree_mismatch")
    b = summarize_run(baseline, preflight["baseline_sha"], candidate=False)
    c = summarize_run(candidate, preflight["candidate_sha"], candidate=True)
    _require(b["run_id"] != c["run_id"], "same_run_substituted")
    _require(_timestamp(candidate["created_at"]) >= max(_timestamp(j["completed_at"]) for j in baseline["jobs"] if j["conclusion"] != "skipped"), "overlapping_pair")
    _require(b["dispatch_to_last_job_wall_minutes"] > 0 and b["backend_runner_minutes_including_producer"] > 0, "invalid_baseline_denominator")
    return {
        "measurement": "single sequential matched-source feasibility pair",
        "baseline": b, "candidate": c,
        "observed_wall_change_percent": (c["dispatch_to_last_job_wall_minutes"] / b["dispatch_to_last_job_wall_minutes"] - 1) * 100,
        "observed_backend_cost_change_percent": (c["backend_runner_minutes_including_producer"] / b["backend_runner_minutes_including_producer"] - 1) * 100,
        "isolation_observed": not (b["observed_competing_workflows"] or c["observed_competing_workflows"]),
        "paired_samples": 1, "median_or_p95_established": False,
        "exact_collected_node_ids_and_outcomes_verified": False,
        "collection_only_cost_measured": False, "cache_and_runner_image_parity_verified": False,
        "acceptance_established": False,
        "limits": ["Five completed pairs are required by the proposal; this is one feasibility sample.",
                   "Successful jobs and equal source trees do not independently verify node IDs, skip/xfail outcomes, or artifact contents.",
                   "Detailed logs are unavailable; do not infer collection-only savings or cache parity from combined step timings.",
                   "Failed/cancelled/retried attempts must remain separate; this analyzer refuses to summarize them as successful pairs.",
                   "Elapsed job minutes are not a billing statement. No merge, policy change or pilot acceptance is implied."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preflight", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        inputs = [json.loads(p.read_text()) for p in (args.preflight, args.baseline, args.candidate)]
        result = compare_pair(*inputs)
    except (ValueError, OSError, TypeError, KeyError):
        print("ci_pair_observation_failed_closed")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
