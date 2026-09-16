import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_models import (
    ExternalDocumentSourceChangeDetectionExecution,
    ExternalDocumentSourceChangeDetectionReceipt,
)
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    clear_external_document_source_change_detection_adapters,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.credential_reference_health_service import clear_external_document_source_credential_reference_health_resolvers
from app.modules.external_document_sources.credential_resolution_execution_service import clear_external_document_source_credential_resolution_resolvers
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_health_service import clear_external_document_source_provider_client_health_adapters
from app.modules.external_document_sources.remote_content_staging_service import clear_external_document_source_remote_content_staging_store
from app.modules.external_document_sources.remote_file_content_read_service import clear_external_document_source_remote_file_content_read_adapters
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    clear_external_document_source_remote_metadata_list_adapters,
)
from app.modules.external_document_sources.sync_checkpoint_models import ExternalDocumentSourceSyncCheckpointExecution
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_content_staging import _PROVIDER_URL, _STORAGE_SECRET
from tests.test_external_document_source_remote_file_content_read import _FILE_BODY, _FILE_BODY_MARKER, _VERSION_HASH
from tests.test_external_document_source_sync_checkpoint import _checkpoint, _completed_phase_n

_CHANGE_REASON = "Observe the exact Phase O checkpointed provider item once and compare bounded metadata without reading file content."
_SECRET = "phase-p-provider-secret-marker"
_TOKEN = "phase-p-provider-token-marker"
_RAW_RESPONSE = "phase-p-provider-raw-response-marker"
_RAW_ITEM_ID = "remote-file-m-001"
_BASELINE = RemoteMetadataItemProjection(
    provider_item_id=_RAW_ITEM_ID,
    parent_item_id="remote-folder-root",
    item_kind="file",
    display_name="Phase M Survey Report.pdf",
    mime_type_class="application/pdf",
    byte_size=len(_FILE_BODY),
    modified_at=datetime(2026, 9, 16, 5, 20, tzinfo=timezone.utc),
    version_token_hash=_VERSION_HASH,
)


class _ChangeAdapter:
    adapter_kind = "deterministic_phase_p_change_detection_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    observation_operation_kind = "graph_drive_item_metadata_read_v1"
    provider_origin = "https://graph.microsoft.com"

    def __init__(self):
        self.calls = 0
        self.result = ExactItemMetadataResult(found=True, item=_BASELINE)
        self.last_policy = None
        self.raise_with_secrets = False

    def read_item_metadata(self, locator, policy):
        self.calls += 1
        self.last_policy = policy
        client_secret = _SECRET
        access_token = _TOKEN
        raw_response = _RAW_RESPONSE
        provider_url = _PROVIDER_URL
        assert client_secret and access_token and raw_response and provider_url
        assert policy.provider_origin == "https://graph.microsoft.com"
        assert "/v1.0/sites/" in policy.metadata_endpoint_url
        assert "/drives/" in policy.metadata_endpoint_url
        assert "/items/remote-file-m-001" in policy.metadata_endpoint_url
        assert "/content" not in policy.metadata_endpoint_url
        assert policy.allow_redirects is False
        assert policy.max_response_bytes == 65536
        if self.raise_with_secrets:
            raise RuntimeError(f"observation failed {client_secret} {access_token} {raw_response} {provider_url}")
        return self.result


def setup_function() -> None:
    clear_external_document_source_change_detection_adapters()
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
    clear_external_document_source_change_detection_adapters()
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    clear_external_document_source_remote_content_staging_store()


