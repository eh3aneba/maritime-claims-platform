#!/usr/bin/env python3
"""Offline privacy-safe eight-finding historical secret disposition record gate.

Only validates an operator-entered private evidence *index*. Never reads a
credential, Git history, secret manager, GitHub Actions, or customer data; never
performs rotation, grants an exception or authorizes Pilot/customer traffic.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

SCHEMA = "mcri-pilot-historical-secret-disposition-v1"
SHA = re.compile(r"[a-f0-9]{40}\Z")
REF = re.compile(r"(?:artifact|ticket|runbook)://[A-Za-z0-9._:/-]{3,200}\Z")
ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,79}\Z")
MAX_RECORD_BYTES = 1_048_576

# Only public path, source commit and line metadata from #764, never values,
# matching text, token hashes, credential fingerprints or scan payloads.
FINDINGS = {
    "F01": (".github/workflows/production-deployment-policy.yml", "90c75c88c2ea", 41),
    "F02": ("apps/api/tests/test_mt_orion_end_to_end_pilot.py", "5eedba6e7a9f", 56),
    "F03": ("apps/api/tests/test_maintenance_workshop_intelligence.py", "92763d09363d", 21),
    "F04": ("apps/api/tests/test_financial_intelligence.py", "d0554233a3e3", 16),
    "F05": ("apps/api/tests/test_chronology_engine.py", "d60e2f343954", 20),
    "F06": ("apps/api/tests/test_claims_api.py", "9c4e465b9fa2", 14),
    "F07": ("apps/api/tests/test_ce_report_intelligence.py", "2b431ca8a3d1", 23),
    "F08": ("apps/api/tests/test_auth_and_tenant_security.py", "b03f9b607be7", 18),
}
CLASSIFICATIONS = frozenset(("confirmed_synthetic_never_issued", "actual_or_reused"))


class DispositionError(ValueError):
    """Never include record-controlled values in this exception."""


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if instant.tzinfo != timezone.utc or instant.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        return None
    return instant


def _ref(value: object) -> bool:
    return isinstance(value, str) and REF.fullmatch(value) is not None


def _role(value: object) -> bool:
    return isinstance(value, str) and ROLE.fullmatch(value) is not None


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise DispositionError("duplicate private evidence record key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise DispositionError("nonstandard private evidence JSON constant")


def _read_private(path: Path) -> object:
    if path.is_symlink():
        raise DispositionError("evidence record not a private regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise DispositionError("evidence record not a private regular file")
        if os.name == "posix" and stat.S_IMODE(before.st_mode) & 0o077:
            raise DispositionError("evidence record permissions not private")
        if before.st_size > MAX_RECORD_BYTES:
            raise DispositionError("evidence record too large")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read(MAX_RECORD_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(payload) > MAX_RECORD_BYTES:
            raise DispositionError("evidence record too large")
        # Even valid JSON is unsafe if its evidence file changed or the
        # bounded read did not match the originally inspected byte count.
        if (
            (before.st_dev, before.st_ino, before.st_mode, before.st_size,
             before.st_mtime_ns, before.st_ctime_ns)
            !=
            (after.st_dev, after.st_ino, after.st_mode, after.st_size,
             after.st_mtime_ns, after.st_ctime_ns)
            or len(payload) != before.st_size
        ):
            raise DispositionError("evidence record changed during read")
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_constant,
    )


def draft(release_sha: str) -> dict:
    if not isinstance(release_sha, str) or not SHA.fullmatch(release_sha):
        raise DispositionError("exact lowercase 40-character release SHA required")
    return {
        "schema": SCHEMA,
        "release_sha": release_sha,
        "security_owner_role": "",
        "independent_reviewer_role": "",
        "review_ticket_ref": "",
        "review_completed_at_utc": "",
        "full_history_scan": {
            "event": "pending",
            "status": "pending",
            "release_sha": release_sha,
            "run_ref": "",
            "observed_at_utc": "",
            "entire_history_confirmed": False,
        },
        "findings": {
            key: {
                "source_path": path,
                "source_commit_prefix": commit,
                "source_line": line,
                "classification": "unresolved",
                "inventory_comparison_ref": "",
                "access_review_ref": "",
                "disposition_ref": "",
                "revocation_rotation_ref": "",
                "reviewed_at_utc": "",
            }
            for key, (path, commit, line) in FINDINGS.items()
        },
    }


def check(record: object, *, expected_sha: str) -> dict:
    expected = draft(expected_sha)
    if not isinstance(record, dict) or set(record) != set(expected):
        raise DispositionError("disposition record schema incomplete")
    if record["schema"] != SCHEMA or record["release_sha"] != expected_sha:
        raise DispositionError("disposition release SHA mismatch")
    owner, reviewer = record["security_owner_role"], record["independent_reviewer_role"]
    if not _role(owner) or not _role(reviewer) or owner == reviewer:
        raise DispositionError("distinct accountable security roles required")
    if not _ref(record["review_ticket_ref"]):
        raise DispositionError("private review ticket missing")
    completed = _utc(record["review_completed_at_utc"])
    if completed is None:
        raise DispositionError("independent review time missing")

    rows = record["findings"]
    if not isinstance(rows, dict) or set(rows) != set(FINDINGS):
        raise DispositionError("all eight historical findings required")
    disposition_refs = set()
    inventory_refs = set()
    for key, fixed in FINDINGS.items():
        row = rows[key]
        if not isinstance(row, dict) or set(row) != set(expected["findings"][key]):
            raise DispositionError("historical finding record incomplete")
        if (row["source_path"], row["source_commit_prefix"]) != fixed[:2]:
            raise DispositionError("historical source identity mismatch")
        if type(row["source_line"]) is not int or row["source_line"] != fixed[2]:
            raise DispositionError("historical source line mismatch")
        if not isinstance(row["classification"], str) or row["classification"] not in CLASSIFICATIONS:
            raise DispositionError("historical finding unresolved")
        for field in ("inventory_comparison_ref", "access_review_ref", "disposition_ref"):
            if not _ref(row[field]):
                raise DispositionError("independent per-finding evidence incomplete")
        # Prevent one universal receipt masquerading as eight separate decisions.
        disposition_refs.add(row["disposition_ref"])
        inventory_refs.add(row["inventory_comparison_ref"])
        when = _utc(row["reviewed_at_utc"])
        if when is None or when > completed:
            raise DispositionError("finding review time inconsistent")
        remediation = row["revocation_rotation_ref"]
        if row["classification"] == "actual_or_reused":
            if not _ref(remediation):
                raise DispositionError("actual credential remediation proof required")
        elif remediation != "":
            raise DispositionError("synthetic classification cannot claim rotation")
    if len(disposition_refs) != len(FINDINGS) or len(inventory_refs) != len(FINDINGS):
        raise DispositionError("distinct per-finding evidence receipts required")
    scan = record["full_history_scan"]
    if not isinstance(scan, dict) or set(scan) != set(expected["full_history_scan"]):
        raise DispositionError("full-history scan record incomplete")
    if (scan["event"] not in ("schedule", "workflow_dispatch")
        or scan["status"] != "success"
        or scan["release_sha"] != expected_sha
        or scan["entire_history_confirmed"] is not True
        or not _ref(scan["run_ref"])):
        raise DispositionError("scheduled-equivalent full-history scan evidence missing")
    observed = _utc(scan["observed_at_utc"])
    if observed is None or observed < completed:
        raise DispositionError("full-history scan time precedes final review")
    return {
        "schema": "mcri-pilot-historical-secret-record-check-v1",
        "historical_findings_structurally_disposed": len(FINDINGS),
        "operator_attestations_independently_verified": False,
        "credential_inventory_independently_verified": False,
        "full_history_scan_independently_verified": False,
        "security_clearance_authorized": False,
        "pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a private NO-GO draft; no security scan")
    init.add_argument("--release-sha", required=True)
    init.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("check", help="Validate only private evidence-index structure")
    verify.add_argument("record", type=Path)
    verify.add_argument("--expected-sha", required=True)
    args = parser.parse_args(argv)
    if args.command == "init":
        try:
            data = draft(args.release_sha)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(args.output, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.write("\n")
        except (DispositionError, OSError):
            print("NO-GO: cannot initialize private historical disposition record", file=sys.stderr)
            return 2
        print("NO-GO: private eight-finding draft created; no finding was cleared.")
        return 0
    try:
        record = _read_private(args.record)
        result = check(record, expected_sha=args.expected_sha)
    except DispositionError:
        print("NO-GO: historical disposition record incomplete or invalid", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("NO-GO: historical disposition record unavailable or unreadable", file=sys.stderr)
        return 2
    print(f"EVIDENCE INDEX COMPLETE: {result['historical_findings_structurally_disposed']} items.")
    print("No credential truth, scan result, independent review or Pilot GO verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
