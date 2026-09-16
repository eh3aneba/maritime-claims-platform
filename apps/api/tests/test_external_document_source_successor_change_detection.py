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
from app.modules.external_document_sources.checkpoint_generation_models import ExternalDocumentSourceCheckpointGenerationExecution
from app.modules.external_document_sources.remote_file_content_read_service import register_external_document_source_remote_file_content_read_adapter
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    clear_external_document_source_remote_metadata_list_adapters,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
    ExternalDocumentSourceSuccessorChangeDetectionReceipt,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import (
    _ChangeAdapter,
    _PROVIDER_URL,
    _RAW_ITEM_ID,
    _SECRET,
    _TOKEN,
    _RAW_RESPONSE,
    _detect,
)
from tests.test_external_document_source_checkpoint_generation import (
    _advance,
    _completed_phase_q,
    setup_function as _phase_r_setup,
    teardown_function as _phase_r_teardown,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_content_staging import _FILE_BODY_MARKER, _STORAGE_SECRET
from tests.test_external_document_source_remote_file_content_read import _FILE_BODY
from tests.test_external_document_source_sync_checkpoint import _checkpoint, _completed_phase_n
from tests.test_external_document_source_versioned_restaging import (
    _NEW_BODY,
    _NEW_VERSION,
    _Q_RAW,
    _Q_SECRET,
    _Q_TOKEN,
    _QReadAdapter,
    _restage,
)

_OBSERVE_REASON = "Observe the exact provider item once against the immutable generation-2 successor checkpoint using metadata only."
_GEN2_MODIFIED = datetime(2026, 9, 16, 6, 30, tzinfo=timezone.utc)


def setup_function() -> None:
    _phase_r_setup()


def teardown_function() -> None:
    _phase_r_teardown()


def _observe(
    profile_id: str,
    r_execution_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _OBSERVE_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-executions/{r_execution_id}/successor-change-detection-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def _generation2_projection(*, size: int | None = None, version: str | None = _NEW_VERSION, modified: datetime = _GEN2_MODIFIED):
    return RemoteMetadataItemProjection(
        provider_item_id="remote-file-m-001",
        parent_item_id="remote-folder-root",
        item_kind="file",
        display_name="Phase M Survey Report.pdf",
        mime_type_class="application/pdf",
        byte_size=len(_NEW_BODY) if size is None else size,
        modified_at=modified,
        version_token_hash=version,
    )


def _completed_phase_r():
    requester_id, profile_id, binding_id, checkpoint, change, q_body, q_adapter, phase_m_read_adapter, store = _completed_phase_q()
    r_response = _advance(profile_id, q_body["id"], requester_id, key="phase-s-r-successor")
    assert r_response.status_code == 201, r_response.text
    r_body = r_response.json()
    assert r_body["status"] == "completed"
    assert r_body["result_status"] == "checkpoint_generation_advanced"
    return requester_id, profile_id, binding_id, checkpoint, change, q_body, r_body, q_adapter, phase_m_read_adapter, store


def test_phase_s_successor_aware_exact_item_observation(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, _checkpoint_body, change, q_body, r_body, q_adapter, phase_m_read_adapter, store = _completed_phase_r()
    r_id = r_body["id"]

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    upstream_io = (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)
    clear_external_document_source_remote_metadata_list_adapters()

    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(found=True, item=_generation2_projection())
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )

    forbidden = _observe(
        profile_id,
        r_id,
        requester_id,
        key="phase-s-forbidden",
        extra={
            "checkpoint_generation": 9,
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
    assert adapter.calls == 0
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == upstream_io

    _, other_requester, _ = _seed_tenant("phase-s-other-tenant")
    wrong_tenant = _observe(profile_id, r_id, other_requester, key="phase-s-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert adapter.calls == 0

    unchanged = _observe(profile_id, r_id, requester_id, key="phase-s-unchanged")
    assert unchanged.status_code == 201, unchanged.text
    body = unchanged.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "unchanged"
    assert body["baseline_generation"] == 2
    assert body["baseline_projection_hash"] == change["observed_projection_hash"]
    assert body["baseline_provider_item_id_hash"] == change["observed_provider_item_id_hash"]
    assert body["baseline_version_token_hash"] == _NEW_VERSION
    assert body["baseline_byte_size"] == len(_NEW_BODY)
    assert body["candidate_content_proof_hash"] == q_body["content_proof_hash"]
    assert body["successor_checkpoint_state_hash"] == r_body["successor_checkpoint_state_hash"]
    assert body["changed_dimensions"] == ""
    assert body["provider_client_constructed"] is True
    assert body["exact_item_metadata_read_performed"] is True
    assert body["successor_change_detection_completed"] is True
    assert body["remote_content_transiently_observed"] is False
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_write_performed"] is False
    assert body["remote_delete_performed"] is False
    assert body["storage_read_performed"] is False
    assert body["storage_write_performed"] is False
    assert body["storage_delete_performed"] is False
    assert body["durable_content_staged"] is False
    assert body["checkpoint_created"] is False
    assert body["checkpoint_advanced"] is False
    assert body["sync_executed"] is False
    assert body["subscription_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["content_parsed"] is False
    assert body["content_extracted"] is False
    assert body["claim_mutated"] is False
    assert adapter.calls == 1
    assert adapter.last_policy is not None
    assert "/items/remote-file-m-001" in adapter.last_policy.metadata_endpoint_url
    assert "/content" not in adapter.last_policy.metadata_endpoint_url
    assert adapter.last_policy.allow_redirects is False
    assert adapter.last_policy.max_response_bytes == 65536
    assert adapter.last_policy.field_projection == "id,name,size,lastModifiedDateTime,file,folder,parentReference,eTag"
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == upstream_io

    for forbidden_field in (
        "provider_item_id",
        "metadata_endpoint_url",
        "provider_origin",
        "storage_object_key",
        "storage_key",
        "content",
        "access_token",
        "client_secret",
    ):
        assert forbidden_field not in body

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-change-detection-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert rows[0]["provider_client_constructed"] is False
    assert rows[1]["provider_client_constructed"] is True

    replay = _observe(profile_id, r_id, requester_id, key="phase-s-unchanged")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert adapter.calls == 1

    changed_replay = _observe(
        profile_id,
        r_id,
        requester_id,
        key="phase-s-unchanged",
        reason="Attempt to alter the completed Phase S request while retaining its request key.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    assert adapter.calls == 1

    adapter.result = ExactItemMetadataResult(found=True, item=_generation2_projection(size=len(_NEW_BODY) + 1))
    changed = _observe(profile_id, r_id, requester_id, key="phase-s-changed")
    assert changed.status_code == 201, changed.text
    assert changed.json()["result_status"] == "changed"
    assert changed.json()["changed_dimensions"] == "byte_size"
    assert adapter.calls == 2

    adapter.result = ExactItemMetadataResult(found=False, failure_code="not_found")
    missing = _observe(profile_id, r_id, requester_id, key="phase-s-missing")
    assert missing.status_code == 201, missing.text
    assert missing.json()["result_status"] == "missing"
    assert missing.json()["changed_dimensions"] == "missing"
    assert adapter.calls == 3

    successful_count = 3
    failures = (
        "unauthorized",
        "permission_denied",
        "endpoint_unavailable",
        "timeout",
        "malformed_response",
        "oversized_response",
        "provider_rejected",
    )
    for index, failure in enumerate(failures, start=1):
        adapter.result = ExactItemMetadataResult(found=False, failure_code=failure)
        failed = _observe(profile_id, r_id, requester_id, key=f"phase-s-failure-{index}")
        assert failed.status_code == 409, failed.text
        assert "missing" not in failed.text.lower()
        with TestingSessionLocal() as db:
            assert db.query(ExternalDocumentSourceSuccessorChangeDetectionExecution).count() == successful_count
            assert db.query(ExternalDocumentSourceSuccessorChangeDetectionReceipt).count() == successful_count * 2

    adapter.result = ExactItemMetadataResult(
        found=True,
        item=RemoteMetadataItemProjection(
            provider_item_id="unexpected-provider-item",
            parent_item_id="remote-folder-root",
            item_kind="file",
            display_name="Phase M Survey Report.pdf",
            mime_type_class="application/pdf",
            byte_size=len(_NEW_BODY),
            modified_at=_GEN2_MODIFIED,
            version_token_hash=_NEW_VERSION,
        ),
    )
    identity_failure = _observe(profile_id, r_id, requester_id, key="phase-s-identity-failure")
    assert identity_failure.status_code == 409, identity_failure.text

    adapter.raise_with_secrets = True
    exception_failure = _observe(profile_id, r_id, requester_id, key="phase-s-secret-exception")
    assert exception_failure.status_code == 409, exception_failure.text
    assert "successor metadata observation failed" in exception_failure.text.lower()
    for marker in (_SECRET, _TOKEN, _RAW_RESPONSE, _PROVIDER_URL):
        assert marker not in exception_failure.text
        assert marker not in caplog.text
    adapter.raise_with_secrets = False

    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceSuccessorChangeDetectionExecution, UUID(execution_id))
        r_row = db.get(ExternalDocumentSourceCheckpointGenerationExecution, UUID(r_id))
        assert execution is not None and r_row is not None
        original_r_hash = r_row.successor_checkpoint_state_hash
        r_row.successor_checkpoint_state_hash = "0" * 64
        db.commit()
    calls_before_tamper = adapter.calls
    tampered_upstream = _observe(profile_id, r_id, requester_id, key="phase-s-r-tampered")
    assert tampered_upstream.status_code == 409, tampered_upstream.text
    assert adapter.calls == calls_before_tamper
    with TestingSessionLocal() as db:
        r_row = db.get(ExternalDocumentSourceCheckpointGenerationExecution, UUID(r_id))
        assert r_row is not None
        r_row.successor_checkpoint_state_hash = original_r_hash
        db.commit()

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceSuccessorChangeDetectionReceipt).filter(
            ExternalDocumentSourceSuccessorChangeDetectionReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceSuccessorChangeDetectionReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "tampered Phase S receipt reason"
        db.commit()
    tampered_receipt = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceSuccessorChangeDetectionReceipt).filter(
            ExternalDocumentSourceSuccessorChangeDetectionReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceSuccessorChangeDetectionReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_successor_change_detection_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        payload = json.dumps(audit.new_values, sort_keys=True, default=str) + (audit.details or "")
        q_row_storage_key = db.execute(
            __import__("sqlalchemy").select(__import__("app.modules.external_document_sources.versioned_restaging_models", fromlist=["ExternalDocumentSourceVersionedRestagingExecution"]).ExternalDocumentSourceVersionedRestagingExecution.storage_object_key).where(
                __import__("app.modules.external_document_sources.versioned_restaging_models", fromlist=["ExternalDocumentSourceVersionedRestagingExecution"]).ExternalDocumentSourceVersionedRestagingExecution.id == UUID(q_body["id"])
            )
        ).scalar_one()
        assert q_row_storage_key not in payload
        for marker in (_RAW_ITEM_ID, _FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL, _SECRET, _TOKEN, _RAW_RESPONSE, _Q_SECRET, _Q_TOKEN, _Q_RAW):
            assert marker not in unchanged.text
            assert marker not in payload
            assert marker not in caplog.text

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable upstream credential lineage so completed Phase S observations fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == upstream_io


def test_phase_s_without_version_token_uses_generation2_projection_fallback() -> None:
    requester_id, profile_id, _binding_id, staging_execution_id, phase_m_read_adapter, store = _completed_phase_n()
    checkpoint_response = _checkpoint(profile_id, staging_execution_id, requester_id, key="phase-s-no-version-o")
    assert checkpoint_response.status_code == 201, checkpoint_response.text
    checkpoint = checkpoint_response.json()

    phase_p_adapter = _ChangeAdapter()
    phase_p_adapter.result = ExactItemMetadataResult(
        found=True,
        item=RemoteMetadataItemProjection(
            provider_item_id="remote-file-m-001",
            parent_item_id="remote-folder-root",
            item_kind="file",
            display_name="Phase M Survey Report.pdf",
            mime_type_class="application/pdf",
            byte_size=len(_NEW_BODY),
            modified_at=_GEN2_MODIFIED,
            version_token_hash=None,
        ),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", phase_p_adapter,
    )
    phase_p = _detect(profile_id, checkpoint["id"], requester_id, key="phase-s-no-version-p")
    assert phase_p.status_code == 201, phase_p.text
    assert phase_p.json()["result_status"] == "changed"
    assert phase_p.json()["observed_version_token_hash"] is None

    q_adapter = _QReadAdapter(version=None)
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint", "graph_drive_item_content_read_v1", q_adapter,
    )
    q = _restage(profile_id, phase_p.json()["id"], requester_id, key="phase-s-no-version-q")
    assert q.status_code == 201, q.text
    assert q.json()["content_version_token_hash"] is None

    r = _advance(profile_id, q.json()["id"], requester_id, key="phase-s-no-version-r")
    assert r.status_code == 201, r.text
    assert r.json()["version_token_hash"] is None

    clear_external_document_source_remote_metadata_list_adapters()
    successor_adapter = _ChangeAdapter()
    successor_adapter.result = ExactItemMetadataResult(
        found=True,
        item=_generation2_projection(size=len(_NEW_BODY) + 1, version=None),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", successor_adapter,
    )
    io_before = (phase_m_read_adapter.calls, q_adapter.calls, store.put_calls, store.head_calls, store.get_calls)
    observed = _observe(profile_id, r.json()["id"], requester_id, key="phase-s-no-version-observation")
    assert observed.status_code == 201, observed.text
    body = observed.json()
    assert body["baseline_version_token_hash"] is None
    assert body["observed_version_token_hash"] is None
    assert body["result_status"] == "changed"
    assert body["changed_dimensions"] == "byte_size"
    assert successor_adapter.calls == 1
    assert (phase_m_read_adapter.calls, q_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before
