#!/usr/bin/env python3
"""Write an exact-checkout-SHA, outcome-aware synthetic real-SFTP CI record.

Records only GitHub step outcomes, NOT independently verified operational
acceptance. The record is written on failed/skipped test paths as well, so a
failed workflow never leaves behind an apparently successful summary.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
SERVER_VERSION_RE = re.compile(r"[A-Za-z0-9.+:~_-]{1,64}\Z")
STEP_KEYS = (
    "postgres_schema",
    "openssh_setup",
    "live_runtime",
    "postgres_due_tick",
    "governed_nplus1",
    "initial_custody",
)
VALID_OUTCOMES = frozenset(("success", "failure", "cancelled", "skipped"))


class RecordError(ValueError):
    """Bounded error without raw environment, usernames, paths or secrets."""


def build_record(
    *,
    expected_sha: str,
    checked_out_sha: str,
    run_id: str,
    run_attempt: str,
    server_version: str,
    outcomes: dict[str, str],
) -> dict:
    if not SHA_RE.fullmatch(expected_sha) or not SHA_RE.fullmatch(checked_out_sha):
        raise RecordError("invalid exact Git commit identity")
    if expected_sha != checked_out_sha:
        raise RecordError("checked out SHA differs from candidate SHA")
    if not run_id.isdecimal() or int(run_id) < 1:
        raise RecordError("invalid GitHub run identity")
    if not run_attempt.isdecimal() or int(run_attempt) < 1:
        raise RecordError("invalid GitHub run attempt")
    if set(outcomes) != set(STEP_KEYS):
        raise RecordError("incomplete real SFTP CI step set")
    normalized = {
        key: (outcomes[key] if outcomes[key] in VALID_OUTCOMES else "not_reported")
        for key in STEP_KEYS
    }
    all_success = all(value == "success" for value in normalized.values())
    version = server_version if SERVER_VERSION_RE.fullmatch(server_version) else "not_observed"
    return {
        "schema_version": 2,
        "suite": "controlled-real-openssh-sftp-ci",
        "candidate_commit_sha": expected_sha,
        "tested_checkout_sha": checked_out_sha,
        "github_run_id": int(run_id),
        "github_run_attempt": int(run_attempt),
        "server_implementation": "OpenSSH",
        "observed_openssh_package_version": version,
        "ci_step_outcomes": normalized,
        "all_six_ci_steps_passed": all_success,
        "ci_result": "six_ci_steps_pass" if all_success else "incomplete_or_failed",
        "observation_level": "ci_step_outcome_only",
        "synthetic_runner_test_scope": True,
        "full_real_host_operational_proof": False,
        "production_scanner_and_store_proof": False,
        "independent_human_signoff": False,
        "customer_data_authorized": False,
        "pilot_go": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--checked-out-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--server-version", default="")
    args = parser.parse_args(argv)
    statuses = {
        key: os.environ.get("MCRI_SFTP_STEP_" + key.upper(), "")
        for key in STEP_KEYS
    }
    try:
        record = build_record(
            expected_sha=args.candidate_sha,
            checked_out_sha=args.checked_out_sha,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            server_version=args.server_version,
            outcomes=statuses,
        )
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(record, file, indent=2, sort_keys=True)
            file.write("\n")
    except RecordError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create exclusive real-SFTP CI evidence", file=sys.stderr)
        return 2
    if record["all_six_ci_steps_passed"]:
        print("All six synthetic CI steps reported success. NOT a Pilot GO.")
    else:
        print("INCOMPLETE/FAILED: CI steps not all successful. NOT a Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
