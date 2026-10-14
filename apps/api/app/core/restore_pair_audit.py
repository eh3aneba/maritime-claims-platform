"""Read-only fail-closed reconciliation for a restored DB/Evidence pair.

This is an integrity gate, NOT a restore command or an authorization to change
an existing host, ACL, filesystem or database. The caller must select an
independently isolated, quiesced copy and supply its authoritative DB rows.
Never emit paths, record IDs, file contents or other Evidence metadata in errors.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
from uuid import UUID


_ALLOWED_SUFFIXES = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_ROWS = 1000
MAX_FILE_BYTES = 150 * 1024 * 1024


class RestorePairAuditError(RuntimeError):
    """Only a bounded, privacy-safe error category is exposed."""


@dataclass(frozen=True)
class RestoreEvidenceRow:
    kind: str
    record_id: UUID
    organization_id: UUID
    claim_id: UUID
    storage_key: str
    file_hash: str
    file_size_bytes: int
    state: str


def audit_restored_evidence_pair(
    root: Path,
    records: list[RestoreEvidenceRow],
    *,
    organization_id: UUID,
    claim_id: UUID,
    uid: int = 1000,
    gid: int = 1000,
) -> int:
    """Verify DB references against an already-restored private filesystem.

    No filesystem writes. Enforce canonical claimed paths, quarantined vs
    admitted status, mode/owner, no symlinks, exact bytes/SHA and deduplicated
    row/key identity. This is a bounded selected-claim reconciliation, not a
    complete cross-claim backup manifest or point-in-time recovery proof.
    """
    if (
        not isinstance(root, Path) or not root.is_absolute()
        or uid < 1 or gid < 1 or not records or len(records) > MAX_ROWS
        or not isinstance(organization_id, UUID) or not isinstance(claim_id, UUID)
    ):
        raise RestorePairAuditError("invalid_contract")
    try:
        root_meta = root.lstat()
        if not stat.S_ISDIR(root_meta.st_mode) or stat.S_IMODE(root_meta.st_mode) != 0o700:
            raise RestorePairAuditError("unsafe_root")
        if root_meta.st_uid != uid or root_meta.st_gid != gid:
            raise RestorePairAuditError("unsafe_root_owner")
        seen_ids: set[tuple[str, UUID]] = set()
        seen_keys: set[str] = set()
        count = 0
        for record in records:
            if record.organization_id != organization_id or record.claim_id != claim_id:
                raise RestorePairAuditError("wrong_claim_lineage")
            if not isinstance(record.record_id, UUID):
                raise RestorePairAuditError("invalid_row")
            if record.kind not in {"document", "quarantine"}:
                raise RestorePairAuditError("invalid_row")
            if (
                not isinstance(record.file_hash, str)
                or not _SHA256.fullmatch(record.file_hash)
                or not isinstance(record.file_size_bytes, int)
                or not 1 <= record.file_size_bytes <= MAX_FILE_BYTES
            ):
                raise RestorePairAuditError("invalid_row")
            if (
                (record.kind == "document" and record.state != "clean")
                or (record.kind == "quarantine" and record.state not in {"infected", "scan_error"})
            ):
                raise RestorePairAuditError("unsafe_evidence_state")
            key = record.storage_key
            if not isinstance(key, str) or not key or "\\" in key or "\x00" in key:
                raise RestorePairAuditError("unsafe_storage_key")
            pure = PurePosixPath(key)
            if pure.is_absolute() or any(part in ("", ".", "..") for part in key.split("/")):
                raise RestorePairAuditError("unsafe_storage_key")
            if pure.as_posix() != key or len(key) > 500:
                raise RestorePairAuditError("unsafe_storage_key")
            suffix = pure.suffix.lower()
            if suffix not in _ALLOWED_SUFFIXES:
                raise RestorePairAuditError("unsafe_storage_key")
            prefix = (
                (str(organization_id), str(claim_id))
                if record.kind == "document"
                else ("_quarantine", str(organization_id), str(claim_id))
            )
            if pure.parts != (*prefix, f"{record.record_id}{suffix}"):
                raise RestorePairAuditError("wrong_storage_lineage")
            identity = (record.kind, record.record_id)
            if identity in seen_ids or key in seen_keys:
                raise RestorePairAuditError("duplicate_reference")
            seen_ids.add(identity)
            seen_keys.add(key)
            current = root
            for segment in pure.parts[:-1]:
                current = current / segment
                meta = current.lstat()
                if (
                    not stat.S_ISDIR(meta.st_mode)
                    or meta.st_uid != uid or meta.st_gid != gid
                    or stat.S_IMODE(meta.st_mode) != 0o700
                ):
                    raise RestorePairAuditError("unsafe_directory")
            path = current / pure.name
            before = path.lstat()
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != uid or before.st_gid != gid
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size != record.file_size_bytes
            ):
                raise RestorePairAuditError("unsafe_file")
            digest = hashlib.sha256()
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                opened = os.fstat(descriptor)
                if (
                    opened.st_dev != before.st_dev or opened.st_ino != before.st_ino
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_size != record.file_size_bytes
                ):
                    raise RestorePairAuditError("changed_file")
                with os.fdopen(descriptor, "rb", closefd=False) as source:
                    total = 0
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > record.file_size_bytes:
                            raise RestorePairAuditError("changed_file")
                        digest.update(chunk)
                if total != record.file_size_bytes:
                    raise RestorePairAuditError("changed_file")
            finally:
                os.close(descriptor)
            if digest.hexdigest() != record.file_hash:
                raise RestorePairAuditError("digest_mismatch")
            count += 1
        return count
    except RestorePairAuditError:
        raise
    except (OSError, ValueError, TypeError):
        raise RestorePairAuditError("evidence_unavailable") from None
