#!/usr/bin/env python3
"""Fail-closed human/operator evidence packet for real SFTP Pilot #652.

Never connects to SSH, database, GitHub or production hosts; does not validate
referenced artifacts, alter source permissions, admit Evidence or authorize GO.
Records bounded *opaque references* only, never credentials/paths/file bytes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

SCHEMA = "mcri-pilot-real-sftp-operator-acceptance-v1"
SHA = re.compile(r"[a-f0-9]{40}\Z")
REF = re.compile(r"(?:artifact|ticket|runbook|monitor)://[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}\Z")
ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,79}\Z")

POSITIVE = (
    "secret_reference_qualification",
    "destination_dns_policy",
    "pinned_host_key_verification",
    "ssh_authentication",
    "sftp_subsystem",
    "bounded_directory_listing",
    "exact_file_lstat",
    "opened_handle_consistency",
    "exact_content_read",
    "quarantine_checkpoint_custody",
    "canonical_initial_v1_admission",
    "metadata_only_due_observation",
    "human_authorized_nplus1_refresh",
    "replay_without_duplicate_document",
    "next_due_tick_unchanged",
    "read_only_remote_authority",
)
NEGATIVE = (
    "wrong_host_key_pin",
    "authentication_denied",
    "unsupported_weak_negotiation",
    "missing_remote_file",
    "traversal_rejected",
    "symlink_rejected",
    "file_replacement_or_metadata_drift",
    "content_size_exceeded",
    "connection_or_read_timeout",
    "disconnect_during_read",
)
ALL = POSITIVE + NEGATIVE
METADATA_REFS = (
    "approved_change_ref",
    "environment_ref",
    "server_implementation_version_ref",
    "enabled_algorithm_policy_ref",
    "approved_host_pin_ref",
    "runtime_configuration_bounds_ref",
    "exact_deployed_images_ref",
    "remote_read_only_permission_ref",
    "operator_independent_review_ref",
    "privacy_cleanup_review_ref",
)


class OperatorEvidenceError(ValueError):
    """Do not embed operator-controlled values in error messages."""


def draft(sha: str) -> dict:
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise OperatorEvidenceError("invalid exact release SHA")
    return {
        "schema": SCHEMA,
        "candidate_release_sha": sha,
        "operator_role": "",
        "independent_reviewer_role": "",
        "observed_at_utc": "",
        "references": {name: "" for name in METADATA_REFS},
        "positive": {
            name: {"outcome": "pending", "real_server_proof_ref": ""}
            for name in POSITIVE
        },
        "negative": {
            name: {
                "outcome": "pending",
                "real_server_proof_ref": "",
                "unreproducible_limitation_ref": "",
                "deterministic_ci_fallback_ref": "",
            }
            for name in NEGATIVE
        },
        "customer_credentials_used": False,
        "customer_files_used": False,
        "remote_mutation_authorized": False,
        "real_provider_go_authorized": False,
    }


def _ref(value: object) -> bool:
    return isinstance(value, str) and REF.fullmatch(value) is not None


def _time(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (parsed.tzinfo == timezone.utc
            and parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value)


def check(record: object, *, sha: str) -> dict:
    template = draft(sha)
    if not isinstance(record, dict) or set(record) != set(template):
        raise OperatorEvidenceError("operator packet structure mismatch")
    if record["schema"] != SCHEMA or record["candidate_release_sha"] != sha:
        raise OperatorEvidenceError("candidate release identity mismatch")
    primary = record["operator_role"]
    reviewer = record["independent_reviewer_role"]
    if (not isinstance(primary, str) or not ROLE.fullmatch(primary)
            or not isinstance(reviewer, str) or not ROLE.fullmatch(reviewer)
            or primary == reviewer):
        raise OperatorEvidenceError("independent role assignment incomplete")
    if not _time(record["observed_at_utc"]):
        raise OperatorEvidenceError("UTC observation time invalid")
    refs = record["references"]
    if not isinstance(refs, dict) or set(refs) != set(METADATA_REFS):
        raise OperatorEvidenceError("operator metadata evidence missing")
    if not all(_ref(x) for x in refs.values()):
        raise OperatorEvidenceError("invalid operator metadata reference")
    for field in (
        "customer_credentials_used", "customer_files_used",
        "remote_mutation_authorized", "real_provider_go_authorized",
    ):
        if record[field] is not False:
            raise OperatorEvidenceError("real-data, mutation or authorization boundary violated")

    plus = record["positive"]
    minus = record["negative"]
    if not isinstance(plus, dict) or set(plus) != set(POSITIVE):
        raise OperatorEvidenceError("real-provider positive case coverage incomplete")
    if not isinstance(minus, dict) or set(minus) != set(NEGATIVE):
        raise OperatorEvidenceError("real-provider negative case coverage incomplete")
    for case in POSITIVE:
        data = plus[case]
        if (not isinstance(data, dict)
                or set(data) != {"outcome", "real_server_proof_ref"}
                or data["outcome"] != "pass"
                or not _ref(data["real_server_proof_ref"])):
            raise OperatorEvidenceError("real-server positive case not proven")
    exceptions = 0
    for case in NEGATIVE:
        data = minus[case]
        if (not isinstance(data, dict)
                or set(data) != {
                    "outcome", "real_server_proof_ref",
                    "unreproducible_limitation_ref", "deterministic_ci_fallback_ref",
                }):
            raise OperatorEvidenceError("negative case data malformed")
        outcome = data["outcome"]
        if outcome == "pass":
            if (not _ref(data["real_server_proof_ref"])
                    or data["unreproducible_limitation_ref"] != ""
                    or data["deterministic_ci_fallback_ref"] != ""):
                raise OperatorEvidenceError("negative real-server proof missing")
        elif outcome == "unreproducible":
            if (data["real_server_proof_ref"] != ""
                    or not _ref(data["unreproducible_limitation_ref"])
                    or not _ref(data["deterministic_ci_fallback_ref"])):
                raise OperatorEvidenceError("unreproducible case fallback incomplete")
            exceptions += 1
        else:
            raise OperatorEvidenceError("negative real-server case incomplete")

    return {
        "schema": "mcri-pilot-sftp-operator-evidence-check-v1",
        "candidate_release_sha": sha,
        "positive_real_server_proofs": len(POSITIVE),
        "negative_real_server_proofs": len(NEGATIVE) - exceptions,
        "negative_with_deterministic_fallback": exceptions,
        "record_refs_structurally_complete": True,
        "actual_server_exercise_independently_verified": False,
        "credentials_and_data_compliance_independently_verified": False,
        "pilot_sftp_go_authorized": False,
        "pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    start = subs.add_parser("init")
    start.add_argument("--sha", required=True)
    start.add_argument("--output", required=True, type=Path)
    verify = subs.add_parser("check")
    verify.add_argument("record", type=Path)
    verify.add_argument("--sha", required=True)
    verify.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            record = draft(args.sha)
        else:
            if (not args.record.is_file() or args.record.is_symlink()
                    or args.record.stat().st_size > 64 * 1024):
                raise OperatorEvidenceError("operator record missing or oversized")
            with args.record.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
            record = check(raw, sha=args.sha)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except OperatorEvidenceError:
        print("NO-GO: real-provider operator acceptance evidence incomplete", file=sys.stderr)
        return 2
    except (OSError, ValueError, UnicodeError):
        print("NO-GO: operator acceptance record inaccessible", file=sys.stderr)
        return 2
    if args.command == "init":
        print("NO-GO: real-server acceptance template created with pending cases.")
    else:
        print("STRUCTURAL OPERATOR RECORD COMPLETE; independent verification remains required.")
        print("This is NOT real SFTP acceptance or permission for customer data; Pilot NO-GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
