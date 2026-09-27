from __future__ import annotations

import hashlib
import json
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpCheckpointAdvancement,
    ExternalDocumentSourceSftpCheckpointAdvancementReceipt,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from app.modules.external_document_sources.sftp_successor_restaging_models import (
    ExternalDocumentSourceSftpSuccessorRestaging,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_file_content_proof import (
    _BODY_MARKER,
    _FileReadAdapter,
)
from tests.test_external_document_source_sftp_quarantine_staging import (
    _QuarantineStore,
    _STORAGE_SECRET,
    _STORAGE_URL,
)
from tests.test_external_document_source_sftp_successor_restaging import (
    _changed_phase_l,
    _restage,
    setup_function as _m_setup,
    teardown_function as _m_teardown,
)


_REASON = (
    "Advance only the exact integrity-valid Phase 17.6-M successor candidate "
    "into generation-2 checkpoint custody without any provider or storage I/O."
)


def setup_function() -> None:
    _m_setup()


def teardown_function() -> None:
    _m_teardown()


def _completed_phase_m(seed: str):
    chain = _changed_phase_l(seed)
    successor_body = b"n" * chain["baseline"]["byte_size"] + b"x"
    read_adapter = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)
    response = _restage(chain, key=f"{seed}-restage")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "successor_staged_verified"
    chain["restaging_id"] = response.json()["id"]
    chain["successor_body"] = successor_body
    chain["read_adapter"] = read_adapter
    chain["store"] = store
    return chain


def _advance(
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
            f"sftp-successor-restaging-executions/{chain['restaging_id']}/"
            "checkpoint-advancements"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_sftp_checkpoint_advancement_is_control_plane_only_and_idempotent() -> None:
    chain = _completed_phase_m("sftp-cp-advance")
    read_calls_before = len(chain["read_adapter"].calls)
    put_calls_before = chain["store"].put_calls

    with TestingSessionLocal() as db:
        predecessor = db.get(
            ExternalDocumentSourceSftpCheckpoint,
            UUID(chain["checkpoint_id"]),
        )
        predecessor_state = predecessor.checkpoint_state_hash
        predecessor_completion = predecessor.completion_hash
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        candidate = db.get(
            ExternalDocumentSourceSftpSuccessorRestaging,
            UUID(chain["restaging_id"]),
        )
        expected_digest = candidate.successor_content_sha256
        expected_size = candidate.successor_content_byte_count
        expected_storage_hash = candidate.storage_object_key_hash

    response = _advance(chain, key="n2")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["result_status"] == "checkpoint_advanced"
    assert body["predecessor_checkpoint_generation"] == 1
    assert body["candidate_generation"] == 2
    assert body["successor_checkpoint_generation"] == 2
    assert body["content_sha256"] == expected_digest
    assert body["content_byte_count"] == expected_size
    assert body["storage_object_key_hash"] == expected_storage_hash
    assert body["checkpoint_created"] is True
    assert body["checkpoint_advanced"] is True

    for field in (
        "secret_resolution_performed", "provider_network_performed",
        "ssh_transport_performed", "host_key_verification_performed",
        "authentication_performed", "sftp_session_opened",
        "remote_content_transiently_observed", "remote_list_performed",
        "remote_stat_performed", "remote_read_performed", "remote_write_performed",
        "remote_rename_performed", "remote_delete_performed",
        "storage_read_performed", "storage_write_performed",
        "storage_reconciliation_performed", "storage_delete_performed",
        "storage_copy_performed", "durable_content_staged",
        "evidence_admitted", "document_created", "processing_enqueued",
        "ai_executed", "claim_mutated",
    ):
        assert body[field] is False

    assert len(chain["read_adapter"].calls) == read_calls_before
    assert chain["store"].put_calls == put_calls_before

    replay = _advance(chain, key="n2")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    assert len(chain["read_adapter"].calls) == read_calls_before
    assert chain["store"].put_calls == put_calls_before

    conflict = _advance(chain, key="n3")
    assert conflict.status_code == 409, conflict.text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-checkpoint-advancements/{body['id']}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    assert [row["event_type"] for row in receipts.json()] == ["requested", "completed"]

    for forbidden_field in (
        "storage_object_key", "stored_etag", "destination_hostname",
        "remote_root_path", "content", "file_body", "credential",
    ):
        assert forbidden_field not in body
    for marker in (_BODY_MARKER, _STORAGE_SECRET, _STORAGE_URL):
        assert marker not in response.text

    with TestingSessionLocal() as db:
        predecessor = db.get(
            ExternalDocumentSourceSftpCheckpoint,
            UUID(chain["checkpoint_id"]),
        )
        assert predecessor.checkpoint_state_hash == predecessor_state
        assert predecessor.completion_hash == predecessor_completion
        assert predecessor.checkpoint_generation == 1
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpCheckpointAdvancement).count() == 1
        assert db.query(ExternalDocumentSourceSftpCheckpointAdvancementReceipt).count() == 2

        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_sftp_checkpoint_advancement",
            AuditLog.entity_id == UUID(body["id"]),
        ).one()
        audit_payload = json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert _BODY_MARKER not in audit_payload
        assert _STORAGE_SECRET not in audit_payload
        assert _STORAGE_URL not in audit_payload


def test_sftp_checkpoint_advancement_rejects_caller_authority_tenant_drift_and_tamper() -> None:
    chain = _completed_phase_m("sftp-cp-advance-boundary")

    forbidden = _advance(
        chain,
        key="deny",
        extra={
            "checkpoint_id": chain["checkpoint_id"],
            "generation": 99,
            "content_sha256": "0" * 64,
            "storage_object_key": "caller/key",
        },
    )
    assert forbidden.status_code == 422, forbidden.text

    _, other_requester, _, _ = _seed_tenant("sftp-cp-advance-other")
    wrong_tenant = _advance(
        chain,
        key="tenant",
        actor_id=other_requester,
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text

    with TestingSessionLocal() as db:
        candidate = db.get(
            ExternalDocumentSourceSftpSuccessorRestaging,
            UUID(chain["restaging_id"]),
        )
        original_completion = candidate.completion_hash
        candidate.completion_hash = "0" * 64
        db.commit()

    tampered_candidate = _advance(chain, key="bad")
    assert tampered_candidate.status_code == 409, tampered_candidate.text

    with TestingSessionLocal() as db:
        candidate = db.get(
            ExternalDocumentSourceSftpSuccessorRestaging,
            UUID(chain["restaging_id"]),
        )
        candidate.completion_hash = original_completion
        db.commit()

    created = _advance(chain, key="ok")
    assert created.status_code == 201, created.text
    advancement_id = UUID(created.json()["id"])

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceSftpCheckpointAdvancement, advancement_id)
        original_state = row.successor_checkpoint_state_hash
        row.successor_checkpoint_state_hash = "0" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-checkpoint-advancements/{advancement_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceSftpCheckpointAdvancement, advancement_id)
        row.successor_checkpoint_state_hash = original_state
        db.commit()
