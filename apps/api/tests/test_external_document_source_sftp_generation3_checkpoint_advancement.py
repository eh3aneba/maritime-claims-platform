from __future__ import annotations

import json
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpCheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    ExternalDocumentSourceSftpGeneration3Restaging,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_file_content_proof import (
    _BODY_MARKER,
    _FileReadAdapter,
)
from tests.test_external_document_source_sftp_generation3_restaging import (
    _changed_phase_o,
    _restage3,
    setup_function as _p_setup,
    teardown_function as _p_teardown,
)
from tests.test_external_document_source_sftp_quarantine_staging import (
    _QuarantineStore,
    _STORAGE_SECRET,
    _STORAGE_URL,
)


_REASON = (
    "Advance the exact integrity-valid generation-3 SFTP quarantine candidate "
    "into checkpoint custody without any provider or object-store I/O."
)


def setup_function() -> None:
    _p_setup()


def teardown_function() -> None:
    _p_teardown()


def _completed_phase_p(seed: str):
    chain = _changed_phase_o(seed)
    body = b"q" * chain["o_observed_size"]
    read_adapter = _FileReadAdapter(content=body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)
    response = _restage3(chain, key=f"{seed}-p3")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "generation3_staged_verified"
    chain["generation3_restaging_id"] = response.json()["id"]
    chain["generation3_body"] = body
    chain["p_read_adapter"] = read_adapter
    chain["p_store"] = store
    return chain


