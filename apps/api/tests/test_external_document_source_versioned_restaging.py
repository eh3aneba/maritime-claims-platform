import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    clear_external_document_source_change_detection_adapters,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.credential_reference_health_service import clear_external_document_source_credential_reference_health_resolvers
from app.modules.external_document_sources.credential_resolution_execution_service import clear_external_document_source_credential_resolution_resolvers
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_health_service import clear_external_document_source_provider_client_health_adapters
from app.modules.external_document_sources.remote_content_staging_service import (
    clear_external_document_source_remote_content_staging_store,
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    RemoteFileContentReadResult,
    clear_external_document_source_remote_file_content_read_adapters,
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    clear_external_document_source_remote_metadata_list_adapters,
)
from app.modules.external_document_sources.sync_checkpoint_models import ExternalDocumentSourceSyncCheckpointExecution
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers
from app.modules.external_document_sources.versioned_restaging_models import (
    CANDIDATE_GENERATION,
    ExternalDocumentSourceVersionedRestagingExecution,
    ExternalDocumentSourceVersionedRestagingReceipt,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_change_detection import _ChangeAdapter, _detect
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_content_staging import (
    _FILE_BODY_MARKER,
    _PROVIDER_URL,
    _STORAGE_SECRET,
    _QuarantineStore,
)
from tests.test_external_document_source_remote_file_content_read import _FILE_BODY, _VERSION_HASH
from tests.test_external_document_source_sync_checkpoint import _checkpoint, _completed_phase_n

_RESTAGE_REASON = "Reread the exact Phase P changed file and stage one immutable candidate generation without advancing the checkpoint."
_NEW_VERSION = "c" * 64
_NEW_BODY = b"q" * len(_FILE_BODY)
_Q_SECRET = "phase-q-provider-secret-marker"
_Q_TOKEN = "phase-q-provider-token-marker"
_Q_RAW = "phase-q-raw-provider-response-marker"


class _QReadAdapter:
    adapter_kind = "deterministic_phase_q_content_read_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    read_operation_kind = "graph_drive_item_content_read_v1"
    provider_origin = "https://graph.microsoft.com"
    redirect_policy_kind = "provider_internal_https_one_hop_v1"

    def __init__(self, *, content: bytes = _NEW_BODY, version: str = _NEW_VERSION, media: str = "application/pdf"):
        self.content = content
        self.version = version
        self.media = media
        self.calls = 0
        self.last_policy = None

    def read_content(self, locator, policy):
        self.calls += 1
        self.last_policy = policy
        secret = _Q_SECRET
        token = _Q_TOKEN
        raw = _Q_RAW
        provider_url = _PROVIDER_URL
        assert secret and token and raw and provider_url
        assert policy.provider_origin == "https://graph.microsoft.com"
        assert "/items/remote-file-m-001/content" in policy.content_endpoint_url
        assert policy.max_redirects == 1
        return RemoteFileContentReadResult(
            read=True,
            content=self.content,
            media_type_class=self.media,
            observed_version_token_hash=self.version,
            latency_class="normal",
        )


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


def _restage(profile_id: str, change_id: str, actor_id: UUID, *, key: str, reason: str = _RESTAGE_REASON, extra: dict | None = None):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/change-detection-executions/{change_id}/versioned-restaging-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def _phase_p_observation(*, result: str = "changed"):
    requester_id, profile_id, binding_id, staging_execution_id, phase_m_read_adapter, store = _completed_phase_n()
    checkpoint_response = _checkpoint(profile_id, staging_execution_id, requester_id, key=f"phase-q-checkpoint-{result}")
    assert checkpoint_response.status_code == 201, checkpoint_response.text
    checkpoint = checkpoint_response.json()

    change_adapter = _ChangeAdapter()
    register_external_document_source_change_detection_adapter("sharepoint", "graph_drive_item_metadata_read_v1", change_adapter)
    if result == "changed":
        change_adapter.result = ExactItemMetadataResult(
            found=True,
            item=RemoteMetadataItemProjection(
                provider_item_id="remote-file-m-001",
                parent_item_id="remote-folder-root",
                item_kind="file",
                display_name="Phase M Survey Report.pdf",
                mime_type_class="application/pdf",
                byte_size=len(_NEW_BODY),
                modified_at=datetime(2026, 9, 16, 6, 30, tzinfo=timezone.utc),
                version_token_hash=_NEW_VERSION,
            ),
        )
    elif result == "missing":
        change_adapter.result = ExactItemMetadataResult(found=False, failure_code="not_found")
    else:
        change_adapter.result = ExactItemMetadataResult(
            found=True,
            item=RemoteMetadataItemProjection(
                provider_item_id="remote-file-m-001",
                parent_item_id="remote-folder-root",
                item_kind="file",
                display_name="Phase M Survey Report.pdf",
                mime_type_class="application/pdf",
                byte_size=len(_FILE_BODY),
                modified_at=datetime(2026, 9, 16, 5, 20, tzinfo=timezone.utc),
                version_token_hash=_VERSION_HASH,
            ),
        )
    response = _detect(profile_id, checkpoint["id"], requester_id, key=f"phase-q-change-{result}")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == result
    return requester_id, profile_id, binding_id, checkpoint, response.json(), phase_m_read_adapter, store


def test_phase_q_bounded_changed_item_versioned_restaging(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, checkpoint, change, phase_m_read_adapter, store = _phase_p_observation(result="changed")
    original_keys = set(store.objects)
    original_objects = dict(store.objects)
    original_io = (phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        checkpoint_row = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(checkpoint["id"]))
        assert checkpoint_row is not None
        checkpoint_state_hash = checkpoint_row.checkpoint_state_hash
        checkpoint_completion_hash = checkpoint_row.completion_hash

    forbidden = _restage(
        profile_id,
        change["id"],
        requester_id,
        key="phase-q-forbidden",
        extra={
            "provider_item_id": "caller-controlled",
            "version": "caller-version",
            "cursor": "caller-cursor",
            "url": _PROVIDER_URL,
            "path": "/caller/path",
            "range": "bytes=0-10",
            "content": _FILE_BODY_MARKER,
            "storage_key": "caller/storage/key",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert (phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == original_io

    _, other_requester, _ = _seed_tenant("phase-q-other-tenant")
    wrong_tenant = _restage(profile_id, change["id"], other_requester, key="phase-q-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert (phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == original_io

    q_adapter = _QReadAdapter()
    register_external_document_source_remote_file_content_read_adapter("sharepoint", "graph_drive_item_content_read_v1", q_adapter)
    completed = _restage(profile_id, change["id"], requester_id, key="phase-q-001")
    assert completed.status_code == 201, completed.text
    body = completed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "staged_candidate_verified"
    assert body["candidate_generation"] == CANDIDATE_GENERATION
    assert body["content_byte_count"] == len(_NEW_BODY)
    assert body["content_version_token_hash"] == _NEW_VERSION
    assert body["provider_client_constructed"] is True
    assert body["remote_content_transiently_observed"] is True
    assert body["remote_read_performed"] is True
    assert body["storage_read_performed"] is True
    assert body["storage_write_performed"] is True
    assert body["durable_content_staged"] is True
    assert body["versioned_restaging_completed"] is True
    assert body["checkpoint_created"] is False
    assert body["checkpoint_advanced"] is False
    assert body["sync_executed"] is False
    assert body["subscription_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["content_parsed"] is False
    assert body["content_extracted"] is False
    assert body["claim_mutated"] is False
    assert "storage_object_key" not in body
    assert q_adapter.calls == 1
    assert len(store.objects) == len(original_objects) + 1
    assert original_keys.issubset(store.objects)
    for key, payload in original_objects.items():
        assert store.objects[key] == payload
    new_keys = set(store.objects) - original_keys
    assert len(new_keys) == 1
    internal_new_key = next(iter(new_keys))
    assert store.objects[internal_new_key] == _NEW_BODY

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/versioned-restaging-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "content_verified", "completed"]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert rows[2]["prior_receipt_hash"] == rows[1]["receipt_hash"]

    replay_io = (q_adapter.calls, store.put_calls, store.head_calls, store.get_calls)
    replay = _restage(profile_id, change["id"], requester_id, key="phase-q-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert q_adapter.calls == replay_io[0]
    assert store.put_calls == replay_io[1]
    assert store.head_calls >= replay_io[2]

    changed_replay = _restage(
        profile_id,
        change["id"],
        requester_id,
        key="phase-q-001",
        reason="Attempt to alter the completed Phase Q request while retaining the consumed Phase P observation.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    second_consumption = _restage(profile_id, change["id"], requester_id, key="phase-q-second")
    assert second_consumption.status_code == 409, second_consumption.text

    with TestingSessionLocal() as db:
        checkpoint_row = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(checkpoint["id"]))
        assert checkpoint_row is not None
        assert checkpoint_row.checkpoint_state_hash == checkpoint_state_hash
        assert checkpoint_row.completion_hash == checkpoint_completion_hash
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceVersionedRestagingExecution, UUID(execution_id))
        assert execution is not None
        raw_storage_key = execution.storage_object_key
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_versioned_restaging_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        audit_payload = json.dumps(audit.new_values, sort_keys=True, default=str) + (audit.details or "")
        assert raw_storage_key not in audit_payload
        assert "storage_object_key" not in audit.new_values
        for marker in (_FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL, _Q_SECRET, _Q_TOKEN, _Q_RAW):
            assert marker not in completed.text
            assert marker not in audit_payload
            assert marker not in caplog.text
        original_proof = execution.content_proof_hash
        execution.content_proof_hash = "0" * 64
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/versioned-restaging-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceVersionedRestagingExecution, UUID(execution_id))
        assert execution is not None
        execution.content_proof_hash = original_proof
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable upstream credentials so completed Phase Q lineage must fail closed on later reads."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/versioned-restaging-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text


def test_phase_q_rejects_unchanged_and_missing_without_content_or_storage_io() -> None:
    for result in ("unchanged", "missing"):
        setup_function()
        requester_id, profile_id, _binding_id, _checkpoint_body, change, phase_m_read_adapter, store = _phase_p_observation(result=result)
        q_adapter = _QReadAdapter()
        register_external_document_source_remote_file_content_read_adapter("sharepoint", "graph_drive_item_content_read_v1", q_adapter)
        before = (q_adapter.calls, store.put_calls, store.head_calls, store.get_calls)
        response = _restage(profile_id, change["id"], requester_id, key=f"phase-q-ineligible-{result}")
        assert response.status_code == 409, response.text
        assert "changed" in response.text
        assert (q_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == before
        with TestingSessionLocal() as db:
            assert db.query(ExternalDocumentSourceVersionedRestagingExecution).count() == 0
            assert db.query(ExternalDocumentSourceVersionedRestagingReceipt).count() == 0
        teardown_function()


def test_phase_q_crash_after_put_recovers_same_object_without_reread_or_delete() -> None:
    requester_id, profile_id, _binding_id, _checkpoint_body, change, _phase_m_read_adapter, _original_store = _phase_p_observation(result="changed")
    crash_store = _QuarantineStore(fail_first_head_after_put=True)
    register_external_document_source_remote_content_staging_store(crash_store)
    q_adapter = _QReadAdapter()
    register_external_document_source_remote_file_content_read_adapter("sharepoint", "graph_drive_item_content_read_v1", q_adapter)

    first = _restage(profile_id, change["id"], requester_id, key="phase-q-crash")
    assert first.status_code == 409, first.text
    assert q_adapter.calls == 1
    assert crash_store.put_calls == 1
    assert len(crash_store.objects) == 1
    with TestingSessionLocal() as db:
        execution = db.query(ExternalDocumentSourceVersionedRestagingExecution).one()
        assert execution.status == "content_verified"
        assert execution.content_proof_hash is not None
        assert db.query(ExternalDocumentSourceVersionedRestagingReceipt).count() == 2

    replay = _restage(profile_id, change["id"], requester_id, key="phase-q-crash")
    assert replay.status_code == 201, replay.text
    assert replay.json()["status"] == "completed"
    assert q_adapter.calls == 1
    assert crash_store.put_calls == 1
    assert len(crash_store.objects) == 1
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceVersionedRestagingReceipt).count() == 3
