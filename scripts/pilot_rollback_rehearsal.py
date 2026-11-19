#!/usr/bin/env python3
"""Offline fail-closed operator record gate for a bounded Pilot rollback drill.

Validates evidence *references* and sequence/compatibility attestation only.
Never executes docker, database restore, migration downgrade, Git, HTTP,
production writes, image swaps or release authorization.
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

SCHEMA = "mcri-pilot-rollback-rehearsal-v1"
SHA = re.compile(r"[a-f0-9]{40}\Z")
ALEMBIC = re.compile(r"[0-9]{4}_[a-z0-9_]+\Z")
REF = re.compile(r"(?:artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,200}\Z")
ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,79}\Z")
IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]{2,200}@sha256:[a-f0-9]{64}\Z")
SERVICES = ("api", "web", "worker")
MODES = ("application_only", "recover_paired_backup")
# A rollback record is private operator metadata, not a public CI artifact.
MAX_ROLLBACK_RECORD_BYTES = 1_048_576
BASE_EVIDENCE = (
    "approved_change_ref",
    "operator_rehearsal_ref",
    "pre_change_backup_ref",
    "pre_change_health_ref",
    "post_rollback_health_ref",
    "post_rollback_authenticated_claim_ref",
    "operator_review_ref",
)
DB_RESTORE_EVIDENCE = (
    "recovery_pair_ref",
    "restore_operation_ref",
    "post_restore_document_lineage_ref",
    "post_restore_migration_preflight_ref",
)


class RollbackEvidenceError(ValueError):
    """Fixed operator-safe error messages, no values from the record."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise RollbackEvidenceError("duplicate rollback record key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise RollbackEvidenceError("nonstandard rollback JSON constant")


