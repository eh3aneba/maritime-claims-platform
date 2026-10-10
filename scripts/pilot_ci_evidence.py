#!/usr/bin/env python3
"""Observe exact-head GitHub Actions CI metadata for a Pilot v1 candidate.

Only verifies workflow metadata for *one supplied SHA*. It cannot certify a
deployed image, branch ruleset, restore, scanner, customer use, or Pilot GO.
Never logs the GitHub token, remote exception text, claim data or secrets.
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
SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
REQUIRED = {
    "backend_exact_head": "Full Backend Pre-Merge",
    "ci_exact_head": "Continuous Integration",
    "postgres_concurrency_exact_head": "PostgreSQL Concurrency Regression Suite",
    "supply_chain_exact_head": "Supply Chain Security",
    "operational_performance_exact_head": "Operational Performance Smoke",
    "production_deployment_policy_exact_head": "Production Deployment Policy",
}


class EvidenceError(RuntimeError):
    """A bounded fail-closed error; never includes underlying response text."""


def _run_key(run: dict) -> tuple[int, int]:
    return int(run["id"]), int(run.get("run_attempt", 1))


def evaluate(runs: object, *, repo: str, sha: str) -> dict:
    """Select latest exact-head attempt per named gate. Never infer missing PASS."""
    if not REPO_RE.fullmatch(repo) or not SHA_RE.fullmatch(sha):
        raise EvidenceError("invalid repository or exact commit SHA")
    if not isinstance(runs, list):
        raise EvidenceError("malformed GitHub Actions runs payload")

    matched: dict[str, dict] = {}
    names = set(REQUIRED.values())
    for run in runs:
        if not isinstance(run, dict):
            raise EvidenceError("malformed GitHub Actions run")
        if run.get("head_sha") != sha or run.get("name") not in names:
            continue
        # Fail closed on malformed matching runs rather than silently ignoring.
        if (
            type(run.get("id")) is not int
            or run["id"] <= 0
            or type(run.get("run_attempt", 1)) is not int
            or run.get("run_attempt", 1) < 1
        ):
            raise EvidenceError("invalid matching workflow run identifier")
        expected_url = (
            f"https://github.com/{repo}/actions/runs/{run['id']}"
        )
        if run.get("html_url") != expected_url:
            raise EvidenceError("unexpected matching workflow URL")
        name = run["name"]
        if name not in matched or _run_key(run) > _run_key(matched[name]):
            matched[name] = run

    gates = {}
    for key, workflow in REQUIRED.items():
        selected = matched.get(workflow)
        if selected is None:
            gates[key] = {
                "workflow": workflow, "outcome": "missing", "run_id": None,
                "run_attempt": None, "run_url": None,
            }
            continue
        success = (
            selected.get("status") == "completed"
            and selected.get("conclusion") == "success"
        )
        gates[key] = {
            "workflow": workflow, "outcome": "pass" if success else "not_pass",
            "run_id": selected["id"],
            "run_attempt": selected.get("run_attempt", 1),
            "run_url": selected["html_url"],
        }

    return {
        "schema": "mcri-pilot-ci-evidence-v1",
        "repository": repo,
        "exact_head_sha": sha,
        "observed_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ci_gates_complete": all(x["outcome"] == "pass" for x in gates.values()),
        "pilot_authorized": False,
        "verified_scope": "GitHub Actions workflow metadata only",
        "gates": gates,
    }


def fetch_runs(*, repo: str, sha: str, token: str | None) -> list[dict]:
    if not REPO_RE.fullmatch(repo) or not SHA_RE.fullmatch(sha):
        raise EvidenceError("invalid repository or exact commit SHA")
    all_runs: list[dict] = []
    for page in range(1, 11):
        url = (
            f"https://api.github.com/repos/{repo}/actions/runs"
            f"?head_sha={sha}&per_page=100&page={page}"
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mcri-pilot-ci-evidence-v1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            with urlopen(Request(url, headers=headers), timeout=15) as response:
                data = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError):
            raise EvidenceError(
                "GitHub Actions metadata could not be verified; CI evidence unavailable"
            ) from None
        if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
            raise EvidenceError("invalid GitHub Actions response structure")
        batch = data["workflow_runs"]
        all_runs.extend(batch)
        if len(batch) < 100:
            return all_runs
    raise EvidenceError("GitHub Actions result pagination limit exceeded")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repository")
    parser.add_argument("--sha", required=True, help="exact lowercase 40-hex commit")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        observed = fetch_runs(
            repo=args.repo, sha=args.sha, token=os.environ.get("GITHUB_TOKEN")
        )
        record = evaluate(observed, repo=args.repo, sha=args.sha)
        # Exclusive creation: failed/pending evidence cannot overwrite an
        # earlier signed-off record. No source-run payload is ever serialized.
        with args.output.open("x", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except EvidenceError as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create immutable CI observation output", file=sys.stderr)
        return 2
    if not record["ci_gates_complete"]:
        incomplete = [
            key for key, value in record["gates"].items()
            if value["outcome"] != "pass"
        ]
        print("CI INCOMPLETE for supplied exact SHA: " + ", ".join(incomplete))
        return 1
    print("EXACT-HEAD CI METADATA COMPLETE — NOT pilot or deployment approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
