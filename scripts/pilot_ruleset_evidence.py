#!/usr/bin/env python3
"""Read-only, fail-closed GitHub Protect main required-gate metadata proof.

Only records an API configuration snapshot for ONE repository. It neither
changes a ruleset nor proves a deliberately failing check was blocked.
It never prints HTTP response bodies, tokens or raw exception messages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
RULESET_NAME = "Protect main"
EXPECTED_CONTEXTS = frozenset((
    "Backend tests",
    "PostgreSQL migration chain",
    "Frontend typecheck and build",
    "Docker Compose validation",
    "Scoped CI gate",
    "PostgreSQL concurrency gate",
    "Operational performance gate",
    "Production dependency audit and SBOM",
    "Secret history scan",
    "Container image vulnerability scan",
    "Production environment policy",
))


class EvidenceError(RuntimeError):
    """Safe, bounded error without raw server data."""


def evaluate(listed: object, detail: object, *, repo: str) -> dict:
    if not REPO_RE.fullmatch(repo):
        raise EvidenceError("invalid repository name")
    if not isinstance(listed, list) or not isinstance(detail, dict):
        raise EvidenceError("malformed ruleset API data")

    matches = [item for item in listed if isinstance(item, dict)
               and item.get("name") == RULESET_NAME
               and item.get("source") == repo
               and item.get("source_type") == "Repository"]
    if len(matches) != 1 or type(matches[0].get("id")) is not int:
        raise EvidenceError("unique repository Protect main ruleset not found")
    listed_id = matches[0]["id"]
    if detail.get("id") != listed_id or detail.get("name") != RULESET_NAME:
        raise EvidenceError("ruleset detail/list identity mismatch")
    rules = detail.get("rules")
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise EvidenceError("malformed ruleset rules")
    status_rules = [r for r in rules if r.get("type") == "required_status_checks"]
    pull_rules = [r for r in rules if r.get("type") == "pull_request"]
    if len(status_rules) != 1 or len(pull_rules) != 1:
        raise EvidenceError("required status/PR protection rule missing or ambiguous")

    checks = status_rules[0].get("parameters", {})
    prs = pull_rules[0].get("parameters", {})
    if not isinstance(checks, dict) or not isinstance(prs, dict):
        raise EvidenceError("invalid protection rule parameters")
    required = checks.get("required_status_checks")
    if not isinstance(required, list) or not all(
        isinstance(item, dict) and isinstance(item.get("context"), str)
        for item in required
    ):
        raise EvidenceError("invalid required check context records")
    contexts = [item["context"] for item in required]
    actual = set(contexts)
    conditions = detail.get("conditions", {})
    if not isinstance(conditions, dict):
        raise EvidenceError("malformed ruleset conditions")
    refs = conditions.get("ref_name", {})
    if not isinstance(refs, dict):
        raise EvidenceError("malformed ref conditions")
    bypass = detail.get("bypass_actors")
    if not isinstance(bypass, list):
        raise EvidenceError("missing bypass actor readback")

    properties = {
        "active": detail.get("enforcement") == "active",
        "repository_owned": detail.get("source") == repo
        and detail.get("source_type") == "Repository",
        "protects_default_branch": (
            refs.get("include") == ["~DEFAULT_BRANCH"]
            and refs.get("exclude") == []
            and detail.get("target") == "branch"
        ),
        "strict_up_to_date_checks": checks.get("strict_required_status_checks_policy") is True,
        "no_bypass_actors": len(bypass) == 0,
        "squash_only": prs.get("allowed_merge_methods") == ["squash"],
        "thread_resolution_required": prs.get("required_review_thread_resolution") is True,
        "linear_history": any(r.get("type") == "required_linear_history" for r in rules),
        "deletion_protected": any(r.get("type") == "deletion" for r in rules),
        "non_fast_forward_protected": any(r.get("type") == "non_fast_forward" for r in rules),
        "unique_contexts": len(contexts) == len(actual),
    }
    missing = sorted(EXPECTED_CONTEXTS - actual)
    unexpected_count = len(actual - EXPECTED_CONTEXTS)
    ready = not missing and unexpected_count == 0 and all(properties.values())
    return {
        "schema": "mcri-pilot-protect-main-readback-v1",
        "repository": repo,
        "ruleset_id": listed_id,
        "ruleset_name": RULESET_NAME,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "required_context_count": len(contexts),
        "expected_context_count": len(EXPECTED_CONTEXTS),
        "missing_expected_contexts": missing,
        "unexpected_context_count": unexpected_count,
        "safety_properties": properties,
        "metadata_complete": ready,
        "failing_check_enforcement_proven": False,
        "pilot_authorized": False,
    }


def _read_json(url: str, *, token: str | None) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mcri-protect-main-readback-v1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(url, headers=headers), timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        raise EvidenceError("GitHub ruleset readback unavailable") from None


def fetch(*, repo: str, token: str | None) -> tuple[object, object]:
    if not REPO_RE.fullmatch(repo):
        raise EvidenceError("invalid repository name")
    base = f"https://api.github.com/repos/{repo}/rulesets"
    listed = _read_json(base, token=token)
    if not isinstance(listed, list):
        raise EvidenceError("invalid ruleset list")
    matches = [item for item in listed if isinstance(item, dict)
               and item.get("name") == RULESET_NAME and item.get("source") == repo
               and item.get("source_type") == "Repository"]
    if len(matches) != 1 or type(matches[0].get("id")) is not int:
        raise EvidenceError("unique repository Protect main ruleset not found")
    detail = _read_json(base + "/" + str(matches[0]["id"]), token=token)
    return listed, detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub owner/repo")
    parser.add_argument("--output", required=True, type=Path,
                        help="New local JSON evidence path (exclusive create)")
    args = parser.parse_args(argv)
    try:
        listed, detail = fetch(repo=args.repo, token=os.environ.get("GITHUB_TOKEN"))
        evidence = evaluate(listed, detail, repo=args.repo)
        with args.output.open("x", encoding="utf-8") as fh:
            json.dump(evidence, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except EvidenceError as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create exclusive readback record", file=sys.stderr)
        return 2
    if not evidence["metadata_complete"]:
        print("NO-GO: active Protect main ruleset is missing required safeguards.")
        print("Missing contexts: " + ", ".join(evidence["missing_expected_contexts"]))
        return 1
    print("PROTECT MAIN METADATA COMPLETE; failing-check enforcement still unproven.")
    print("This is not an operational Pilot GO or release authorization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
