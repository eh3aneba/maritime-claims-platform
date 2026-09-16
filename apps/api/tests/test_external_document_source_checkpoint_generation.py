import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.checkpoint_generation_models import (
    SUCCESSOR_CHECKPOINT_GENERATION,
    SUCCESSOR_CHECKPOINT_KIND,
    ExternalDocumentSourceCheckpointGenerationExecution,
    ExternalDocumentSourceCheckpointGenerationReceipt,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_service import RemoteMetadataItemProjection
from app.modules.external_document_sources.sync_checkpoint_models import ExternalDocumentSourceSyncCheckpointExecution
from app.modules.external_document_sources.versioned_restaging_models import ExternalDocumentSourceVersionedRestagingExecution
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _ChangeAdapter, _detect
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_content_staging import _FILE_BODY_MARKER, _PROVIDER_URL, _STORAGE_SECRET
from tests.test_external_document_source_versioned_restaging import (
    _NEW_BODY,
    _NEW_VERSION,
    _Q_RAW,
    _Q_SECRET,
    _Q_TOKEN,
    _QReadAdapter,
    _phase_p_observation,
    _restage,
    setup_function as _phase_q_setup,
    teardown_function as _phase_q_teardown,
)

_ADVANCE_REASON = "Advance the exact integrity-valid Phase Q candidate into one immutable generation-2 successor checkpoint without provider or storage I/O."


def setup_function() -> None:
    _phase_q_setup()


def teardown_function() -> None:
    _phase_q_teardown()


def _advance(
    profile_id: str,
    q_execution_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _ADVANCE_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/versioned-restaging-executions/{q_execution_id}/checkpoint-generation-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def _completed_phase_q():
    requester_id, profile_id, binding_id, checkpoint, change, phase_m_read_adapter, store = _phase_p_observation(result="changed")
    q_adapter = _QReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint", "graph_drive_item_content_read_v1", q_adapter,
    )
    q_response = _restage(profile_id, change["id"], requester_id, key="phase-r-q-candidate")
    assert q_response.status_code == 201, q_response.text
    q_body = q_response.json()
    assert q_body["status"] == "completed"
    assert q_body["result_status"] == "staged_candidate_verified"
    return requester_id, profile_id, binding_id, checkpoint, change, q_body, q_adapter, phase_m_read_adapter, store


def test_phase_r_bounded_checkpoint_generation_advancement(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, checkpoint, _change, q_body, q_adapter, phase_m_read_adapter, store = _completed_phase_q()
    q_id = q_body["id"]
    io_before = (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        predecessor = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(checkpoint["id"]))
        candidate = db.get(ExternalDocumentSourceVersionedRestagingExecution, UUID(q_id))
        assert predecessor is not None and candidate is not None
        predecessor_facts = (predecessor.checkpoint_state_hash, predecessor.completion_hash)
        candidate_facts = (
            candidate.content_proof_hash,
            candidate.completion_hash,
            candidate.storage_object_key_hash,
            candidate.storage_object_key,
        )

    forbidden = _advance(
        profile_id,
        q_id,
        requester_id,
        key="phase-r-forbidden",
        extra={
            "checkpoint_generation": 9,
            "provider_item_id": "caller-controlled",
            "version": "caller-version",
            "url": _PROVIDER_URL,
            "path": "/caller/path",
            "content": _FILE_BODY_MARKER,
            "storage_key": "caller/storage/key",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    _, other_requester, _ = _seed_tenant("phase-r-other-tenant")
    wrong_tenant = _advance(profile_id, q_id, other_requester, key="phase-r-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    completed = _advance(profile_id, q_id, requester_id, key="phase-r-001")
    assert completed.status_code == 201, completed.text
    body = completed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "checkpoint_generation_advanced"
    assert body["predecessor_checkpoint_generation"] == 1
    assert body["candidate_generation"] == 2
    assert body["successor_checkpoint_generation"] == SUCCESSOR_CHECKPOINT_GENERATION
    assert body["successor_checkpoint_kind"] == SUCCESSOR_CHECKPOINT_KIND
    assert body["versioned_restaging_execution_id"] == q_id
    assert body["predecessor_sync_checkpoint_execution_id"] == checkpoint["id"]
    assert body["provider_client_constructed"] is False
    assert body["exact_item_metadata_read_performed"] is False
    assert body["remote_content_transiently_observed"] is False
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_write_performed"] is False
    assert body["remote_delete_performed"] is False
    assert body["storage_read_performed"] is False
    assert body["storage_write_performed"] is False
    assert body["storage_delete_performed"] is False
    assert body["durable_content_staged"] is False
    assert body["checkpoint_created"] is True
    assert body["checkpoint_advanced"] is True
    assert body["checkpoint_generation_advance_completed"] is True
    assert body["sync_executed"] is False
    assert body["subscription_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["content_parsed"] is False
    assert body["content_extracted"] is False
    assert body["claim_mutated"] is False
    assert "storage_object_key" not in body
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert rows[0]["checkpoint_advanced"] is False
    assert rows[1]["checkpoint_advanced"] is True
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    replay = _advance(profile_id, q_id, requester_id, key="phase-r-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    changed_replay = _advance(
        profile_id,
        q_id,
        requester_id,
        key="phase-r-001",
        reason="Attempt to alter the completed Phase R request while retaining the already-consumed candidate.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    second_consumption = _advance(profile_id, q_id, requester_id, key="phase-r-second")
    assert second_consumption.status_code == 409, second_consumption.text
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    with TestingSessionLocal() as db:
        predecessor = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(checkpoint["id"]))
        candidate = db.get(ExternalDocumentSourceVersionedRestagingExecution, UUID(q_id))
        execution = db.get(ExternalDocumentSourceCheckpointGenerationExecution, UUID(execution_id))
        assert predecessor is not None and candidate is not None and execution is not None
        assert (predecessor.checkpoint_state_hash, predecessor.completion_hash) == predecessor_facts
        assert (
            candidate.content_proof_hash,
            candidate.completion_hash,
            candidate.storage_object_key_hash,
            candidate.storage_object_key,
        ) == candidate_facts
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceCheckpointGenerationExecution).count() == 1
        assert db.query(ExternalDocumentSourceCheckpointGenerationReceipt).count() == 2

        raw_storage_key = candidate.storage_object_key
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_checkpoint_generation_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        audit_payload = json.dumps(audit.new_values, sort_keys=True, default=str) + (audit.details or "")
        assert raw_storage_key not in audit_payload
        assert "storage_object_key" not in audit.new_values
        for marker in (_FILE_BODY_MARKER, _NEW_BODY.decode("ascii"), _STORAGE_SECRET, _PROVIDER_URL, _Q_SECRET, _Q_TOKEN, _Q_RAW):
            assert marker not in completed.text
            assert marker not in audit_payload
            assert marker not in caplog.text

        original_state_hash = execution.successor_checkpoint_state_hash
        execution.successor_checkpoint_state_hash = "0" * 64
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceCheckpointGenerationExecution, UUID(execution_id))
        assert execution is not None
        execution.successor_checkpoint_state_hash = original_state_hash
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable upstream credentials so completed Phase R lineage must fail closed on later reads."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text


def test_phase_r_rejects_competing_successor_for_same_predecessor_without_new_io() -> None:
    requester_id, profile_id, _binding_id, checkpoint, _change, q1, q_adapter, phase_m_read_adapter, store = _completed_phase_q()

    second_change_adapter = _ChangeAdapter()
    second_change_adapter.result = ExactItemMetadataResult(
        found=True,
        item=RemoteMetadataItemProjection(
            provider_item_id="remote-file-m-001",
            parent_item_id="remote-folder-root",
            item_kind="file",
            display_name="Phase M Survey Report.pdf",
            mime_type_class="application/pdf",
            byte_size=len(_NEW_BODY),
            modified_at=datetime(2026, 9, 16, 7, 30, tzinfo=timezone.utc),
            version_token_hash=_NEW_VERSION,
        ),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", second_change_adapter,
    )
    second_change = _detect(
        profile_id,
        checkpoint["id"],
        requester_id,
        key="phase-r-second-change",
    )
    assert second_change.status_code == 201, second_change.text
    assert second_change.json()["result_status"] == "changed"

    q2 = _restage(profile_id, second_change.json()["id"], requester_id, key="phase-r-second-q")
    assert q2.status_code == 201, q2.text
    assert q2.json()["result_status"] == "staged_candidate_verified"

    first = _advance(profile_id, q1["id"], requester_id, key="phase-r-first-successor")
    assert first.status_code == 201, first.text
    io_before_conflict = (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)

    competing = _advance(profile_id, q2.json()["id"], requester_id, key="phase-r-competing-successor")
    assert competing.status_code == 409, competing.text
    assert "successor" in competing.text.lower()
    assert (q_adapter.calls, phase_m_read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before_conflict
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceCheckpointGenerationExecution).count() == 1
        assert db.query(ExternalDocumentSourceCheckpointGenerationReceipt).count() == 2