def _read_private_record(path: Path) -> object:
    """Read one bounded regular record, rejecting direct symlinks and FIFOs.

    Inspect and read the same file descriptor. The POSIX private-mode check
    is necessary for operator metadata; Windows ACLs must be verified by
    the deployment operator separately.
    """
    if path.is_symlink():
        raise RollbackEvidenceError("rollback record is not a private regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RollbackEvidenceError("rollback record is not a private regular file")
        if os.name == "posix" and stat.S_IMODE(before.st_mode) & 0o077:
            raise RollbackEvidenceError("rollback record permissions are not private")
        if before.st_size > MAX_ROLLBACK_RECORD_BYTES:
            raise RollbackEvidenceError("rollback record exceeds size limit")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            data = stream.read(MAX_ROLLBACK_RECORD_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(data) > MAX_ROLLBACK_RECORD_BYTES:
            raise RollbackEvidenceError("rollback record exceeds size limit")
        # Compare one opened descriptor across the bounded read. A shorter
        # parseable record is not necessarily the original operator snapshot.
        if (
            (before.st_dev, before.st_ino, before.st_mode, before.st_size,
             before.st_mtime_ns, before.st_ctime_ns)
            !=
            (after.st_dev, after.st_ino, after.st_mode, after.st_size,
             after.st_mtime_ns, after.st_ctime_ns)
            or len(data) != before.st_size
        ):
            raise RollbackEvidenceError("rollback record changed during verification")
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )


def draft(from_sha: str, to_sha: str) -> dict:
    if (not SHA.fullmatch(from_sha) or not SHA.fullmatch(to_sha)
        or from_sha == to_sha):
        raise RollbackEvidenceError("two distinct exact release SHAs required")
    return {
        "schema": SCHEMA,
        "from_release_sha": from_sha,
        "to_release_sha": to_sha,
        "environment_ref": "",
        "mode": "pending",
        "from_alembic_revision": "",
        "to_alembic_revision": "",
        "from_images": {service: "" for service in SERVICES},
        "to_images": {service: "" for service in SERVICES},
        "primary_operator_role": "",
        "independent_approver_role": "",
        "exercise_started_at_utc": "",
        "exercise_completed_at_utc": "",
        "rollback_result": "pending",
        "explicit_human_authorized": False,
        "unsafe_database_downgrade_performed": False,
        "live_database_restored": False,
        "evidence": {name: "" for name in BASE_EVIDENCE + DB_RESTORE_EVIDENCE},
    }


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if (dt.tzinfo != timezone.utc
        or dt.strftime("%Y-%m-%dT%H:%M:%SZ") != value):
        return None
    return dt


def _safe_ref(value: object) -> bool:
    return isinstance(value, str) and REF.fullmatch(value) is not None


def check(record: object, *, from_sha: str, to_sha: str) -> dict:
    if not SHA.fullmatch(from_sha) or not SHA.fullmatch(to_sha) or from_sha == to_sha:
        raise RollbackEvidenceError("invalid independently supplied release pair")
    if not isinstance(record, dict) or set(record) != set(draft(from_sha, to_sha)):
        raise RollbackEvidenceError("rollback record structure incomplete")
    if (record["schema"] != SCHEMA or record["from_release_sha"] != from_sha
        or record["to_release_sha"] != to_sha):
        raise RollbackEvidenceError("rollback release identity mismatch")
    if not _safe_ref(record["environment_ref"]):
        raise RollbackEvidenceError("rollback environment reference invalid")
    mode = record["mode"]
    if not isinstance(mode, str) or mode not in MODES:
        raise RollbackEvidenceError("rollback mode must be explicitly selected")
    before = record["from_alembic_revision"]
    after = record["to_alembic_revision"]
    if (not isinstance(before, str) or not ALEMBIC.fullmatch(before)
        or not isinstance(after, str) or not ALEMBIC.fullmatch(after)):
        raise RollbackEvidenceError("rollback migration revisions incomplete")
    if mode == "application_only" and before != after:
        raise RollbackEvidenceError("application-only rollback requires identical Alembic revisions")
    if not isinstance(record["from_images"], dict) or set(record["from_images"]) != set(SERVICES):
        raise RollbackEvidenceError("source image set incomplete")
    if not isinstance(record["to_images"], dict) or set(record["to_images"]) != set(SERVICES):
        raise RollbackEvidenceError("target image set incomplete")
    for service in SERVICES:
        old = record["from_images"][service]
        new = record["to_images"][service]
        if (not isinstance(old, str) or not IMAGE.fullmatch(old)
            or not isinstance(new, str) or not IMAGE.fullmatch(new)):
            raise RollbackEvidenceError("immutable rollback image identity missing")
    if (record["from_images"] == record["to_images"]):
        raise RollbackEvidenceError("rollback image sets did not change")
    operator = record["primary_operator_role"]
    reviewer = record["independent_approver_role"]
    if (not isinstance(operator, str) or not ROLE.fullmatch(operator)
        or not isinstance(reviewer, str) or not ROLE.fullmatch(reviewer)
        or operator == reviewer):
        raise RollbackEvidenceError("independent rollback responsibilities required")
    started = _utc(record["exercise_started_at_utc"])
    completed = _utc(record["exercise_completed_at_utc"])
    if started is None or completed is None or completed < started:
        raise RollbackEvidenceError("rollback rehearsal UTC window invalid")
    if (record["rollback_result"] != "pass"
        or record["explicit_human_authorized"] is not True
        or record["unsafe_database_downgrade_performed"] is not False):
        raise RollbackEvidenceError("rollback exercise or approval incomplete")
    db_restored = record["live_database_restored"]
    if type(db_restored) is not bool or (
        mode == "application_only" and db_restored is not False
    ) or (
        mode == "recover_paired_backup" and db_restored is not True
    ):
        raise RollbackEvidenceError("rollback mode and recorded database operation disagree")
    evidence = record["evidence"]
    expected_keys = set(BASE_EVIDENCE + DB_RESTORE_EVIDENCE)
    if not isinstance(evidence, dict) or set(evidence) != expected_keys:
        raise RollbackEvidenceError("rollback evidence references incomplete")
    for key in BASE_EVIDENCE:
        if not _safe_ref(evidence[key]):
            raise RollbackEvidenceError("required independent rollback evidence missing")
    for key in DB_RESTORE_EVIDENCE:
        if mode == "recover_paired_backup":
            if not _safe_ref(evidence[key]):
                raise RollbackEvidenceError("paired backup restore proof missing")
        elif evidence[key] != "":
            raise RollbackEvidenceError("application-only rollback must not claim DB restore evidence")
    return {
        "schema": "mcri-pilot-rollback-record-check-v1",
        "rollback_record_complete": True,
        "operator_attestations_independently_verified": False,
        "real_host_rollback_independently_verified": False,
        "fresh_host_restore_verified": False,
        "production_rollback_authorized": False,
        "pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="command", required=True)
    init = modes.add_parser("init", help="Create an exclusive NO-GO rehearsal draft")
    init.add_argument("--from-sha", required=True)
    init.add_argument("--to-sha", required=True)
    init.add_argument("--output", type=Path, required=True)
    verify = modes.add_parser("check", help="Validate a completed operator evidence record")
    verify.add_argument("record", type=Path)
    verify.add_argument("--from-sha", required=True)
    verify.add_argument("--to-sha", required=True)
    args = parser.parse_args(argv)
    if args.command == "init":
        try:
            # Validate before opening the exclusive destination: a bad release
            # pair must not leave a zero-byte "record" behind.
            record = draft(args.from_sha, args.to_sha)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(args.output, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(record, stream, indent=2, sort_keys=True)
                stream.write("\n")
        except RollbackEvidenceError as exc:
            print("NO-GO: " + str(exc), file=sys.stderr)
            return 2
        except OSError:
            print("NO-GO: cannot create exclusive rollback draft", file=sys.stderr)
            return 2
        print("NO-GO rollback rehearsal draft created; no rollback executed.")
        return 0
    try:
        record = _read_private_record(args.record)
        check(record, from_sha=args.from_sha, to_sha=args.to_sha)
    except RollbackEvidenceError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("NO-GO: rollback record unreadable", file=sys.stderr)
        return 2
    print("ROLLBACK RECORD COMPLETE: independent operator evidence review still required.")
    print("This is NOT proof of actual rollback, production approval, or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
