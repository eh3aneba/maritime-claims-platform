"""Synthetic H&M Claim Pack archive-download integrity regressions.

An immutable export's stored SHA-256 header is meaningful only if the local
archived bytes were checked against their persisted generation-time digest.
No test here changes a real customer claim or performs an external download.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from app.modules.claim_packs.models import ClaimPackExport
from app.modules.documents.service import _storage
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _create_export(export_format: str) -> tuple[str, dict]:
    seeded = create_orion_claim()
    claim_id = seeded["claim"]["id"]
    base_url = f"/api/v1/claims/{claim_id}/claim-pack-exports"
    response = client.post(
        base_url,
        json={
            "export_format": export_format,
            "acknowledge_review_aid": True,
            "generation_note": "Synthetic local archive integrity only",
        },
    )
    assert response.status_code == 201, response.text
    return base_url, response.json()


def _archive_path(export_id: str):
    with TestingSessionLocal() as db:
        record = db.get(ClaimPackExport, UUID(export_id))
        assert record is not None
        return _storage().path_for(record.storage_key)


@pytest.mark.parametrize("export_format", ["pdf", "xlsx"])
def test_unchanged_archive_is_verified_and_downloadable(export_format: str) -> None:
    base_url, metadata = _create_export(export_format)
    response = client.get(f"{base_url}/{metadata['id']}/download")
    assert response.status_code == 200, response.text
    assert len(response.content) == metadata["file_size_bytes"]
    assert hashlib.sha256(response.content).hexdigest() == metadata["file_hash"]
    assert response.headers["x-claim-pack-file-sha256"] == metadata["file_hash"]
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("mutation", ["same_size", "length_changed"])
def test_mutated_archive_is_rejected_without_rewriting_original_record(mutation: str) -> None:
    base_url, metadata = _create_export("xlsx")
    path = _archive_path(metadata["id"])
    original = path.read_bytes()
    assert original

    if mutation == "same_size":
        changed = (b"X" if original[0] != 88 else b"Y") + original[1:]
        assert len(changed) == len(original)
    else:
        changed = original + b"UNAPPROVED CHANGE"

    try:
        path.write_bytes(changed)
        rejected = client.get(f"{base_url}/{metadata['id']}/download")
        assert rejected.status_code == 409, rejected.text
        assert "SHA-256" in rejected.json()["detail"]
        assert "UNAPPROVED CHANGE" not in rejected.text
        assert "x-claim-pack-file-sha256" not in rejected.headers

        with TestingSessionLocal() as db:
            recorded = db.get(ClaimPackExport, UUID(metadata["id"]))
            assert recorded is not None
            assert recorded.file_hash == metadata["file_hash"]
            assert recorded.file_size_bytes == metadata["file_size_bytes"]
            assert recorded.snapshot_hash == metadata["snapshot_hash"]
    finally:
        path.write_bytes(original)

    restored = client.get(f"{base_url}/{metadata['id']}/download")
    assert restored.status_code == 200
    assert hashlib.sha256(restored.content).hexdigest() == metadata["file_hash"]


@pytest.mark.parametrize("field", ["file_hash", "file_size_bytes"])
def test_corrupt_stored_integrity_metadata_is_rejected(field: str) -> None:
    base_url, metadata = _create_export("xlsx")
    with TestingSessionLocal() as db:
        record = db.get(ClaimPackExport, UUID(metadata["id"]))
        assert record is not None
        if field == "file_hash":
            record.file_hash = "0" * 64
        else:
            record.file_size_bytes = record.file_size_bytes - 1
        db.commit()

    rejected = client.get(f"{base_url}/{metadata['id']}/download")
    assert rejected.status_code == 409, rejected.text
    assert "SHA-256" in rejected.json()["detail"]


def test_missing_archived_file_returns_gone_not_a_successful_download() -> None:
    base_url, metadata = _create_export("xlsx")
    path = _archive_path(metadata["id"])
    path.unlink()

    rejected = client.get(f"{base_url}/{metadata['id']}/download")
    assert rejected.status_code == 410, rejected.text
    assert "unavailable" in rejected.json()["detail"]
    assert "x-claim-pack-file-sha256" not in rejected.headers
