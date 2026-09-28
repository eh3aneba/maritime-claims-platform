from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

import pytest

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
    ExternalDocumentSourceEvidenceFamilyBindingReceipt,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    _stable_sftp_source_item_hash,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers
from tests.test_external_document_source_sftp_evidence_admission_execution import (
    _authorized_phase_s,
    _enable_clean_admission,
    _execute,
    setup_function as _t_setup,
    teardown_function as _t_teardown,
)


_BIND_REASON = (
    "Bind this verified initial SFTP Evidence admission to its durable "
    "provider-neutral Document family without granting processing authority."
)


def setup_function() -> None:
    _t_setup()


def teardown_function() -> None:
    _t_teardown()


def _bind(
    chain: dict,
    execution_id: str,
    *,
    key: str,
    reason: str = _BIND_REASON,
    actor_id=None,
    extra: dict | None = None,
):
    payload = {
        "request_key": key,
        "reason": reason,
    }
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-evidence-admission-executions/{execution_id}/family-binding"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_phase_u_binds_initial_sftp_evidence_without_external_io_or_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, claim_id, authorization = _authorized_phase_s(
        "sftp-phase-u-success"
    )
    _enable_clean_admission(monkeypatch)

    admitted = _execute(
        chain,
        authorization["id"],
        key="u-admit-initial",
    )
    assert admitted.status_code == 201, admitted.text
    execution = admitted.json()
    document_id = UUID(execution["document_id"])

    provider_calls_before = len(adapter.calls)
    staged_heads_before = chain["p_store"].head_calls
    staged_gets_before = chain["p_store"].get_calls
    remote_reads_before = len(chain["p_read_adapter"].calls)

    response = _bind(
        chain,
        execution["id"],
        key="u-bind-initial",
    )
    assert response.status_code == 201, response.text
    body = response.json()

    expected_source_hash = _stable_sftp_source_item_hash(
        profile_id=UUID(chain["profile_id"]),
        relative_path_hash=authorization["authorized_relative_path_hash"],
    )
    assert body["provider_kind"] == "sftp"
    assert body["claim_id"] == str(claim_id)
    assert body["admission_execution_id"] is None
    assert body["sftp_admission_execution_id"] == execution["id"]
    assert body["initial_document_id"] == str(document_id)
    assert body["document_family_id"] == str(document_id)
    assert body["current_document_id"] == str(document_id)
    assert body["current_version_number"] == 1
    assert body["stable_source_item_hash"] == expected_source_hash
    assert body["source_projection_hash"] == execution["fresh_projection_hash"]
    assert (
        body["source_observation_completion_hash"]
        == execution["observation_completion_hash"]
    )
    assert body["admission_completion_hash"] == execution["completion_hash"]
    assert body["admitted_content_sha256"] == execution["document_file_hash"]
    assert body["admitted_byte_count"] == execution["document_file_size_bytes"]
    assert body["admitted_provider_version_hash"] is None

    for field in (
        "upstream_admission_verified",
        "stable_source_identity_derived",
        "document_family_verified",
        "version_baseline_recorded",
    ):
        assert body[field] is True
    for field in (
        "provider_client_constructed",
        "remote_metadata_read_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "document_created",
        "document_mutated",
        "processing_enqueued",
        "content_extracted",
        "ai_executed",
        "claim_mutated",
        "checkpoint_advanced",
        "background_sync_started",
    ):
        assert body[field] is False

    assert len(adapter.calls) == provider_calls_before
    assert chain["p_store"].head_calls == staged_heads_before
    assert chain["p_store"].get_calls == staged_gets_before
    assert len(chain["p_read_adapter"].calls) == remote_reads_before

    for forbidden_field in (
        "remote_path",
        "remote_root_path",
        "storage_key",
        "storage_object_key",
        "credential",
        "content",
    ):
        assert forbidden_field not in body

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.processing_status == DocumentProcessingStatus.UPLOADED
        assert document.document_family_id == document.id
        assert document.version_number == 1
        assert document.is_current is True
        assert (
            db.query(DocumentProcessingJob)
            .filter(DocumentProcessingJob.document_id == document_id)
            .count()
            == 0
        )
        assert db.query(ExternalDocumentSourceEvidenceFamilyBinding).count() == 1
        assert (
            db.query(ExternalDocumentSourceEvidenceFamilyBindingReceipt).count()
            == 1
        )
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action
                == "BIND_EXTERNAL_DOCUMENT_SOURCE_EVIDENCE_FAMILY"
            )
            .all()
        )
        assert len(audits) == 1
        audit_text = json.dumps(
            [{"new": row.new_values, "details": row.details} for row in audits],
            sort_keys=True,
        )
        assert "remote_path" not in audit_text
        assert "storage_key" not in audit_text
        assert "credential" not in audit_text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"evidence-family-bindings/{body['id']}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    assert len(receipts.json()) == 1
    assert receipts.json()[0]["event_type"] == "bound"

    replay = _bind(
        chain,
        execution["id"],
        key="u-bind-initial",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    assert len(adapter.calls) == provider_calls_before
    assert chain["p_store"].get_calls == staged_gets_before

    duplicate = _bind(
        chain,
        execution["id"],
        key="u-bind-initial-duplicate",
    )
    assert duplicate.status_code == 409, duplicate.text


def test_phase_u_sftp_source_identity_is_stable_and_profile_path_scoped() -> None:
    profile_a = uuid4()
    profile_b = uuid4()
    path_a = hashlib.sha256(b"evidence/report.pdf").hexdigest()
    path_b = hashlib.sha256(b"evidence/other.pdf").hexdigest()

    first = _stable_sftp_source_item_hash(
        profile_id=profile_a,
        relative_path_hash=path_a,
    )
    same = _stable_sftp_source_item_hash(
        profile_id=profile_a,
        relative_path_hash=path_a,
    )
    other_path = _stable_sftp_source_item_hash(
        profile_id=profile_a,
        relative_path_hash=path_b,
    )
    other_profile = _stable_sftp_source_item_hash(
        profile_id=profile_b,
        relative_path_hash=path_a,
    )

    assert first == same
    assert first != other_path
    assert first != other_profile


def test_phase_u_sftp_binding_fails_closed_when_authorization_lineage_is_tampered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, _adapter, _r_body, _claim_id, authorization = _authorized_phase_s(
        "sftp-phase-u-tamper"
    )
    _enable_clean_admission(monkeypatch)
    admitted = _execute(
        chain,
        authorization["id"],
        key="u-tamper-admit",
    )
    assert admitted.status_code == 201, admitted.text

    bound = _bind(
        chain,
        admitted.json()["id"],
        key="u-tamper-bind",
    )
    assert bound.status_code == 201, bound.text

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
            UUID(authorization["id"]),
        )
        assert row is not None
        row.authorized_relative_path_hash = "f" * 64
        db.commit()

    fetched = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"evidence-family-bindings/{bound.json()['id']}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert fetched.status_code == 409, fetched.text
