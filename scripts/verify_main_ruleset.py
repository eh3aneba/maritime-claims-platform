#!/usr/bin/env python3
"""Fail-closed readback verifier for the repository's Protect main ruleset.

The verifier performs read-only validation. It never mutates repository settings.
It can read a live GitHub ruleset or an exported JSON file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_REPOSITORY = "eh3aneba/maritime-claims-platform"
DEFAULT_RULESET_ID = 20842512

REQUIRED_CONTEXTS = {
    "Backend tests",
    "PostgreSQL migration chain",
    "Frontend typecheck and build",
    "Docker Compose validation",
    "Scoped CI gate",
    "PostgreSQL concurrency gate",
    "Operational performance gate",
    "Production environment policy",
    "Production dependency audit and SBOM",
    "Secret history scan",
    "Container image vulnerability scan",
}


class VerificationError(RuntimeError):
    """Raised when ruleset state is missing or weaker than the required policy."""


def _load_live_ruleset(repository: str, ruleset_id: int) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{repository}/rulesets/{ruleset_id}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mcri-ruleset-verifier",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise VerificationError(
            f"GitHub ruleset readback failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise VerificationError("GitHub ruleset readback failed") from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise VerificationError("GitHub ruleset response was not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise VerificationError("GitHub ruleset response was not a JSON object")
    return parsed


def _load_file(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Could not load ruleset JSON from {path}") from exc

    if not isinstance(parsed, dict):
        raise VerificationError("Ruleset JSON file must contain one JSON object")
    return parsed


def _single_rule(ruleset: dict[str, Any], rule_type: str) -> dict[str, Any]:
    matches = [
        rule
        for rule in ruleset.get("rules", [])
        if isinstance(rule, dict) and rule.get("type") == rule_type
    ]
    if len(matches) != 1:
        raise VerificationError(
            f"Expected exactly one {rule_type!r} rule; found {len(matches)}"
        )
    return matches[0]


def verify_ruleset(ruleset: dict[str, Any]) -> list[str]:
    """Return the sorted required contexts after all policy checks pass."""

    failures: list[str] = []

    if ruleset.get("name") != "Protect main":
        failures.append("ruleset name must be 'Protect main'")
    if ruleset.get("enforcement") != "active":
        failures.append("ruleset enforcement must be active")
    if ruleset.get("bypass_actors") not in ([], None):
        failures.append("bypass_actors must be empty")

    conditions = ruleset.get("conditions")
    include = (
        conditions.get("ref_name", {}).get("include", [])
        if isinstance(conditions, dict)
        else []
    )
    if "~DEFAULT_BRANCH" not in include:
        failures.append("ruleset must target the default branch")

    try:
        pull_request = _single_rule(ruleset, "pull_request")
        pull_params = pull_request.get("parameters", {})
        if pull_params.get("required_review_thread_resolution") is not True:
            failures.append("review-thread resolution must remain required")
        allowed_merge_methods = pull_params.get("allowed_merge_methods")
        if allowed_merge_methods != ["squash"]:
            failures.append("allowed merge methods must remain squash-only")
    except VerificationError as exc:
        failures.append(str(exc))

    try:
        status_rule = _single_rule(ruleset, "required_status_checks")
        status_params = status_rule.get("parameters", {})
        if status_params.get("strict_required_status_checks_policy") is not True:
            failures.append("required status checks must remain strict/up-to-date")

        raw_checks = status_params.get("required_status_checks", [])
        actual_contexts = {
            item.get("context")
            for item in raw_checks
            if isinstance(item, dict) and isinstance(item.get("context"), str)
        }
        missing = sorted(REQUIRED_CONTEXTS - actual_contexts)
        if missing:
            failures.append("missing required contexts: " + ", ".join(missing))
    except VerificationError as exc:
        failures.append(str(exc))
        actual_contexts = set()

    rule_types = {
        rule.get("type")
        for rule in ruleset.get("rules", [])
        if isinstance(rule, dict)
    }
    if "required_linear_history" not in rule_types:
        failures.append("required_linear_history rule is missing")
    if "deletion" not in rule_types:
        failures.append("branch deletion protection is missing")
    if "non_fast_forward" not in rule_types:
        failures.append("non-fast-forward protection is missing")

    if failures:
        raise VerificationError("; ".join(failures))

    return sorted(actual_contexts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the MCRI Protect main ruleset by readback."
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--ruleset-id", type=int, default=DEFAULT_RULESET_ID)
    parser.add_argument(
        "--input",
        type=Path,
        help="Read an exported ruleset JSON file instead of GitHub.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ruleset = (
            _load_file(args.input)
            if args.input is not None
            else _load_live_ruleset(args.repository, args.ruleset_id)
        )
        contexts = verify_ruleset(ruleset)
    except VerificationError as exc:
        print(f"RULESET VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1

    print("RULESET VERIFICATION PASSED")
    for context in contexts:
        print(f"- {context}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
