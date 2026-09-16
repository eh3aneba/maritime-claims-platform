import json
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.credential_reference_health_service import clear_external_document_source_credential_reference_health_resolvers
from app.modules.external_document_sources.credential_resolution_execution_service import clear_external_document_source_credential_resolution_resolvers
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_health_service import clear_external_document_source_provider_client_health_adapters
from app.modules.external_document_sources.remote_content_staging_models import ExternalDocumentSourceRemoteContentStagingExecution
from app.modules.external_document_sources.remote_content_staging_service import (
    clear_external_document_source_remote_content_staging_store,
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import clear_external_document_source_remote_file_content_read_adapters
from app.modules.external_document_sources.remote_metadata_listing_service import clear_external_document_source_remote_metadata_list_adapters
from app.modules.external_document_sources.sync_checkpoint_models import (
    CHECKPOINT_KIND,
    ExternalDocumentSourceSyncCheckpointExecution,
    ExternalDocumentSourceSyncCheckpointReceipt,
)
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_content_staging import (
    _FILE_BODY_MARKER,
    _PROVIDER_URL,
    _STORAGE_SECRET,
    _QuarantineStore,
    _completed_phase_m,
    _stage,
)

_CHECKPOINT_REASON = "Record one immutable initial synchronization checkpoint for the exact completed Phase N quarantine snapshot."


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    clear_external_document_source_remote_content_staging_store()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    clear_external_document_source_remote_content_staging_store()


def _completed_phase_n():
    requester_id, profile_id, binding_id, read_execution_id, read_adapter = _completed_phase_m()
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)
    staged = _stage(
        profile_id,
        read_execution_id,
        requester_id,
        key="sync-checkpoint-phase-n",
    )
    assert staged.status_code == 201, staged.text
    return requester_id, profile_id, binding_id, staged.json()["id"], read_adapter, store


def _checkpoint(
    profile_id: str,
    staging_execution_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _CHECKPOINT_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-staging-executions/{staging_execution_id}/sync-checkpoint-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def test_phase_o_bounded_initial_synchronization_checkpoint(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, staging_execution_id, read_adapter, store = _completed_phase_n()
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        staging = db.get(ExternalDocumentSourceRemoteContentStagingExecution, UUID(staging_execution_id))
        assert staging is not None
        internal_storage_key = staging.storage_object_key
        expected_content_hash = staging.expected_content_sha256
        expected_content_size = staging.expected_content_byte_count

    io_before = (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)

    forbidden = _checkpoint(
        profile_id,
        staging_execution_id,
        requester_id,
        key="checkpoint-forbidden",
        extra={
            "provider_item_id": "caller-controlled",
            "version": "caller-version",
            "cursor": "caller-cursor",
            "url": _PROVIDER_URL,
            "path": "/caller/path",
            "content": _FILE_BODY_MARKER,
            "storage_key": "caller/storage/key",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    _, other_requester, _ = _seed_tenant("phase-o-other-tenant")
    wrong_tenant = _checkpoint(
        profile_id,
        staging_execution_id,
        other_requester,
        key="checkpoint-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    completed = _checkpoint(
        profile_id,
        staging_execution_id,
        requester_id,
        key="checkpoint-001",
    )
    assert completed.status_code == 201, completed.text
    body = completed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "checkpoint_recorded"
    assert body["checkpoint_kind"] == CHECKPOINT_KIND
    assert body["checkpoint_generation"] == 1
    assert body["content_sha256"] == expected_content_hash
    assert body["content_byte_count"] == expected_content_size
    assert body["upstream_remote_content_staging_completed"] is True
    assert body["checkpoint_created"] is True
    assert body["sync_executed"] is False
    assert body["subscription_created"] is False
    assert body["provider_client_constructed"] is False
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_write_performed"] is False
    assert body["remote_delete_performed"] is False
    assert body["storage_read_performed"] is False
    assert body["storage_write_performed"] is False
    assert body["storage_delete_performed"] is False
    assert body["durable_content_staged"] is False
    assert body["remote_content_stored"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["claim_mutated"] is False
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    for forbidden_field in (
        "storage_object_key",
        "stored_etag",
        "provider_item_id",
        "provider_origin",
        "content_endpoint_url",
        "url",
        "content",
        "file_body",
        "download_url",
        "access_token",
        "client_secret",
        "provider_client",
    ):
        assert forbidden_field not in body
    for marker in (_FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL, internal_storage_key):
        assert marker not in completed.text
        assert marker not in caplog.text

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sync-checkpoint-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["checkpoint_created"] for row in rows] == [False, True]
    assert [row["sync_executed"] for row in rows] == [False, False]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sync-checkpoint-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["checkpoint_state_hash"] == body["checkpoint_state_hash"]
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    replay = _checkpoint(
        profile_id,
        staging_execution_id,
        requester_id,
        key="checkpoint-001",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    changed = _checkpoint(
        profile_id,
        staging_execution_id,
        requester_id,
        key="checkpoint-001",
        reason="Attempt to alter the completed Phase O initial synchronization checkpoint request.",
    )
    assert changed.status_code == 409, changed.text
    second = _checkpoint(
        profile_id,
        staging_execution_id,
        requester_id,
        key="checkpoint-002",
    )
    assert second.status_code == 409, second.text
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(execution_id))
        assert execution is not None
        assert execution.checkpoint_generation == 1
        persisted = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        receipt_rows = db.query(ExternalDocumentSourceSyncCheckpointReceipt).filter(
            ExternalDocumentSourceSyncCheckpointReceipt.execution_id == UUID(execution_id)
        ).all()
        for receipt in receipt_rows:
            persisted.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_sync_checkpoint_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        persisted_payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        for marker in (_FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL, internal_storage_key):
            assert marker not in persisted_payload
        assert "storage_object_key" not in json.dumps(audit.new_values, sort_keys=True)

        original_state_hash = execution.checkpoint_state_hash
        execution.checkpoint_state_hash = "0" * 64
        db.commit()

    tampered_checkpoint = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sync-checkpoint-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_checkpoint.status_code == 409, tampered_checkpoint.text
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(execution_id))
        execution.checkpoint_state_hash = original_state_hash
        db.commit()

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceSyncCheckpointReceipt).filter(
            ExternalDocumentSourceSyncCheckpointReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceSyncCheckpointReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "Tampered Phase O receipt reason."
        db.commit()
    tampered_receipt = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sync-checkpoint-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceSyncCheckpointReceipt).filter(
            ExternalDocumentSourceSyncCheckpointReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceSyncCheckpointReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    with TestingSessionLocal() as db:
        staging = db.get(ExternalDocumentSourceRemoteContentStagingExecution, UUID(staging_execution_id))
        original_storage_hash = staging.storage_object_key_hash
        staging.storage_object_key_hash = "0" * 64
        db.commit()
    upstream_tamper = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sync-checkpoint-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert upstream_tamper.status_code == 409, upstream_tamper.text
    with TestingSessionLocal() as db:
        staging = db.get(ExternalDocumentSourceRemoteContentStagingExecution, UUID(staging_execution_id))
        staging.storage_object_key_hash = original_storage_hash
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase O lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sync-checkpoint-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSyncCheckpointExecution).count() == 1
        assert db.query(ExternalDocumentSourceSyncCheckpointReceipt).count() == 2