def _detect(profile_id: str, checkpoint_id: str, actor_id: UUID, *, key: str, reason: str = _CHANGE_REASON, extra: dict | None = None):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sync-checkpoint-executions/{checkpoint_id}/change-detection-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def test_phase_p_bounded_exact_item_remote_change_detection(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, staging_execution_id, read_adapter, store = _completed_phase_n()
    checkpoint_response = _checkpoint(
        profile_id,
        staging_execution_id,
        requester_id,
        key="phase-p-checkpoint",
    )
    assert checkpoint_response.status_code == 201, checkpoint_response.text
    checkpoint_body = checkpoint_response.json()
    checkpoint_id = checkpoint_body["id"]
    checkpoint_state_hash = checkpoint_body["checkpoint_state_hash"]
    checkpoint_completion_hash = checkpoint_body["completion_hash"]

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    io_before = (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)

    forbidden = _detect(
        profile_id,
        checkpoint_id,
        requester_id,
        key="change-forbidden",
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

    _, other_requester, _ = _seed_tenant("phase-p-other-tenant")
    wrong_tenant = _detect(profile_id, checkpoint_id, other_requester, key="change-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    missing_adapter = _detect(profile_id, checkpoint_id, requester_id, key="change-no-adapter")
    assert missing_adapter.status_code == 409, missing_adapter.text
    assert "adapter is unavailable" in missing_adapter.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceChangeDetectionExecution).count() == 0

    adapter = _ChangeAdapter()
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )

    unchanged = _detect(profile_id, checkpoint_id, requester_id, key="change-001")
    assert unchanged.status_code == 201, unchanged.text
    body = unchanged.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "unchanged"
    assert body["changed_dimensions"] == ""
    assert body["provider_client_constructed"] is True
    assert body["exact_item_metadata_read_performed"] is True
    assert body["change_detection_completed"] is True
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["storage_read_performed"] is False
    assert body["storage_write_performed"] is False
    assert body["checkpoint_advanced"] is False
    assert body["sync_executed"] is False
    assert body["subscription_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["content_parsed"] is False
    assert body["content_extracted"] is False
    assert body["claim_mutated"] is False
    assert adapter.calls == 1
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    for forbidden_field in (
        "provider_item_id",
        "metadata_endpoint_url",
        "provider_origin",
        "url",
        "path",
        "content",
        "storage_key",
        "access_token",
        "client_secret",
        "provider_client",
    ):
        assert forbidden_field not in body
    for marker in (_RAW_ITEM_ID, _FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL, _SECRET, _TOKEN, _RAW_RESPONSE):
        assert marker not in unchanged.text
        assert marker not in caplog.text

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/change-detection-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["change_detection_completed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    replay = _detect(profile_id, checkpoint_id, requester_id, key="change-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert adapter.calls == 1
    changed_replay = _detect(
        profile_id,
        checkpoint_id,
        requester_id,
        key="change-001",
        reason="Attempt to alter the completed Phase P observation request while keeping the same idempotency key.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    assert adapter.calls == 1

    adapter.result = ExactItemMetadataResult(
        found=True,
        item=RemoteMetadataItemProjection(
            provider_item_id=_RAW_ITEM_ID,
            parent_item_id="remote-folder-root",
            item_kind="file",
            display_name="Phase M Survey Report.pdf",
            mime_type_class="application/pdf",
            byte_size=len(_FILE_BODY),
            modified_at=datetime(2026, 9, 16, 5, 25, tzinfo=timezone.utc),
            version_token_hash="c" * 64,
        ),
    )
    changed = _detect(profile_id, checkpoint_id, requester_id, key="change-002")
    assert changed.status_code == 201, changed.text
    assert changed.json()["result_status"] == "changed"
    assert changed.json()["changed_dimensions"] == "modified_at,version_token_hash"
    assert adapter.calls == 2

    adapter.result = ExactItemMetadataResult(found=False, failure_code="not_found")
    missing = _detect(profile_id, checkpoint_id, requester_id, key="change-003")
    assert missing.status_code == 201, missing.text
    assert missing.json()["result_status"] == "missing"
    assert missing.json()["changed_dimensions"] == "missing"
    assert missing.json()["observed_projection_hash"] is None
    assert adapter.calls == 3

    adapter.result = ExactItemMetadataResult(found=False, failure_code="permission_denied")
    permission_failure = _detect(profile_id, checkpoint_id, requester_id, key="change-permission")
    assert permission_failure.status_code == 409, permission_failure.text
    assert "permission_denied" in permission_failure.text
    assert adapter.calls == 4
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceChangeDetectionExecution).count() == 3
        assert db.query(ExternalDocumentSourceChangeDetectionReceipt).count() == 6

    with TestingSessionLocal() as db:
        checkpoint = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(checkpoint_id))
        assert checkpoint is not None
        assert checkpoint.checkpoint_state_hash == checkpoint_state_hash
        assert checkpoint.completion_hash == checkpoint_completion_hash
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before

        execution = db.get(ExternalDocumentSourceChangeDetectionExecution, UUID(execution_id))
        assert execution is not None
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_change_detection_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        persisted = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        persisted_payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True, default=str) + (audit.details or "")
        for marker in (_RAW_ITEM_ID, _FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL, _SECRET, _TOKEN, _RAW_RESPONSE):
            assert marker not in persisted_payload

        original_observed_hash = execution.observed_projection_hash
        execution.observed_projection_hash = "0" * 64
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceChangeDetectionExecution, UUID(execution_id))
        assert execution is not None
        execution.observed_projection_hash = original_observed_hash
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable upstream credentials so completed Phase P lineage must fail closed on later reads."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before
