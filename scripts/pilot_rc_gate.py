#!/usr/bin/env python3
"""Fail-closed completeness gate for a *recorded* Pilot v1 release candidate.

This script verifies record structure, not the truth of external attestations.
Never treat PASS as a deployment authorization without independent operator review.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

SCHEMA = "mcri-pilot-rc-v1"
IMAGES = ("api", "web", "worker", "postgres", "clamav")
PROOFS = (
    "branch_protection_fail_closed",
    "real_sftp_governed_lifecycle",
    "fresh_host_deployment",
    "migration_and_preflight",
    "browser_operator_journey",
    "database_backup_verified",
    "matched_evidence_storage_recovery_point",
    "restore_drill",
    "rollback_drill",
    "monitoring_and_alert_ownership",
    "tenant_onboarding_and_offboarding",
    "backend_exact_head",
    "ci_exact_head",
    "postgres_concurrency_exact_head",
    "supply_chain_exact_head",
    "operational_performance_exact_head",
    "production_deployment_policy_exact_head",
)
SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
MIGRATION_RE = re.compile(r"[0-9]{4}_[a-z0-9_]+\Z")
DIGEST_RE = re.compile(r"[a-f0-9]{64}\Z")


def draft(sha: str) -> dict:
    """Every unobserved/unaudited field begins unset; no implied successes."""
    return {
        "schema": SCHEMA,
        "release_sha": sha,
        "alembic_head": "",
        "environment_id": "",
        "configuration_contract_ref": "",
        "known_limitations_ref": "",
        "images": {key: "" for key in IMAGES},
        "proofs": {
            key: {"result": "pending", "evidence_ref": "", "owner": "", "observed_at_utc": ""}
            for key in PROOFS
        },
    }


def _text(obj: dict, key: str, errors: list[str]) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key}: nonempty string required")
        return ""
    return value.strip()


def _timestamp(value: str) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo == timezone.utc and parsed.isoformat(timespec="seconds").endswith("+00:00")


def validate(record: object, expected_sha: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record: JSON object required"]
    expected_keys = {
        "schema", "release_sha", "alembic_head", "environment_id",
        "configuration_contract_ref", "known_limitations_ref", "images", "proofs",
    }
    if set(record) != expected_keys:
        errors.append("record: missing or unexpected top-level fields")
    if record.get("schema") != SCHEMA:
        errors.append("schema: unsupported release-candidate record version")
    if not SHA_RE.fullmatch(expected_sha):
        errors.append("expected SHA: must be a full lowercase Git commit ID")
    release_sha = _text(record, "release_sha", errors)
    if not SHA_RE.fullmatch(release_sha):
        errors.append("release_sha: full lowercase 40-character SHA required")
    if release_sha != expected_sha:
        errors.append("release_sha: does not match the independently supplied exact SHA")
    if not MIGRATION_RE.fullmatch(_text(record, "alembic_head", errors)):
        errors.append("alembic_head: expected a revision such as 0224_obs_refresh_recovery_anchor")
    for key in ("environment_id", "configuration_contract_ref", "known_limitations_ref"):
        _text(record, key, errors)

    images = record.get("images")
    if not isinstance(images, dict) or set(images) != set(IMAGES):
        errors.append("images: exact API/Web/Worker/Postgres/ClamAV image set required")
    else:
        for key in IMAGES:
            value = images[key]
            if not isinstance(value, str) or value.count("@sha256:") != 1:
                errors.append(f"images.{key}: immutable name@sha256:<64 hex> required")
                continue
            name, digest = value.split("@sha256:")
            if not name or "@" in name or any(c.isspace() for c in name) or not DIGEST_RE.fullmatch(digest):
                errors.append(f"images.{key}: invalid immutable digest reference")

    proofs = record.get("proofs")
    if not isinstance(proofs, dict) or set(proofs) != set(PROOFS):
        errors.append("proofs: required pilot-readiness gate set is incomplete or unexpected")
    else:
        for key in PROOFS:
            entry = proofs[key]
            if not isinstance(entry, dict) or set(entry) != {
                "result", "evidence_ref", "owner", "observed_at_utc"
            }:
                errors.append(f"proofs.{key}: invalid evidence entry")
                continue
            if entry["result"] != "pass":
                errors.append(f"proofs.{key}: independently verified 'pass' required")
            for field in ("evidence_ref", "owner"):
                if not isinstance(entry[field], str) or not entry[field].strip():
                    errors.append(f"proofs.{key}.{field}: required")
            if not _timestamp(entry["observed_at_utc"]):
                errors.append(f"proofs.{key}.observed_at_utc: UTC timestamp required")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    create = subs.add_parser("init", help="Write a NO-GO draft with blank evidence")
    create.add_argument("--output", required=True, type=Path)
    create.add_argument("--release-sha", help="Full release SHA; defaults to local git HEAD")
    check = subs.add_parser("check", help="Fail unless *all* evidence fields are complete")
    check.add_argument("record", type=Path)
    check.add_argument("--expected-sha", required=True, help="Externally established exact release SHA")
    args = parser.parse_args(argv)
    if args.command == "init":
        if args.release_sha:
            sha = args.release_sha
        else:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
            )
            sha = proc.stdout.strip() if proc.returncode == 0 else ""
        if not SHA_RE.fullmatch(sha):
            print("ERROR: full lowercase 40-character release SHA required", file=sys.stderr)
            return 2
        try:
            # 'x' means an old or newly-created record can never be overwritten silently.
            with args.output.open("x", encoding="utf-8") as fh:
                json.dump(draft(sha), fh, indent=2, sort_keys=True)
                fh.write("\n")
        except OSError as exc:
            print(f"ERROR: cannot create record: {type(exc).__name__}", file=sys.stderr)
            return 2
        print("NO-GO draft created. No runtime, security or pilot evidence was verified.")
        return 0
    try:
        with args.record.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"NO-GO: cannot read JSON record ({type(exc).__name__})", file=sys.stderr)
        return 1
    issues = validate(data, args.expected_sha)
    if issues:
        for issue in issues:
            print(f"NO-GO: {issue}", file=sys.stderr)
        return 1
    print("RECORD COMPLETE: independent verification of attached evidence is still required.")
    print("This result is NOT pilot authorization, a release approval, or proof of deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
