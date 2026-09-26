from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_change_detection_models import (
    ExternalDocumentSourceSftpChangeDetection,
    ExternalDocumentSourceSftpChangeDetectionReceipt,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    SftpExactFileMetadataResult,
    clear_external_document_source_sftp_exact_file_metadata_adapter,
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListingEntry,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_checkpoint import (
    _checkpoint,
    _completed_phase_j,
    setup_function as _k_setup,
    teardown_function as _k_teardown,
)


_REASON = (
    "Observe metadata for the exact checkpointed SFTP file once and classify "
    "it as unchanged, changed or canonical missing without reading content."
)


def setup_function() -> None:
    _k_setup()
    clear_external_document_source_sftp_exact_file_metadata_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_exact_file_metadata_adapter()
    _k_teardown()


def _completed_phase_k(seed: str):
    chain = _completed_phase_j(seed)
    response = _checkpoint(chain, key="checkpoint")
    assert response.status_code == 201, response.text
    chain["checkpoint_id"] = response.json()["id"]
    return chain


def _baseline(chain: dict):
    with TestingSessionLocal() as db:
        checkpoint = db.get(
            ExternalDocumentSourceSftpCheckpoint,
            UUID(chain["checkpoint_id"]),
        )
        assert checkpoint is not None
        entry = db.get(
            ExternalDocumentSourceSftpDirectoryListingEntry,
            checkpoint.listing_entry_id,
        )
        assert entry is not None
        return {
            "byte_size": checkpoint.content_byte_count,
            "modified_at": entry.modified_at,
            "metadata_id_hash": entry.metadata_id_hash,
        }


class _StatAdapter:
    adapter_kind = "deterministic_sftp_exact_file_metadata"

    def __init__(
        self,
        *,
        mode: str,
        baseline: dict,
    ):
        self.mode = mode
        self.baseline = baseline
        self.calls = []

    def stat_metadata(self, request):
        self.calls.append(request)
        common = dict(
            authentication_method=(
                "password"
                if request.authentication_kind == "password"
                else "public_key"
            ),
            latency_class="fast",
            secret_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=True,
            host_key_verification_performed=True,
            host_key_verified=True,
            authentication_performed=True,
            authentication_succeeded=True,
            sftp_session_opened=True,
            remote_stat_performed=True,
            sftp_session_closed=True,
        )
        if self.mode == "missing":
            return SftpExactFileMetadataResult(
                found=False,
                failure_code="not_found",
                **common,
            )
        if self.mode == "permission":
            return SftpExactFileMetadataResult(
                found=False,
                failure_code="permission_denied",
                **common,
            )
        if self.mode == "timeout":
            return SftpExactFileMetadataResult(
                found=False,
                failure_code="stat_timeout",
                **common,
            )

        size = self.baseline["byte_size"]
        modified_at = self.baseline["modified_at"]
        metadata_id_hash = self.baseline["metadata_id_hash"]
        if self.mode == "changed":
            size += 1
            if modified_at is not None:
                modified_at = modified_at + timedelta(seconds=1)
        return SftpExactFileMetadataResult(
            found=True,
            entry_kind="file",
            byte_size=size,
            modified_at=modified_at,
            metadata_id_hash=metadata_id_hash,
            **common,
        )


def _observe(
    chain: dict,
    *,
    key: str,
    reason: str = _REASON,
    actor_id=None,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-checkpoints/{chain['checkpoint_id']}/change-detections"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_sftp_change_detection_unchanged_is_exact_path_metadata_only_and_replay_safe() -> None:
    chain = _completed_phase_k("sftp-change-unchanged")
    baseline = _baseline(chain)
    adapter = _StatAdapter(mode="unchanged", baseline=baseline)
    register_external_document_source_sftp_exact_file_metadata_adapter(adapter)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    forbidden = _observe(
        chain,
        key="forbidden",
        extra={
            "remote_path": "/caller/path",
            "content": "caller-content",
            "storage_key": "caller/storage",
            "cursor": "caller-cursor",
            "version": "caller-version",
            "provider_item_id": "caller-provider-id",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert adapter.calls == []

    _, other_requester, _, _ = _seed_tenant("sftp-change-other")
    wrong_tenant = _observe(
        chain,
        key="wrongtenant",
        actor_id=other_requester,
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert adapter.calls == []

    response = _observe(chain, key="observe")
    assert response.status_code == 201, response.text
    body = response.json()
    execution_id = body["id"]
    assert body["result_status"] == "unchanged"
    assert body["changed_dimensions"] is None
    assert body["observed_byte_size"] == baseline["byte_size"]
    assert body["remote_stat_performed"] is True
    assert body["exact_item_metadata_read_performed"] is True
    assert body["change_detection_completed"] is True
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_content_transiently_observed"] is False
    assert body["storage_read_performed"] is False
    assert body["storage_write_performed"] is False
    assert body["storage_delete_performed"] is False
    assert body["storage_copy_performed"] is False
    assert body["checkpoint_advanced"] is False
    assert body["subscription_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False
    assert len(adapter.calls) == 1
    request = adapter.calls[0]
    assert request.max_stat_attempts == 1
    assert request.follow_symlinks is False
    assert request.read_only_intent is True
    assert request.entry_relative_path
    assert request.effective_remote_path.endswith(request.entry_relative_path)

    for forbidden_field in (
        "effective_remote_path",
        "entry_relative_path",
        "remote_root_path",
        "hostname",
        "reference_name",
        "reference_namespace",
        "storage_object_key",
        "content",
    ):
        assert forbidden_field not in body

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-change-detections/{execution_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["remote_stat_performed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    replay = _observe(chain, key="observe")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert len(adapter.calls) == 1

    changed_replay = _observe(
        chain,
        key="observe",
        reason=(
            "Attempt to alter the exact immutable Phase 17.6-L observation "
            "request after it was completed."
        ),
    )
    assert changed_replay.status_code == 409, changed_replay.text
    assert len(adapter.calls) == 1

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        row = db.get(
            ExternalDocumentSourceSftpChangeDetection,
            UUID(execution_id),
        )
        assert row is not None
        assert db.query(ExternalDocumentSourceSftpChangeDetection).count() == 1
        assert (
            db.query(ExternalDocumentSourceSftpChangeDetectionReceipt).count()
            == 2
        )
        original = row.observed_projection_hash
        row.observed_projection_hash = "0" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-change-detections/{execution_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpChangeDetection,
            UUID(execution_id),
        )
        row.observed_projection_hash = original
        db.commit()


def test_sftp_change_detection_changed_and_missing_are_distinct() -> None:
    changed_chain = _completed_phase_k("sftp-change-changed")
    changed_adapter = _StatAdapter(
        mode="changed",
        baseline=_baseline(changed_chain),
    )
    register_external_document_source_sftp_exact_file_metadata_adapter(
        changed_adapter
    )
    changed = _observe(changed_chain, key="changed")
    assert changed.status_code == 201, changed.text
    changed_body = changed.json()
    assert changed_body["result_status"] == "changed"
    assert "byte_size" in changed_body["changed_dimensions"]
    assert len(changed_adapter.calls) == 1

    missing_chain = _completed_phase_k("sftp-change-missing")
    missing_adapter = _StatAdapter(
        mode="missing",
        baseline=_baseline(missing_chain),
    )
    register_external_document_source_sftp_exact_file_metadata_adapter(
        missing_adapter
    )
    missing = _observe(missing_chain, key="missing")
    assert missing.status_code == 201, missing.text
    missing_body = missing.json()
    assert missing_body["result_status"] == "missing"
    assert missing_body["observed_projection_hash"] is None
    assert missing_body["observed_byte_size"] is None
    assert missing_body["changed_dimensions"] is None
    assert len(missing_adapter.calls) == 1


@pytest.mark.parametrize("mode", ["permission", "timeout"])
def test_sftp_change_detection_provider_failures_never_become_missing(
    mode: str,
) -> None:
    chain = _completed_phase_k(f"sftp-change-failure-{mode}")
    adapter = _StatAdapter(mode=mode, baseline=_baseline(chain))
    register_external_document_source_sftp_exact_file_metadata_adapter(adapter)

    response = _observe(chain, key="failure")
    assert response.status_code == 409, response.text
    assert "observation failed" in response.text
    assert "missing" not in response.text.lower()
    assert len(adapter.calls) == 1
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpChangeDetection).count() == 0
