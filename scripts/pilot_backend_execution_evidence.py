#!/usr/bin/env python3
"""Independently distinguish full 64-shard Backend PASS from scoped CI bypass.

This is read-only GitHub Actions job metadata; it never dispatches tests,
changes CI triggers, authorizes a release, or copies raw job logs and secrets.
A successful aggregate 'Backend tests' job is NOT by itself full execution.
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
SHARD_RE = re.compile(r"Backend tests shard ([0-9]+)\Z")
SKIPPED_MATRIX_PLACEHOLDER = "Backend tests shard ${{ matrix.shard }}"
SHARD_COUNT = 64


class BackendEvidenceError(ValueError):
    """Safe static errors; never include GitHub API body or user metadata."""


def _valid_identifier(repo: str, sha: str, run_id: int) -> None:
    if (not REPO_RE.fullmatch(repo) or not SHA_RE.fullmatch(sha)
        or type(run_id) is not int or run_id <= 0):
        raise BackendEvidenceError("invalid repository, SHA or run identifier")


def _step(j: dict, name: str) -> str | None:
    steps = j.get("steps")
    if not isinstance(steps, list):
        raise BackendEvidenceError("backend aggregate steps unavailable")
    values = [x.get("conclusion") for x in steps
              if isinstance(x, dict) and x.get("name") == name]
    if len(values) != 1:
        raise BackendEvidenceError("backend step identity incomplete")
    return values[0]


def _success(job: dict) -> bool:
    return job.get("status") == "completed" and job.get("conclusion") == "success"


def evaluate(*, run: object, jobs: object, repo: str, sha: str,
             run_id: int) -> dict:
    _valid_identifier(repo, sha, run_id)
    if not isinstance(run, dict) or not isinstance(jobs, list):
        raise BackendEvidenceError("invalid Full Backend workflow metadata")
    attempt = run.get("run_attempt")
    expected_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    if (run.get("id") != run_id or run.get("name") != "Full Backend Pre-Merge"
        or run.get("head_sha") != sha or run.get("html_url") != expected_url
        or type(attempt) is not int or attempt < 1
        or run.get("status") != "completed" or run.get("conclusion") != "success"):
        raise BackendEvidenceError("Full Backend exact-head workflow not complete")
    classified, backend, shards = [], [], []
    for job in jobs:
        if not isinstance(job, dict):
            raise BackendEvidenceError("invalid Full Backend job metadata")
        if (job.get("run_id") != run_id
            or job.get("run_attempt") != attempt
            or type(job.get("id")) is not int or job["id"] <= 0
            or not isinstance(job.get("name"), str)
            or job.get("status") != "completed"):
            raise BackendEvidenceError("Full Backend job or attempt mismatch")
        name = job["name"]
        if name == "Classify backend changes":
            classified.append(job)
        elif name == "Backend tests":
            backend.append(job)
        elif SHARD_RE.fullmatch(name) or name == SKIPPED_MATRIX_PLACEHOLDER:
            shards.append(job)
        else:
            raise BackendEvidenceError("unrecognized Full Backend job identity")
    if len(classified) != 1 or len(backend) != 1 or not (
        _success(classified[0]) and _success(backend[0])
    ):
        raise BackendEvidenceError("Full Backend classifier or aggregate incomplete")
    full_step = _step(backend[0], "Verify full backend shards succeeded")
    skip_step = _step(backend[0], "Record workflow-only backend bypass")

    # This is the intentionally cheap case; do not represent it as 64/64.
    if (len(shards) == 1
        and shards[0]["name"] == SKIPPED_MATRIX_PLACEHOLDER
        and shards[0].get("conclusion") == "skipped"
        and full_step == "skipped" and skip_step == "success"):
        mode = "scoped_skip_verified"
        executed = 0
    else:
        seen: set[int] = set()
        for job in shards:
            match = SHARD_RE.fullmatch(job["name"])
            if not match or not _success(job):
                raise BackendEvidenceError("backend shard failed, skipped or invalid")
            shard = int(match.group(1))
            if shard in seen or shard >= SHARD_COUNT:
                raise BackendEvidenceError("duplicate or out-of-range backend shard")
            seen.add(shard)
        if (seen != set(range(SHARD_COUNT))
            or full_step != "success" or skip_step != "skipped"):
            raise BackendEvidenceError("full 64-shard execution not independently proven")
        mode = "full_64_shards_pass"
        executed = SHARD_COUNT
    return {
        "schema": "mcri-backend-execution-evidence-v1",
        "exact_head_sha": sha,
        "repository": repo,
        "workflow_run_id": run_id,
        "workflow_run_attempt": attempt,
        "workflow_run_url": expected_url,
        "observed_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "execution_mode": mode,
        "backend_shards_executed_and_passed": executed,
        "full_backend_64_shards_pass": mode == "full_64_shards_pass",
        "scope_bypass_explicitly_verified": mode == "scoped_skip_verified",
        "pilot_authorized": False,
    }


def _get(url: str, token: str | None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mcri-backend-execution-evidence-v1",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(url, headers=headers), timeout=15) as response:
            value = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        raise BackendEvidenceError("GitHub backend job metadata unavailable") from None
    if not isinstance(value, dict):
        raise BackendEvidenceError("malformed GitHub backend job metadata")
    return value


def fetch(*, repo: str, sha: str, run_id: int,
          token: str | None) -> tuple[dict, list[dict]]:
    _valid_identifier(repo, sha, run_id)
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    workflow = _get(url, token)
    # Use the exact attempt, not jobs from older or partial reruns.
    attempt = workflow.get("run_attempt")
    if type(attempt) is not int or attempt < 1:
        raise BackendEvidenceError("invalid Full Backend run attempt")
    jobs: list[dict] = []
    for page in range(1, 4):
        url = (f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
               f"/attempts/{attempt}/jobs?per_page=100&page={page}")
        response = _get(url, token)
        chunk = response.get("jobs")
        if not isinstance(chunk, list):
            raise BackendEvidenceError("invalid Full Backend jobs page")
        jobs.extend(chunk)
        if len(chunk) < 100:
            return workflow, jobs
    raise BackendEvidenceError("Full Backend jobs pagination limit reached")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-full", action="store_true",
                        help="Fail if the backend was intentionally scope-skipped")
    args = parser.parse_args(argv)
    try:
        run, jobs = fetch(repo=args.repo, sha=args.sha, run_id=args.run_id,
                          token=os.environ.get("GITHUB_TOKEN"))
        record = evaluate(run=run, jobs=jobs, repo=args.repo,
                          sha=args.sha, run_id=args.run_id)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except BackendEvidenceError as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: exclusive backend evidence output unavailable", file=sys.stderr)
        return 2
    if record["scope_bypass_explicitly_verified"]:
        print("BACKEND SCOPE BYPASS VERIFIED — 64-shard suite NOT executed.")
        if args.require_full:
            print("RELEASE BACKEND PROOF INCOMPLETE: full test suite required.")
            return 1
        return 0
    print("FULL BACKEND 64/64 SHARDS VERIFIED — NOT Pilot approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
