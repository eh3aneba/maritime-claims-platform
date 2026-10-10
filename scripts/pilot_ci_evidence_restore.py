"""Synthetic CI-only Evidence archive extraction and restored-DB hash reconciliation.

Never extract into live storage or touch customer files. Every archive entry
must be a regular file or directory, with safe normalized paths, in bounded
numbers and total bytes. Only fixed error labels cross the test boundary.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILES = 5000
MAX_BYTES = 2 * 1024**3


class EvidenceRestoreError(ValueError):
    """Fixed-phrase, privacy-safe synthetic restore error."""


def safe_relative(name: str) -> Path:
    if not isinstance(name, str) or not name or name.startswith("/"):
        raise EvidenceRestoreError("unsafe synthetic archive path")
    if "\\" in name or any(ord(c) < 32 for c in name):
        raise EvidenceRestoreError("unsafe synthetic archive path")
    stripped = name.rstrip("/")
    parts = stripped.split("/")
    if not stripped or any(part in ("", ".", "..") for part in parts):
        raise EvidenceRestoreError("unsafe synthetic archive path")
    normalized = str(PurePosixPath(stripped))
    if normalized != stripped:
        raise EvidenceRestoreError("unnormalized synthetic archive path")
    return Path(*parts)


def restore_and_reconcile(archive_path: Path, restore_dir: Path,
                          db_rows_json: str) -> dict[str, int]:
    """Restore into a NEW empty directory and hash-check demo Documents."""
    try:
        documents = json.loads(db_rows_json)
    except (TypeError, ValueError):
        raise EvidenceRestoreError("restored synthetic document rows malformed") from None
    if not isinstance(documents, list) or not documents or len(documents) > MAX_FILES:
        raise EvidenceRestoreError("missing or invalid restored synthetic documents")

    restored: dict[str, Path] = {}
    count = 0
    total = 0
    try:
        if not restore_dir.is_dir() or any(restore_dir.iterdir()):
            raise EvidenceRestoreError("synthetic restore destination must be empty")
        with tarfile.open(archive_path, mode="r:*") as archive:
            for item in archive:
                name = item.name
                path_key = safe_relative(name)
                destination = restore_dir / path_key
                if item.isdir():
                    if destination.is_symlink():
                        raise EvidenceRestoreError("unsafe synthetic restore target")
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not item.isfile() or name in restored:
                    raise EvidenceRestoreError("unsafe or duplicate synthetic archive member")
                count += 1
                total += item.size
                if count > MAX_FILES or item.size < 0 or total > MAX_BYTES:
                    raise EvidenceRestoreError("synthetic Evidence archive exceeds bounds")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() or destination.is_symlink():
                    raise EvidenceRestoreError("duplicate synthetic restore destination")
                handle = archive.extractfile(item)
                if handle is None:
                    raise EvidenceRestoreError("synthetic archive member content missing")
                with handle, destination.open("xb") as output:
                    shutil.copyfileobj(handle, output, length=1024 * 1024)
                if destination.stat().st_size != item.size:
                    raise EvidenceRestoreError("synthetic Evidence extracted size mismatch")
                restored[name] = destination
    except EvidenceRestoreError:
        raise
    except (OSError, tarfile.TarError, EOFError, ValueError):
        raise EvidenceRestoreError("synthetic Evidence archive restore failed") from None

    matched: set[str] = set()
    for item in documents:
        if not isinstance(item, dict) or set(item) != {"key", "sha256", "size"}:
            raise EvidenceRestoreError("restored synthetic Document metadata malformed")
        key = item["key"]
        safe_relative(key)
        digest = item["sha256"]
        size = item["size"]
        if (key in matched or key not in restored
            or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
            or type(size) is not int or size < 0):
            raise EvidenceRestoreError("restored synthetic Document file missing or invalid")
        path = restored[key]
        if path.stat().st_size != size:
            raise EvidenceRestoreError("restored synthetic Document size mismatch")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            raise EvidenceRestoreError("restored synthetic Document digest mismatch")
        matched.add(key)
    return {"files_restored": count, "demo_documents_matched": len(matched)}
