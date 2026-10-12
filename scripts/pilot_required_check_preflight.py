#!/usr/bin/env python3
"""Read-only, exact PR-head check-run name preflight before changing Protect main.

This is NOT GitHub ruleset enforcement proof, a branch protection mutation,
or a Pilot release authorization. No customer data, token, raw API payload or
unexpected check name is persisted/printed.
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

from pilot_ruleset_evidence import EXPECTED_CONTEXTS

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
MAX_PAGES = 10


class GatePreflightError(ValueError):
    """Fixed non-secret errors for CI and operator logs."""


def evaluate(pr: object, check_runs: object, *, repo: str, pr_number: int,
             exact_sha: str) -> dict:
    if (not REPO.fullmatch(repo) or not SHA.fullmatch(exact_sha)
            or type(pr_number) is not int or pr_number <= 0):
        raise GatePreflightError("invalid independently supplied repo/PR/SHA")
    if not isinstance(pr, dict):
        raise GatePreflightError("PR API response invalid")
    head = pr.get("head")
    base = pr.get("base")
    if (pr.get("number") != pr_number or pr.get("state") != "open"
            or not isinstance(head, dict) or not isinstance(base, dict)
            or head.get("sha") != exact_sha or base.get("ref") != "main"
            or not isinstance(base.get("repo"), dict)
            or base["repo"].get("full_name") != repo
            or not isinstance(head.get("repo"), dict)
            or head["repo"].get("full_name") != repo):
        raise GatePreflightError("PR is not the expected open same-repo main candidate")
    if not isinstance(check_runs, list):
        raise GatePreflightError("check run data unavailable")

    grouped: dict[str, list[dict]] = {name: [] for name in EXPECTED_CONTEXTS}
    for check in check_runs:
        if not isinstance(check, dict):
            raise GatePreflightError("malformed check run record")
        name = check.get("name")
        if name not in grouped:
            continue
        if (type(check.get("id")) is not int or check["id"] <= 0
                or check.get("head_sha") != exact_sha
                or not isinstance(check.get("app"), dict)
                or check["app"].get("slug") != "github-actions"):
            raise GatePreflightError("required check run identity invalid")
        grouped[name].append(check)

    results: dict[str, str] = {}
    ids: dict[str, int | None] = {}
    for name in sorted(EXPECTED_CONTEXTS):
        matches = grouped[name]
        if not matches:
            results[name] = "missing"
            ids[name] = None
        elif len(matches) != 1:
            # Duplicate names risk a ruleset binding the wrong app/workflow.
            results[name] = "ambiguous"
            ids[name] = None
        else:
            selected = matches[0]
            results[name] = (
                "pass" if selected.get("status") == "completed"
                and selected.get("conclusion") == "success" else "not_pass"
            )
            ids[name] = selected["id"]

    return {
        "schema": "mcri-protect-main-preactivation-check-names-v1",
        "repository": repo,
        "pr_number": pr_number,
        "pr_head_sha": exact_sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "required_context_count": len(EXPECTED_CONTEXTS),
        "exact_name_contexts_present": sum(
            outcome in {"pass", "not_pass"} for outcome in results.values()
        ),
        "all_required_checks_green": all(
            x == "pass" for x in results.values()
        ),
        "expected_checks": {
            name: {"outcome": results[name], "check_run_id": ids[name]}
            for name in sorted(EXPECTED_CONTEXTS)
        },
        "ruleset_mutated": False,
        "failing_required_check_enforcement_proven": False,
        "pilot_authorized": False,
    }


def _request_json(url: str, *, token: str | None) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mcri-protect-main-preactivation-v1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(url, headers=headers), timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        raise GatePreflightError("GitHub check metadata unavailable") from None


def fetch(*, repo: str, pr_number: int, sha: str,
          token: str | None) -> tuple[object, list[dict]]:
    if not REPO.fullmatch(repo) or not SHA.fullmatch(sha) or pr_number <= 0:
        raise GatePreflightError("invalid remote preflight request")
    root = f"https://api.github.com/repos/{repo}"
    pr = _request_json(f"{root}/pulls/{pr_number}", token=token)
    runs: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        payload = _request_json(
            f"{root}/commits/{sha}/check-runs?per_page=100&page={page}",
            token=token,
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("check_runs"), list
        ):
            raise GatePreflightError("invalid check-runs response structure")
        batch = payload["check_runs"]
        if any(not isinstance(entry, dict) for entry in batch):
            raise GatePreflightError("malformed check runs")
        runs.extend(batch)
        if len(batch) < 100:
            if payload.get("total_count") != len(runs):
                raise GatePreflightError("incomplete check-run pagination")
            break
    else:
        raise GatePreflightError("check-run pagination exceeds bounded limit")
    return pr, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        pr, runs = fetch(
            repo=args.repo, pr_number=args.pr, sha=args.sha,
            token=os.environ.get("GITHUB_TOKEN"),
        )
        result = evaluate(
            pr, runs, repo=args.repo, pr_number=args.pr,
            exact_sha=args.sha,
        )
        # Never overwrite an existing proof or print any API payload.
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except GatePreflightError:
        print("NO-GO: exact PR required check-run evidence incomplete", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create exclusive preactivation record", file=sys.stderr)
        return 2
    if not result["all_required_checks_green"]:
        print("NO-GO: some stable required context names are missing or not green.")
        return 1
    print("11/11 required context names observed green on exact open PR head.")
    print("Ruleset activation and failing-check enforcement remain UNPROVEN; Pilot NO-GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