def _advance3(
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
            f"sftp-generation-3-restaging-executions/{chain['generation3_restaging_id']}/"
            "checkpoint-advancements"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_generation3_checkpoint_advancement_is_zero_io_and_idempotent() -> None:
    chain = _completed_phase_p("sftp-g3-cp")
    read_calls_before = len(chain["p_read_adapter"].calls)
    put_before = chain["p_store"].put_calls
    head_before = chain["p_store"].head_calls
    get_before = chain["p_store"].get_calls

    with TestingSessionLocal() as db:
        predecessor = db.get(
            ExternalDocumentSourceSftpCheckpointAdvancement,
            UUID(chain["advancement_id"]),
        )
        candidate = db.get(
            ExternalDocumentSourceSftpGeneration3Restaging,
            UUID(chain["generation3_restaging_id"]),
        )
        predecessor_state = predecessor.successor_checkpoint_state_hash
        predecessor_completion = predecessor.completion_hash
        candidate_completion = candidate.completion_hash
        expected_digest = candidate.content_sha256
        expected_size = candidate.content_byte_count
        expected_storage_hash = candidate.storage_object_key_hash
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    response = _advance3(chain, key="q3")
    assert response.status_code == 201, response.text
    body = response.json()
    advancement_id = body["id"]

    assert body["status"] == "completed"
    assert body["result_status"] == "checkpoint_advanced"
    assert body["predecessor_checkpoint_generation"] == 2
    assert body["candidate_generation"] == 3
    assert body["successor_checkpoint_generation"] == 3
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

    assert len(chain["p_read_adapter"].calls) == read_calls_before
    assert chain["p_store"].put_calls == put_before
    assert chain["p_store"].head_calls == head_before
    assert chain["p_store"].get_calls == get_before

    replay = _advance3(chain, key="q3")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == advancement_id
    assert len(chain["p_read_adapter"].calls) == read_calls_before
    assert chain["p_store"].put_calls == put_before
    assert chain["p_store"].head_calls == head_before
    assert chain["p_store"].get_calls == get_before

    second = _advance3(chain, key="q3-second")
    assert second.status_code == 409, second.text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-generation3-checkpoint-advancements/{advancement_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    assert [r["event_type"] for r in receipts.json()] == ["requested", "completed"]

    for forbidden_field in (
        "storage_object_key", "stored_etag", "destination_hostname",
        "remote_root_path", "effective_remote_path", "reference_name",
        "content", "file_body", "credential",
    ):
        assert forbidden_field not in body
    for marker in (_BODY_MARKER, _STORAGE_SECRET, _STORAGE_URL):
        assert marker not in response.text

    with TestingSessionLocal() as db:
        predecessor = db.get(
            ExternalDocumentSourceSftpCheckpointAdvancement,
            UUID(chain["advancement_id"]),
        )
        candidate = db.get(
            ExternalDocumentSourceSftpGeneration3Restaging,
            UUID(chain["generation3_restaging_id"]),
        )
        assert predecessor.successor_checkpoint_state_hash == predecessor_state
        assert predecessor.completion_hash == predecessor_completion
        assert predecessor.successor_checkpoint_generation == 2
        assert candidate.completion_hash == candidate_completion
        assert candidate.candidate_generation == 3
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement).count() == 1
        assert db.query(ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt).count() == 2

        audit = db.query(AuditLog).filter(
            AuditLog.entity_type
            == "external_document_source_sftp_generation3_checkpoint_advancement",
            AuditLog.entity_id == UUID(advancement_id),
        ).one()
        audit_payload = json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert candidate.storage_object_key not in audit_payload
        assert candidate.stored_etag not in audit_payload
        assert _BODY_MARKER not in audit_payload
        assert _STORAGE_SECRET not in audit_payload
        assert _STORAGE_URL not in audit_payload


def test_generation3_checkpoint_advancement_rejects_authority_tenant_and_tamper() -> None:
    chain = _completed_phase_p("sftp-g3-cp-boundary")

    forbidden = _advance3(
        chain,
        key="deny",
        extra={
            "generation": 99,
            "digest": "0" * 64,
            "storage_key": "caller/storage",
            "hostname": "caller.invalid",
            "content": "caller-content",
            "credential": "caller-secret",
        },
    )
    assert forbidden.status_code == 422, forbidden.text

    _, other_requester, _, _ = _seed_tenant("sftp-g3-cp-other")
    wrong_tenant = _advance3(chain, key="tenant", actor_id=other_requester)
    assert wrong_tenant.status_code == 404, wrong_tenant.text

    with TestingSessionLocal() as db:
        candidate = db.get(
            ExternalDocumentSourceSftpGeneration3Restaging,
            UUID(chain["generation3_restaging_id"]),
        )
        original_completion = candidate.completion_hash
        candidate.completion_hash = "0" * 64
        db.commit()

    calls_before = len(chain["p_read_adapter"].calls)
    put_before = chain["p_store"].put_calls
    tampered_upstream = _advance3(chain, key="bad")
    assert tampered_upstream.status_code == 409, tampered_upstream.text
    assert len(chain["p_read_adapter"].calls) == calls_before
    assert chain["p_store"].put_calls == put_before

    with TestingSessionLocal() as db:
        candidate = db.get(
            ExternalDocumentSourceSftpGeneration3Restaging,
            UUID(chain["generation3_restaging_id"]),
        )
        candidate.completion_hash = original_completion
        db.commit()

    created = _advance3(chain, key="ok")
    assert created.status_code == 201, created.text
    advancement_id = UUID(created.json()["id"])

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt)
            .filter(
                ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt.advancement_id
                == advancement_id,
                ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt.sequence_number
                == 1,
            )
            .one()
        )
        original_receipt_hash = receipt.receipt_hash
        receipt.receipt_hash = "0" * 64
        db.commit()

    tampered_receipt = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-generation3-checkpoint-advancements/{advancement_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt)
            .filter(
                ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt.advancement_id
                == advancement_id,
                ExternalDocumentSourceSftpGeneration3CheckpointAdvancementReceipt.sequence_number
                == 1,
            )
            .one()
        )
        receipt.receipt_hash = original_receipt_hash
        row = db.get(
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
            advancement_id,
        )
        original_state = row.successor_checkpoint_state_hash
        row.successor_checkpoint_state_hash = "0" * 64
        db.commit()

    tampered_execution = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-generation3-checkpoint-advancements/{advancement_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered_execution.status_code == 409, tampered_execution.text

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
            advancement_id,
        )
        row.successor_checkpoint_state_hash = original_state
        db.commit()
