#!/usr/bin/env python3
"""Read-only red/blocked -> green/clean observation for Pilot issue #461.

This observes live GitHub metadata on *two separately created commits* of one
disposable synthetic-only PR, after an Admin independently activates 11/11
required checks. No settings change or merge is attempted. State alone is
NOT proof of a refused merge action or of causal enforcement. Never Pilot GO.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from pilot_required_check_preflight import (
    SHA, GatePreflightError, evaluate as evaluate_checks, fetch as fetch_checks,
)
from pilot_ruleset_evidence import (
    EXPECTED_CONTEXTS, EvidenceError, evaluate as evaluate_ruleset,
    fetch as fetch_ruleset,
)
from pilot_ruleset_admin_activation import REPO, RULESET_ID, ORIGINAL

NEW_CONTEXTS = frozenset(EXPECTED_CONTEXTS - ORIGINAL)
SCHEMA = "mcri-pilot-required-check-negative-observation-v1"


class NegativeObservationError(ValueError):
    """Error text intentionally excludes all untrusted GitHub API fields."""


def evaluate(*, listed: object, ruleset: object, pr: object, runs: object,
             pr_number: int, sha: str, target: str, phase: str) -> dict:
    if (phase not in {"red", "green"} or target not in NEW_CONTEXTS
            or not SHA.fullmatch(sha)):
        raise NegativeObservationError("invalid phase, target or SHA")
    try:
        protection = evaluate_ruleset(listed, ruleset, repo=REPO)
        checks = evaluate_checks(
            pr, runs, repo=REPO, pr_number=pr_number, exact_sha=sha,
        )
    except (EvidenceError, GatePreflightError):
        raise NegativeObservationError("ruleset or exact-head check evidence incomplete") from None
    if (not protection["metadata_complete"]
            or protection["ruleset_id"] != RULESET_ID
            or protection["required_context_count"] != 11
            or not isinstance(pr, dict)
            or pr.get("draft") is not False
            or pr.get("mergeable") is not True
            or pr.get("mergeable_state") != ("blocked" if phase == "red" else "clean")
            or not isinstance(pr.get("base"), dict)
            or not SHA.fullmatch(pr["base"].get("sha", ""))
            or not isinstance(pr.get("head"), dict)
            or not isinstance(pr["head"].get("ref"), str)
            or not pr["head"]["ref"]):
        raise NegativeObservationError("live 11/11 policy or PR merge-state boundary missing")
    statuses = checks["expected_checks"]
    if set(statuses) != EXPECTED_CONTEXTS:
        raise NegativeObservationError("expected exact stable check set missing")
    for context in EXPECTED_CONTEXTS:
        outcome = statuses[context]["outcome"]
        if outcome != ("not_pass" if phase == "red" and context == target else "pass"):
            raise NegativeObservationError("required check status does not match phase")
    selected = [
        x for x in runs
        if isinstance(x, dict) and x.get("name") == target
    ]
    if len(selected) != 1 or (
        selected[0].get("conclusion")
        != ("failure" if phase == "red" else "success")
    ) or selected[0].get("status") != "completed":
        raise NegativeObservationError("target check does not have exact red/green result")
    if any(
        isinstance(x, dict) and x.get("name") not in EXPECTED_CONTEXTS
        and x.get("conclusion") in {
            "failure", "timed_out", "cancelled", "action_required",
        }
        for x in runs
    ):
        raise NegativeObservationError("another failing check could explain blocked merge")
    return {
        "schema": SCHEMA,
        "repository": REPO,
        "ruleset_id": RULESET_ID,
        "pr_number": pr_number,
        "target_required_check": target,
        "phase": phase,
        "pr_head_sha": sha,
        "pr_base_sha": pr["base"]["sha"],
        "pr_head_ref": pr["head"]["ref"],
        "ruleset_updated_at": ruleset.get("updated_at"),
        "target_check_run_id": selected[0]["id"],
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "eleven_required_contexts_observed": True,
        "red_required_check_and_blocked_metadata_observed": phase == "red",
        "green_required_checks_and_clean_metadata_observed": phase == "green",
        "github_merge_api_refusal_actually_observed": False,
        "enforcement_causality_independently_verified": False,
        "pilot_authorized": False,
    }


def compare(red: object, green: object) -> dict:
    if not isinstance(red, dict) or not isinstance(green, dict):
        raise NegativeObservationError("red/green records malformed")
    fields = set(evaluate_schema_keys())
    if set(red) != fields or set(green) != fields:
        raise NegativeObservationError("unexpected observation record structure")
    for record, phase in ((red, "red"), (green, "green")):
        if (record["schema"] != SCHEMA or record["repository"] != REPO
                or record["ruleset_id"] != RULESET_ID
                or record["phase"] != phase
                or record["target_required_check"] not in NEW_CONTEXTS
                or not isinstance(record["pr_number"], int)
                or record["pr_number"] < 1
                or not isinstance(record["target_check_run_id"], int)
                or record["target_check_run_id"] < 1
                or not isinstance(record["pr_head_ref"], str)
                or not record["pr_head_ref"]
                or not SHA.fullmatch(record["pr_head_sha"])
                or not SHA.fullmatch(record["pr_base_sha"])
                or record["eleven_required_contexts_observed"] is not True
                or record["github_merge_api_refusal_actually_observed"] is not False
                or record["enforcement_causality_independently_verified"] is not False
                or record["pilot_authorized"] is not False
                or record["red_required_check_and_blocked_metadata_observed"] is not (phase == "red")
                or record["green_required_checks_and_clean_metadata_observed"] is not (phase == "green")):
            raise NegativeObservationError("required observation record incomplete")
    consistent = (
        red["pr_number"] == green["pr_number"]
        and red["pr_head_ref"] == green["pr_head_ref"]
        and red["pr_base_sha"] == green["pr_base_sha"]
        and red["target_required_check"] == green["target_required_check"]
        and red["ruleset_updated_at"] == green["ruleset_updated_at"]
        and red["pr_head_sha"] != green["pr_head_sha"]
        and red["target_check_run_id"] != green["target_check_run_id"]
        and isinstance(red["observed_at_utc"], str)
        and isinstance(green["observed_at_utc"], str)
        and red["observed_at_utc"] < green["observed_at_utc"]
    )
    if not consistent:
        raise NegativeObservationError("red-to-green observation identity/order mismatch")
    return {
        "schema": "mcri-pilot-branch-protection-paired-observation-v1",
        "ruleset_id": RULESET_ID,
        "pr_number": red["pr_number"],
        "target_required_check": red["target_required_check"],
        "red_blocked_and_green_clean_metadata_pair": True,
        "actual_required_check_merge_refusal_independently_verified": False,
        "independent_operator_review_still_required": True,
        "pilot_authorized": False,
    }


def evaluate_schema_keys() -> tuple[str, ...]:
    return (
        "schema", "repository", "ruleset_id", "pr_number",
        "target_required_check", "phase", "pr_head_sha", "pr_base_sha",
        "pr_head_ref", "ruleset_updated_at", "target_check_run_id",
        "observed_at_utc", "eleven_required_contexts_observed",
        "red_required_check_and_blocked_metadata_observed",
        "green_required_checks_and_clean_metadata_observed",
        "github_merge_api_refusal_actually_observed",
        "enforcement_causality_independently_verified", "pilot_authorized",
    )


def _json_file(path: Path) -> object:
    if (not path.is_file() or path.is_symlink()
            or path.stat().st_size > 32 * 1024):
        raise NegativeObservationError("private proof record unavailable")
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, ValueError):
        raise NegativeObservationError("private proof record invalid") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="command", required=True)
    capture = modes.add_parser("capture")
    capture.add_argument("--pr", type=int, required=True)
    capture.add_argument("--sha", required=True)
    capture.add_argument("--target-check", required=True, choices=sorted(NEW_CONTEXTS))
    capture.add_argument("--phase", required=True, choices=["red", "green"])
    capture.add_argument("--output", required=True, type=Path)
    paired = modes.add_parser("compare")
    paired.add_argument("--red", required=True, type=Path)
    paired.add_argument("--green", required=True, type=Path)
    paired.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        print("NO-GO: observation output already exists", file=sys.stderr)
        return 2
    try:
        if args.command == "capture":
            pr, runs = fetch_checks(
                repo=REPO, pr_number=args.pr, sha=args.sha,
                token=None,  # Public repo: deliberately never needs a credential.
            )
            listed, ruleset = fetch_ruleset(repo=REPO, token=None)
            result = evaluate(
                listed=listed, ruleset=ruleset, pr=pr, runs=runs,
                pr_number=args.pr, sha=args.sha,
                target=args.target_check, phase=args.phase,
            )
        else:
            result = compare(_json_file(args.red), _json_file(args.green))
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (NegativeObservationError, GatePreflightError, EvidenceError, OSError):
        print("NO-GO: independent enforcement observation incomplete", file=sys.stderr)
        return 2
    print("READ-ONLY red/green metadata recorded; true blocked-merge causality remains unproven.")
    print("No Pilot GO; accountable GitHub Admin must independently review the enforcement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
