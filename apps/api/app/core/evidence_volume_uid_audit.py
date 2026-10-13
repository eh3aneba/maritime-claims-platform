"""Read-only, privacy-safe POSIX-mode precheck for non-root Evidence migration.

No modification of Evidence bytes, ownership, permissions or names is allowed.
A precheck PASS is NOT a live effective-UID access probe or rollout approval:
POSIX ACLs, mounts, concurrent changes and existing operator controls still need
independent review. Invoke within the existing API container with the mounted
LOCAL_STORAGE_PATH, before enabling a non-root API/document worker.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat


TARGET_UID = 1000
TARGET_GID = 1000
MAX_ENTRIES = 20000
MAX_DEPTH = 32


class EvidencePermissionAuditError(RuntimeError):
    """An intentionally bounded error code, without filesystem paths."""


def _mode_allows(metadata: os.stat_result, uid: int, gid: int, bits: int) -> bool:
    mode = stat.S_IMODE(metadata.st_mode)
    granted = (mode >> 6) if metadata.st_uid == uid else (
        (mode >> 3) if metadata.st_gid == gid else mode
    )
    return granted & bits == bits


def audit_evidence_tree(
    root: Path, *, uid: int = TARGET_UID, gid: int = TARGET_GID,
    entry_limit: int = MAX_ENTRIES,
) -> int:
    """Inspect metadata only. Return number inspected; never list entry names."""
    if not root.is_absolute() or entry_limit < 1 or uid < 1 or gid < 1:
        raise EvidencePermissionAuditError("invalid_audit_contract")
    try:
        # All ancestors must be real, traversable directories. Reject symlink
        # ancestors rather than resolving and silently inspecting a new target.
        for ancestor in reversed(root.parents):
            meta = ancestor.lstat()
            if not stat.S_ISDIR(meta.st_mode) or not _mode_allows(meta, uid, gid, 1):
                raise EvidencePermissionAuditError("unsafe_ancestor")
        stack = [(root, 0)]
        inspected = 0
        while stack:
            path, depth = stack.pop()
            inspected += 1
            if inspected > entry_limit or depth > MAX_DEPTH:
                raise EvidencePermissionAuditError("scan_limit_exceeded")
            meta = path.lstat()
            mode = stat.S_IMODE(meta.st_mode)
            if stat.S_ISLNK(meta.st_mode):
                raise EvidencePermissionAuditError("symlink_detected")
            if mode & stat.S_IWOTH:
                raise EvidencePermissionAuditError("world_writable_entry")
            if stat.S_ISDIR(meta.st_mode):
                # Incoming non-root API/worker must be able to enumerate,
                # enter, create, rename and remove files in existing subtrees.
                if not _mode_allows(meta, uid, gid, 7):
                    raise EvidencePermissionAuditError("directory_permissions")
                with os.scandir(path) as children:
                    for child in children:
                        stack.append((Path(child.path), depth + 1))
                        if inspected + len(stack) > entry_limit:
                            raise EvidencePermissionAuditError("scan_limit_exceeded")
            elif stat.S_ISREG(meta.st_mode):
                # Existing Evidence content must remain readable; creation,
                # quarantine and replacement are governed by parent dirs.
                if not _mode_allows(meta, uid, gid, 4):
                    raise EvidencePermissionAuditError("file_permissions")
            else:
                raise EvidencePermissionAuditError("unsupported_entry")
        return inspected
    except EvidencePermissionAuditError:
        raise
    except (OSError, ValueError):
        raise EvidencePermissionAuditError("metadata_unavailable") from None


def main() -> int:
    try:
        from app.core.config import get_settings

        settings = get_settings()
        if settings.storage_backend.lower().strip() != "local":
            raise EvidencePermissionAuditError("unsupported_storage_backend")
        audit_evidence_tree(Path(settings.local_storage_path))
    except EvidencePermissionAuditError as exc:
        print("NO-GO: Evidence non-root metadata precheck " + str(exc))
        return 2
    except Exception:
        print("NO-GO: Evidence non-root metadata precheck unavailable")
        return 2
    print("PRECHECK PASS: Evidence metadata appears compatible with UID/GID 1000.")
    print("NOT proof of ACLs, live write access, customer volume safety or rollout approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
