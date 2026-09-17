import json
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.checkpoint_generation_3_models import (
    ExternalDocumentSourceCheckpointGeneration3Execution,
    ExternalDocumentSourceCheckpointGeneration3Receipt,
)
from app.modules.external_document_sources.checkpoint_generation_models import (
    ExternalDocumentSourceCheckpointGenerationExecution,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_successor_versioned_restaging import (
    _RESTAGE_REASON,
    _TReadAdapter,
    _completed_phase_s,
    _restage_successor,
    setup_function as _phase_t_setup,
    teardown_function as _phase_t_teardown,
)

_ADVANCE_REASON = "Advance the exact completed Phase T generation-3 candidate to one immutable generation-3 successor checkpoint without provider or storage I/O."


def setup_function() -> None:
    _phase_t_setup()


def teardown_function() -> None:
    _phase_t_teardown()


def _advance(profile_id: str, t_execution_id: str, actor_id: UUID, *, key: str, reason: str = _ADVANCE_REASON, extra: dict | None = None):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{t_execution_id}/checkpoint-generation-3-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def _completed_phase_t():
    (
        requester_id,
        profile_id,
        binding_id,
        checkpoint,
        change,
        q_body,
        r_body,
        s_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        store,
    ) = _completed_phase_s(result="changed")
    t_adapter = _TReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        t_adapter,
    )
    t_response = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key="phase-u-t-candidate",
        reason=_RESTAGE_REASON,
    )
    assert t_response.status_code == 201, t_response.text
    t_body = t_response.json()
    assert t_body["status"] == "completed"
    assert t_body["result_status"] == "staged_candidate_verified"
    assert t_body["candidate_generation"] == 3
    return (
        requester_id,
        profile_id,
        binding_id,
        checkpoint,
        change,
        q_body,
        r_body,
        s_body,
        t_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        t_adapter,
        store,
    )


def _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store):
    return (
        metadata_adapter.calls,
        q_adapter.calls,
        phase_m_read_adapter.calls,
        t_adapter.calls,
        store.put_calls,
        store.head_calls,
        store.get_calls,
    )


def test_phase_u_generation3_checkpoint_advancement_is_zero_io_and_fail_closed() -> None:
    (
        requester_id,
        profile_id,
        _binding_id,
        _checkpoint,
        _change,
        _q_body,
        r_body,
        _s_body,
        t_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        t_adapter,
        store,
    ) = _completed_phase_t()

    before_io = _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store)
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        r_row = db.get(ExternalDocumentSourceCheckpointGenerationExecution, UUID(r_body["id"]))
        t_row = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(t_body["id"]))
        assert r_row is not None and t_row is not None
        r_facts = (r_row.successor_checkpoint_state_hash, r_row.completion_hash)
        t_facts = (
            t_row.scope_hash,
            t_row.request_hash,
            t_row.content_proof_hash,
            t_row.completion_hash,
            t_row.storage_object_key_hash,
            t_row.storage_object_key,
        )
        raw_t_key = t_row.storage_object_key

    forbidden = _advance(
        profile_id,
        t_body["id"],
        requester_id,
        key="phase-u-forbidden",
        extra={
            "checkpoint_generation": 3,
            "provider_item_id": "caller-item",
            "storage_key": "caller-key",
            "content": "caller-content",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io

    _foreign_org, foreign_requester, _foreign_approver = _seed_tenant("phase-u-foreign")
    wrong_tenant = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{t_body['id']}/checkpoint-generation-3-executions",
        headers=_headers(foreign_requester),
        json={"request_key": "phase-u-foreign", "reason": _ADVANCE_REASON},
    )
    assert wrong_tenant.status_code == 404
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io

    advanced = _advance(profile_id, t_body["id"], requester_id, key="phase-u-advance")
    assert advanced.status_code == 201, advanced.text
    body = advanced.json()
    assert body["status"] == "completed"
    assert body["result_status"] == "checkpoint_generation_3_advanced"
    assert body["predecessor_checkpoint_generation"] == 2
    assert body["candidate_generation"] == 3
    assert body["successor_checkpoint_generation"] == 3
    assert body["successor_checkpoint_kind"] == "remote_file_snapshot_successor_v1"
    assert body["checkpoint_created"] is True
    assert body["checkpoint_advanced"] is True
    assert body["checkpoint_generation_3_advance_completed"] is True
    for field in (
        "provider_client_constructed",
        "exact_item_metadata_read_performed",
        "remote_content_transiently_observed",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "durable_content_staged",
        "sync_executed",
        "subscription_created",
        "evidence_admitted",
        "document_created",
        "claim_mutated",
    ):
        assert body[field] is False
    serialized = json.dumps(body, sort_keys=True)
    assert raw_t_key not in serialized
    assert "storage_object_key" not in body
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-3-executions/{body['id']}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == ["requested", "completed"]
    assert receipt_rows[0]["prior_receipt_hash"] is None
    assert receipt_rows[1]["prior_receipt_hash"] == receipt_rows[0]["receipt_hash"]
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-3-executions/{body['id']}",
        headers=_headers(requester_id),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["completion_hash"] == body["completion_hash"]
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io

    replay = _advance(profile_id, t_body["id"], requester_id, key="phase-u-advance")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io

    changed_replay = _advance(profile_id, t_body["id"], requester_id, key="phase-u-changed-replay")
    assert changed_replay.status_code == 409
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io

    with TestingSessionLocal() as db:
        r_row = db.get(ExternalDocumentSourceCheckpointGenerationExecution, UUID(r_body["id"]))
        t_row = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(t_body["id"]))
        assert r_row is not None and t_row is not None
        assert (r_row.successor_checkpoint_state_hash, r_row.completion_hash) == r_facts
        assert (
            t_row.scope_hash,
            t_row.request_hash,
            t_row.content_proof_hash,
            t_row.completion_hash,
            t_row.storage_object_key_hash,
            t_row.storage_object_key,
        ) == t_facts
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceCheckpointGeneration3Execution).count() == 1
        assert db.query(ExternalDocumentSourceCheckpointGeneration3Receipt).count() == 2
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "EXTERNAL_DOCUMENT_SOURCE_CHECKPOINT_GENERATION_3_ADVANCED")
            .one()
        )
        audit_text = json.dumps({"new": audit.new_values, "details": audit.details}, sort_keys=True)
        assert raw_t_key not in audit_text
        assert "caller-token" not in audit_text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceCheckpointGeneration3Execution, UUID(body["id"]))
        assert row is not None
        original_state = row.successor_checkpoint_state_hash
        row.successor_checkpoint_state_hash = "f" * 64
        db.commit()
    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-3-executions/{body['id']}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io
    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceCheckpointGeneration3Execution, UUID(body["id"]))
        assert row is not None
        row.successor_checkpoint_state_hash = original_state
        db.commit()


def test_phase_u_upstream_t_tamper_fails_closed_without_io() -> None:
    (
        requester_id,
        profile_id,
        _binding_id,
        _checkpoint,
        _change,
        _q_body,
        _r_body,
        _s_body,
        t_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        t_adapter,
        store,
    ) = _completed_phase_t()
    before_io = _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store)
    with TestingSessionLocal() as db:
        t_row = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(t_body["id"]))
        assert t_row is not None
        t_row.content_proof_hash = "a" * 64
        db.commit()
    response = _advance(profile_id, t_body["id"], requester_id, key="phase-u-upstream-tamper")
    assert response.status_code == 409
    assert _io_counts(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == before_io
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceCheckpointGeneration3Execution).count() == 0
