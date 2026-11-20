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
import os
from pathlib import Path, PurePosixPath
import re
import sys
import stat
import tarfile

SCHEMA = "mcri-pilot-recovery-pair-v1"
SHA_RE = re.compile(r"[a-f0-9]{64}\Z")
COMMIT_RE = re.compile(r"[a-f0-9]{40}\Z")
ATTESTATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z")
MAX_MEMBERS = 50_000
MAX_DECLARED_BYTES = 512 * 1024**3
MAX_RECORD_BYTES = 1_048_576


class RecoveryEvidenceError(ValueError):
    """Bounded error labels: no internal paths or file contents."""


def _matches_open_file_read(before: os.stat_result, after: os.stat_result, bytes_read: int) -> bool:
    """Accept only a complete, unchanged snapshot from one opened file descriptor.

    Bounded metadata/race detection is not a digital signature and cannot
    guarantee that a file will remain unchanged after the read.
    """
    return (
        bytes_read == before.st_size
        and (
            before.st_dev, before.st_ino, before.st_mode, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        ) == (
            after.st_dev, after.st_ino, after.st_mode, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
    )


def _digest(path: Path) -> str:
    """Hash one opened regular dump, rejecting detectable concurrent mutation.

    Do not first check and then separately follow a mutable pathname. The
    Evidence archive uses its own single-descriptor hash + TAR inspection.
    """
    try:
        if path.is_symlink():
            raise RecoveryEvidenceError("required artifact is unavailable or not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RecoveryEvidenceError("required artifact is unavailable or not a regular file")
            digestor = hashlib.sha256()
            total_read = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digestor.update(chunk)
                total_read += len(chunk)
            after = os.fstat(stream.fileno())
            if not _matches_open_file_read(before, after, total_read):
                raise RecoveryEvidenceError("PostgreSQL dump changed during verification")
            return digestor.hexdigest()
    except OSError:
        raise RecoveryEvidenceError("artifact could not be hashed") from None


def _read_integrity_sidecar(path: Path, limit: int) -> bytes:
    """Open a bounded, regular-file sidecar without following a direct symlink.

    A single descriptor is held for size checks and content read. POSIX
    O_NOFOLLOW prevents substitution with a direct symlink during open.
    """
    try:
        if path.is_symlink():
            raise RecoveryEvidenceError("PostgreSQL integrity sidecars unavailable")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RecoveryEvidenceError("PostgreSQL integrity sidecars unavailable")
            if before.st_size > limit:
                raise RecoveryEvidenceError("oversized PostgreSQL metadata sidecar")
            payload = stream.read(limit + 1)
            if len(payload) > limit:
                raise RecoveryEvidenceError("oversized PostgreSQL metadata sidecar")
            after = os.fstat(stream.fileno())
            if not _matches_open_file_read(before, after, len(payload)):
                raise RecoveryEvidenceError("PostgreSQL integrity sidecar changed during verification")
            return payload
    except OSError:
        raise RecoveryEvidenceError("PostgreSQL integrity sidecars unavailable") from None


def _db_identity(dump: Path, release_sha: str) -> dict:
    if not COMMIT_RE.fullmatch(release_sha):
        raise RecoveryEvidenceError("release SHA must be exactly 40 lowercase hex characters")
    digest = _digest(dump)
    if digest == hashlib.sha256(b"").hexdigest():
        raise RecoveryEvidenceError("empty PostgreSQL backup is not eligible")
    checksum_path = Path(str(dump) + ".sha256")
    metadata_path = Path(str(dump) + ".meta")
    checksum_bytes = _read_integrity_sidecar(checksum_path, 256)
    meta_bytes = _read_integrity_sidecar(metadata_path, 8192)
    try:
        sidecar = checksum_bytes.decode("utf-8")
        metadata = meta_bytes.decode("utf-8")
    except UnicodeError:
        raise RecoveryEvidenceError("PostgreSQL integrity sidecars unavailable") from None
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
    # Hash and inspect the SAME open file description. A renamed pathname
    # must not make a digest from one Evidence version describe another.
    seen: set[str] = set()
    members = 0
    bytes_declared = 0
    try:
        if archive.is_symlink():
            raise RecoveryEvidenceError("unsafe Evidence archive file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(archive, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RecoveryEvidenceError("unsafe Evidence archive file")
            digestor = hashlib.sha256()
            total_read = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digestor.update(chunk)
                total_read += len(chunk)
            digest = digestor.hexdigest()
            stream.seek(0)
            with tarfile.open(fileobj=stream, mode="r:*") as reader:
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
            after = os.fstat(stream.fileno())
            if not _matches_open_file_read(before, after, total_read):
                raise RecoveryEvidenceError("Evidence archive changed during verification")
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


def _exact_json_value(left: object, right: object) -> bool:
    """Recursive JSON equality with no bool/int or int/float coercion."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (left.keys() == right.keys() and
                all(_exact_json_value(left[key], right[key]) for key in left))
    if isinstance(left, list):
        return (len(left) == len(right) and
                all(_exact_json_value(a, b) for a, b in zip(left, right)))
    return left == right


def check_record(record: object, actual: dict, release_sha: str) -> None:
    if not isinstance(record, dict) or set(record) != set(actual):
        raise RecoveryEvidenceError("recovery record structure mismatch")
    for key in ("schema", "release_sha", "database", "evidence",
                "operator_quiescence_record_ref", "artifact_integrity_bound",
                "same_recovery_point_verified", "restore_drill_verified",
                "pilot_authorized"):
        if not _exact_json_value(record[key], actual[key]):
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


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicates at any depth; last-value-wins is unsafe evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryEvidenceError("duplicate recovery record key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise RecoveryEvidenceError("invalid recovery record numeric constant")


def _write_private_record(path: Path, record: dict) -> None:
    """Exclusive POSIX mode-0600 creation, independent of process umask."""
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > MAX_RECORD_BYTES:
        raise RecoveryEvidenceError("oversized recovery record")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def _read_private_record(path: Path) -> object:
    """Bounded one-descriptor read with pre/post metadata checks; no unsafe records."""
    if path.is_symlink():
        raise RecoveryEvidenceError("unsafe recovery record")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RecoveryEvidenceError("unsafe recovery record")
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RecoveryEvidenceError("recovery record permissions are not private")
        if metadata.st_size > MAX_RECORD_BYTES:
            raise RecoveryEvidenceError("oversized recovery record")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read(MAX_RECORD_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(payload) > MAX_RECORD_BYTES:
            raise RecoveryEvidenceError("oversized recovery record")
        if not _matches_open_file_read(metadata, after, len(payload)):
            raise RecoveryEvidenceError("recovery record changed during verification")
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_unique_json_keys,
        parse_constant=_reject_json_constant,
    )


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
            _write_private_record(args.output, observed)
            print("RECOVERY ARTIFACTS BOUND — consistency and restore NOT verified.")
            return 0
        supplied = _read_private_record(args.manifest)
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
