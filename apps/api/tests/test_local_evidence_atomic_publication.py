"""Local Evidence admission must never erase or replace foreign/colliding bytes.

No database, customer volume, malware scanner, or external storage required.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
import os
from pathlib import Path
import stat

from fastapi import UploadFile
import pytest

from app.modules.documents import storage as storage_module
from app.modules.documents.storage import LocalDocumentStorage, StorageError, UploadTooLarge


@pytest.fixture
def local_store(tmp_path: Path) -> LocalDocumentStorage:
    return LocalDocumentStorage(str(tmp_path / "isolated-evidence"), max_upload_bytes=8)


def _no_staging_files(root: Path) -> None:
    assert list(root.rglob(".mcri-upload-*.partial")) == []


def test_save_bytes_collision_preserves_original_and_no_partial(local_store):
    key = "_quarantine/one/evidence.pdf"
    existing = local_store.root / key
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"original-Evidence-should-survive")
    with pytest.raises(FileExistsError):
        local_store.save_bytes(b"new-but-colliding", key)
    assert existing.read_bytes() == b"original-Evidence-should-survive"
    _no_staging_files(local_store.root)


def test_save_upload_collision_preserves_original_and_closes_upload(local_store):
    key = "_quarantine/one/new.pdf"
    existing = local_store.root / key
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"historic-claim-evidence")
    stream = BytesIO(b"fresh")
    with pytest.raises(FileExistsError):
        asyncio.run(local_store.save_upload(UploadFile(file=stream, filename="new.pdf"), key))
    assert existing.read_bytes() == b"historic-claim-evidence"
    assert stream.closed
    _no_staging_files(local_store.root)


@pytest.mark.parametrize("method", ["save_bytes", "save_upload"])
def test_late_publish_collision_never_overwrites_other_writer(
    local_store, monkeypatch, method,
):
    key = "_quarantine/one/raced.pdf"
    target = local_store.root / key
    real_link = storage_module.os.link
    injected = []

    def concurrent_writer(source, destination, *args, **kwargs):
        if Path(destination) == target:
            assert not target.exists()
            target.write_bytes(b"concurrent-publisher-wins")
            injected.append(True)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(storage_module.os, "link", concurrent_writer)
    with pytest.raises(FileExistsError):
        if method == "save_bytes":
            local_store.save_bytes(b"later", key)
        else:
            asyncio.run(local_store.save_upload(
                UploadFile(file=BytesIO(b"later"), filename="raced.pdf"), key
            ))
    assert injected == [True]
    assert target.read_bytes() == b"concurrent-publisher-wins"
    _no_staging_files(local_store.root)


def test_excess_upload_never_publishes_partial_bytes(local_store):
    stream = BytesIO(b"123456789ABC")
    with pytest.raises(UploadTooLarge):
        asyncio.run(local_store.save_upload(
            UploadFile(file=stream, filename="oversize.pdf"), "abc/oversize.pdf"
        ))
    assert stream.closed
    assert not (local_store.root / "abc/oversize.pdf").exists()
    _no_staging_files(local_store.root)


def test_successful_publication_is_private_complete_and_digest_correct(local_store):
    key = "org/claim/document.pdf"
    stored = local_store.save_bytes(b"private-claim-bytes", key)
    assert stored.file_size_bytes == len(b"private-claim-bytes")
    assert local_store.path_for(key).read_bytes() == b"private-claim-bytes"
    assert stat.S_IMODE(local_store.path_for(key).stat().st_mode) == 0o600
    _no_staging_files(local_store.root)

    upload = UploadFile(file=BytesIO(b"upload"), filename="another.pdf")
    saved = asyncio.run(local_store.save_upload(upload, "org/claim/another.pdf"))
    assert saved.file_size_bytes == 6
    assert local_store.path_for(saved.storage_key).read_bytes() == b"upload"
    assert stat.S_IMODE(local_store.path_for(saved.storage_key).stat().st_mode) == 0o600
    _no_staging_files(local_store.root)


def test_promote_moves_quarantine_to_final_without_overwrite(local_store):
    local_store.save_bytes(b"approved-bytes", "_quarantine/one/source")
    local_store.promote("_quarantine/one/source", "org/claim/admitted")
    assert local_store.path_for("org/claim/admitted").read_bytes() == b"approved-bytes"
    assert not (local_store.root / "_quarantine/one/source").exists()


def test_promote_existing_destination_retains_both_files(local_store):
    local_store.save_bytes(b"quarantined", "_quarantine/one/source")
    local_store.save_bytes(b"admitted-original", "org/claim/admitted")
    with pytest.raises(StorageError, match="Target storage key already exists"):
        local_store.promote("_quarantine/one/source", "org/claim/admitted")
    assert local_store.path_for("org/claim/admitted").read_bytes() == b"admitted-original"
    assert local_store.path_for("_quarantine/one/source").read_bytes() == b"quarantined"


def test_promote_raced_in_admitted_destination_is_preserved(local_store, monkeypatch):
    local_store.save_bytes(b"quarantine-original", "_quarantine/one/source")
    target = local_store.root / "org/claim/admitted"
    real_link = storage_module.os.link
    raced = []

    def inject_target(source, destination, *args, **kwargs):
        if Path(destination) == target:
            target.write_bytes(b"unrelated-writer-evidence")
            raced.append(True)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(storage_module.os, "link", inject_target)
    with pytest.raises(StorageError, match="Target storage key already exists"):
        local_store.promote("_quarantine/one/source", "org/claim/admitted")
    assert raced == [True]
    assert target.read_bytes() == b"unrelated-writer-evidence"
    assert local_store.path_for("_quarantine/one/source").read_bytes() == b"quarantine-original"


def test_promote_failed_source_unlink_keeps_both_custody_links(local_store, monkeypatch):
    local_store.save_bytes(b"custody-retained", "_quarantine/one/source")
    source = local_store.root / "_quarantine/one/source"
    original_unlink = Path.unlink

    def deny_source_unlink(path, *args, **kwargs):
        if path == source:
            raise PermissionError("synthetic-only")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_source_unlink)
    with pytest.raises(StorageError, match="Storage move failed"):
        local_store.promote("_quarantine/one/source", "org/claim/admitted")
    assert source.read_bytes() == b"custody-retained"
    assert (local_store.root / "org/claim/admitted").read_bytes() == b"custody-retained"
    assert source.stat().st_ino == (local_store.root / "org/claim/admitted").stat().st_ino
