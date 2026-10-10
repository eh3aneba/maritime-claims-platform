#!/usr/bin/env python3
"""Bind a PostgreSQL dump and a bounded Evidence tar archive to one integrity record.

A valid binding proves *artifact identity*, NOT that the two backups were
captured from the same recovery instant. Operator quiescence/restore proof and
independent approval remain mandatory for Pilot v1.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

SCHEMA = "mcri-pilot-recovery-pair-v1"
SHA_RE = re.compile(r"[a-f0-9]{64}\Z")
COMMIT_RE = re.compile(r"[a-f0-9]{40}\Z")
ATTESTATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z")
MAX_MEMBERS = 50_000
MAX_DECLARED_BYTES = 512 * 1024**3


class RecoveryEvidenceError(ValueError):
    """Bounded error labels: no internal paths or file contents."""


def _digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RecoveryEvidenceError("required artifact is unavailable or not a regular file")
    hash_obj = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hash_obj.update(chunk)
    except OSError:
        raise RecoveryEvidenceError("artifact could not be hashed") from None
    return hash_obj.hexdigest()


def _db_identity(dump: Path, release_sha: str) -> dict:
    if not COMMIT_RE.fullmatch(release_sha):
        raise RecoveryEvidenceError("release SHA must be exactly 40 lowercase hex characters")
    digest = _digest(dump)
    if digest == hashlib.sha256(b"").hexdigest():
        raise RecoveryEvidenceError("empty PostgreSQL backup is not eligible")
    try:
        sidecar = (Path(str(dump) + ".sha256")).read_text(encoding="utf-8")
        meta_bytes = (Path(str(dump) + ".meta")).read_bytes()
        metadata = meta_bytes.decode("utf-8")
    except (OSError, UnicodeError):
        raise RecoveryEvidenceError("PostgreSQL integrity sidecars unavailable") from None
    if len(sidecar) > 256 or len(meta_bytes) > 8192:
        raise RecoveryEvidenceError("oversized PostgreSQL metadata sidecar")
    parts = sidecar.strip().split()
    if len(parts) != 2 or not SHA_RE.fullmatch(parts[0]) or parts[1] != dump.name:
        raise RecoveryEvidenceError("PostgreSQL checksum sidecar is malformed")
    if parts[0] != digest:
        raise RecoveryEvidenceError("PostgreSQL dump checksum mismatch")
    parsed: dict[str, str] = {}
    for line in metadata.splitlines():
        if "=" not in line:
            raise RecoveryEvidenceError("malformed PostgreSQL metadata record")
        key, value = line.split("=", 1)
        if key in parsed:
            raise RecoveryEvidenceError("duplicate PostgreSQL metadata field")
        parsed[key] = value
    expected = {
        "format", "created_at_utc", "database", "git_sha", "alembic_heads",
        "dump_file", "dump_sha256",
    }
    if set(parsed) != expected or parsed["format"] != "mcri-postgres-backup-v1":
        raise RecoveryEvidenceError("unsupported PostgreSQL backup metadata")
    if (parsed["dump_file"] != dump.name
        or parsed["dump_sha256"] != digest
        or parsed["git_sha"] != release_sha):
        raise RecoveryEvidenceError("PostgreSQL backup release or digest mismatch")
    if not parsed["alembic_heads"] or len(parsed["alembic_heads"]) > 300:
        raise RecoveryEvidenceError("PostgreSQL Alembic revision is missing or invalid")
    try:
        instant = datetime.fromisoformat(parsed["created_at_utc"].replace("Z", "+00:00"))
    except ValueError:
        raise RecoveryEvidenceError("invalid PostgreSQL backup timestamp") from None
    if not parsed["created_at_utc"].endswith("Z") or instant.utcoffset().total_seconds() != 0:
        raise RecoveryEvidenceError("non-UTC PostgreSQL backup timestamp")
    return {
        "dump_sha256": digest,
        "metadata_sha256": hashlib.sha256(meta_bytes).hexdigest(),
        "alembic_heads": parsed["alembic_heads"],
        "backup_created_at_utc": parsed["created_at_utc"],
    }


def _evidence_identity(archive: Path) -> dict:
    digest = _digest(archive)
    seen: set[str] = set()
    members = 0
    bytes_declared = 0
    try:
        with tarfile.open(archive, mode="r:*") as reader:
            for entry in reader:
                members += 1
                if members > MAX_MEMBERS:
                    raise RecoveryEvidenceError("Evidence archive entry limit exceeded")
                name = entry.name
                if (not isinstance(name, str) or not name or
                    name.startswith("/") or "\\" in name or
                    any(ord(c) < 32 for c in name)):
                    raise RecoveryEvidenceError("unsafe Evidence archive entry path")
                segments = name.rstrip("/").split("/")
                if ".." in segments:
                    raise RecoveryEvidenceError("Evidence archive traversal rejected")
                normalized = str(PurePosixPath(name))
                if normalized == ".":
                    if entry.isdir():
                        continue
                    raise RecoveryEvidenceError("invalid Evidence archive root entry")
                if normalized in seen:
                    raise RecoveryEvidenceError("duplicate Evidence archive path")
                seen.add(normalized)
                if not (entry.isfile() or entry.isdir()):
                    raise RecoveryEvidenceError("Evidence archive contains an unsafe entry type")
                if entry.isfile():
                    if entry.size < 0:
                        raise RecoveryEvidenceError("invalid Evidence archive member size")
                    bytes_declared += entry.size
                if bytes_declared > MAX_DECLARED_BYTES:
                    raise RecoveryEvidenceError("Evidence archive declared size limit exceeded")
    except (tarfile.TarError, EOFError, OSError):
        raise RecoveryEvidenceError("Evidence archive could not be parsed safely") from None
    if not seen:
        raise RecoveryEvidenceError("Evidence archive has no entries")
    return {
        "archive_sha256": digest,
        "entry_count": len(seen),
        "declared_regular_file_bytes": bytes_declared,
    }


def observe(*, db_dump: Path, evidence_archive: Path, release_sha: str,
            quiescence_ref: str) -> dict:
    if not ATTESTATION_RE.fullmatch(quiescence_ref):
        raise RecoveryEvidenceError("quiescence reference must be an opaque safe record ID")
    database = _db_identity(db_dump, release_sha)
    evidence = _evidence_identity(evidence_archive)
    return {
        "schema": SCHEMA,
        "release_sha": release_sha,
        "recorded_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "database": database,
        "evidence": evidence,
        "operator_quiescence_record_ref": quiescence_ref,
        "artifact_integrity_bound": True,
        "same_recovery_point_verified": False,
        "restore_drill_verified": False,
        "pilot_authorized": False,
    }


def check_record(record: object, actual: dict, release_sha: str) -> None:
    if not isinstance(record, dict) or set(record) != set(actual):
        raise RecoveryEvidenceError("recovery record structure mismatch")
    for key in ("schema", "release_sha", "database", "evidence",
                "operator_quiescence_record_ref", "artifact_integrity_bound",
                "same_recovery_point_verified", "restore_drill_verified",
                "pilot_authorized"):
        if record[key] != actual[key]:
            raise RecoveryEvidenceError("recovery binding differs from current artifacts")
    if record["release_sha"] != release_sha:
        raise RecoveryEvidenceError("recovery record release SHA mismatch")
    if not isinstance(record["recorded_at_utc"], str):
        raise RecoveryEvidenceError("recovery record timestamp invalid")
    try:
        parsed = datetime.fromisoformat(record["recorded_at_utc"].replace("Z", "+00:00"))
    except ValueError:
        raise RecoveryEvidenceError("recovery record timestamp invalid") from None
    if not record["recorded_at_utc"].endswith("Z") or parsed.utcoffset().total_seconds() != 0:
        raise RecoveryEvidenceError("recovery record timestamp must be UTC")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("create", "verify"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--db-dump", type=Path, required=True)
        cmd.add_argument("--evidence-archive", type=Path, required=True)
        cmd.add_argument("--release-sha", required=True)
        if action == "create":
            cmd.add_argument("--quiescence-ref", required=True)
            cmd.add_argument("--output", type=Path, required=True)
        else:
            cmd.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            observed = observe(
                db_dump=args.db_dump, evidence_archive=args.evidence_archive,
                release_sha=args.release_sha, quiescence_ref=args.quiescence_ref,
            )
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(observed, stream, indent=2, sort_keys=True)
                stream.write("\n")
            print("RECOVERY ARTIFACTS BOUND — consistency and restore NOT verified.")
            return 0
        with args.manifest.open(encoding="utf-8") as stream:
            supplied = json.load(stream)
        ref = supplied.get("operator_quiescence_record_ref") if isinstance(supplied, dict) else ""
        observed = observe(
            db_dump=args.db_dump, evidence_archive=args.evidence_archive,
            release_sha=args.release_sha, quiescence_ref=ref,
        )
        check_record(supplied, observed, args.release_sha)
        print("RECOVERY ARTIFACT DIGESTS VERIFIED — NOT a same-point or Pilot GO proof.")
        return 0
    except (RecoveryEvidenceError, OSError, ValueError, UnicodeError) as exc:
        label = str(exc) if isinstance(exc, RecoveryEvidenceError) else "artifact/manifest unavailable or invalid"
        print("NO-GO: " + label, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
