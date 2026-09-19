import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
    ExternalDocumentSourceEvidenceFamilyBindingReceipt,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
)
from app.modules.processing.models import (
    DocumentProcessingJob,
    DocumentTextExtraction,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.processing.service import (
    ExternalEvidenceProcessingAuthorizationRequired,
    enqueue_processing_job,
    process_job,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_discovery import _headers
from tests.test_external_document_source_evidence_admission_authorization import (
    _authorize,
    _seed_claim,
    _unchanged_phase_v,
)
from tests.test_external_document_source_evidence_admission_execution import (
    _enable_clean_admission,
    _execute,
    setup_function as _phase_x_setup,
    teardown_function as _phase_x_teardown,
)

_BINDING_REASON = (
    "Bind this verified Phase-X external Evidence admission to its durable source-item "
    "Document family baseline without granting downstream processing authority."
)


def setup_function() -> None:
    _phase_x_setup()


def teardown_function() -> None:
    _phase_x_teardown()


def _admit(monkeypatch: pytest.MonkeyPatch, suffix: str):
    upstream, metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    store = upstream[14]
    claim_id = _seed_claim(actor_id, f"y-{suffix}")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key=f"phase-y-auth-{suffix}",
    )
    assert authorization.status_code == 201, authorization.text
    _enable_clean_admission(monkeypatch)
    admitted = _execute(
        profile_id,
        authorization.json()["id"],
        actor_id,
        key=f"phase-y-admit-{suffix}",
    )
    assert admitted.status_code == 201, admitted.text
    return (
        actor_id,
        profile_id,
        claim_id,
        admitted.json(),
        metadata_adapter,
        store,
    )


def _bind(
    profile_id: str,
    execution_id: str,
    actor_id,
    *,
    key: str,
    reason: str = _BINDING_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-admission-executions/{execution_id}/family-binding"
        ),
        headers=_headers(actor_id),
        json=payload,
    )


def test_phase_y_binds_one_admitted_source_item_without_io_or_document_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, execution, metadata_adapter, store = _admit(
        monkeypatch,
        "success",
    )
    document_id = UUID(execution["document_id"])

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        original = {
            "document_family_id": document.document_family_id,
            "version_number": document.version_number,
            "is_current": document.is_current,
            "file_hash": document.file_hash,
            "file_size_bytes": document.file_size_bytes,
            "storage_key": document.storage_key,
            "processing_status": document.processing_status,
        }
        observation = db.get(
            ExternalDocumentSourceGeneration3ChangeDetectionExecution,
            UUID(execution["generation_3_change_detection_execution_id"]),
        )
        assert observation is not None
        expected_source_hash = observation.observed_provider_item_id_hash
        binding_count_before = db.query(
            ExternalDocumentSourceEvidenceFamilyBinding
        ).count()

    metadata_calls_before = metadata_adapter.calls
    storage_gets_before = store.get_calls

    forbidden = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-forbidden",
        extra={
            "provider_item_id": "caller-provider-id",
            "storage_key": "caller/storage/key",
            "provider_url": "https://provider.example/item",
            "content": "caller-content",
            "access_token": "caller-token",
            "document_family_id": str(uuid4()),
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert metadata_adapter.calls == metadata_calls_before
    assert store.get_calls == storage_gets_before

    response = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-bind-success",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["claim_id"] == str(claim_id)
    assert body["admission_execution_id"] == execution["id"]
    assert body["initial_document_id"] == execution["document_id"]
    assert body["document_family_id"] == execution["document_id"]
    assert body["current_document_id"] == execution["document_id"]
    assert body["current_version_number"] == 1
    assert body["stable_source_item_hash"] == expected_source_hash
    assert body["source_projection_hash"] == execution["fresh_projection_hash"]
    assert body["admission_completion_hash"] == execution["completion_hash"]
    assert body["admitted_content_sha256"] == execution["document_file_hash"]
    assert body["admitted_byte_count"] == execution["document_file_size_bytes"]

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

    assert metadata_adapter.calls == metadata_calls_before
    assert store.get_calls == storage_gets_before

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.document_family_id == original["document_family_id"]
        assert document.version_number == original["version_number"]
        assert document.is_current == original["is_current"]
        assert document.file_hash == original["file_hash"]
        assert document.file_size_bytes == original["file_size_bytes"]
        assert document.storage_key == original["storage_key"]
        assert document.processing_status == original["processing_status"]
        assert (
            db.query(ExternalDocumentSourceEvidenceFamilyBinding).count()
            == binding_count_before + 1
        )
        assert db.query(ExternalDocumentSourceEvidenceFamilyBindingReceipt).count() == 1

        audits = db.query(AuditLog).filter(
            AuditLog.action == "BIND_EXTERNAL_DOCUMENT_SOURCE_EVIDENCE_FAMILY"
        ).all()
        assert len(audits) == 1
        audit_text = json.dumps(
            [{"new": row.new_values, "details": row.details} for row in audits],
            sort_keys=True,
        )
        for forbidden_text in (
            "provider_item_id",
            "storage_key",
            "access_token",
            "client_secret",
            "raw_content",
        ):
            assert forbidden_text not in audit_text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/evidence-family-bindings/{body['id']}/receipts"
        ),
        headers=_headers(actor_id),
    )
    assert receipts.status_code == 200, receipts.text
    assert len(receipts.json()) == 1
    assert receipts.json()[0]["event_type"] == "bound"

    replay = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-bind-success",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    assert metadata_adapter.calls == metadata_calls_before
    assert store.get_calls == storage_gets_before

    altered = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-bind-success",
        reason=(
            "Attempt to alter a completed external source Evidence-family binding "
            "after the immutable receipt was committed."
        ),
    )
    assert altered.status_code == 409, altered.text


def test_phase_y_rejects_second_binding_for_same_source_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, execution, metadata_adapter, store = _admit(
        monkeypatch,
        "duplicate",
    )
    first = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-bind-first",
    )
    assert first.status_code == 201, first.text

    metadata_calls = metadata_adapter.calls
    storage_gets = store.get_calls
    second = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-bind-second",
    )
    assert second.status_code == 409, second.text
    assert "already bound" in second.json()["detail"].lower()
    assert metadata_adapter.calls == metadata_calls
    assert store.get_calls == storage_gets


def test_phase_y_rejects_soft_deleted_claim_and_wrong_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, execution, _adapter, _store = _admit(
        monkeypatch,
        "deleted",
    )

    wrong_profile = _bind(
        str(uuid4()),
        execution["id"],
        actor_id,
        key="phase-y-wrong-profile",
    )
    assert wrong_profile.status_code == 404, wrong_profile.text

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        assert claim is not None
        claim.deleted_at = datetime.now(UTC)
        db.commit()

    deleted = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-deleted-claim",
    )
    assert deleted.status_code == 404, deleted.text

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceEvidenceFamilyBinding).count() == 0


def test_phase_y_rejects_tampered_document_family_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, execution, _adapter, _store = _admit(
        monkeypatch,
        "tamper",
    )
    document_id = UUID(execution["document_id"])

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        document.document_family_id = uuid4()
        db.commit()

    rejected = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-tampered-document",
    )
    assert rejected.status_code == 409, rejected.text
    assert "baseline" in rejected.json()["detail"].lower()

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceEvidenceFamilyBinding).count() == 0

def test_phase_y_binding_preserves_processing_release_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, claim_id, execution, _adapter, _store = _admit(
        monkeypatch,
        "processing-boundary",
    )
    bound = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key="phase-y-bind-processing-boundary",
    )
    assert bound.status_code == 201, bound.text
    document_id = UUID(execution["document_id"])

    retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert retry.status_code == 409, retry.text
    assert "downstream processing authority" in retry.json()["detail"].lower()

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.processing_status == DocumentProcessingStatus.UPLOADED

        with pytest.raises(ExternalEvidenceProcessingAuthorizationRequired):
            enqueue_processing_job(
                db,
                document=document,
                requested_by_id=actor_id,
                job_type=ProcessingJobType.EXTRACT_TEXT,
            )
        db.rollback()

        document = db.get(Document, document_id)
        assert document is not None
        security_job = enqueue_processing_job(
            db,
            document=document,
            requested_by_id=actor_id,
            job_type=ProcessingJobType.MALWARE_RESCAN,
        )
        assert security_job.job_type == ProcessingJobType.MALWARE_RESCAN
        db.rollback()

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        legacy_job = DocumentProcessingJob(
            organization_id=document.organization_id,
            claim_id=claim_id,
            document_id=document.id,
            requested_by_id=actor_id,
            job_type=ProcessingJobType.EXTRACT_TEXT,
            status=ProcessingJobStatus.RUNNING,
            max_attempts=3,
            attempt_count=1,
            available_at=datetime.now(UTC),
        )
        db.add(legacy_job)
        db.commit()
        db.refresh(legacy_job)

        process_job(db, job=legacy_job)

        db.refresh(legacy_job)
        db.refresh(document)
        assert legacy_job.status == ProcessingJobStatus.FAILED
        assert legacy_job.result == {
            "blocked": True,
            "reason": "processing_authorization_required",
        }
        assert document.processing_status == DocumentProcessingStatus.UPLOADED
        assert (
            db.query(DocumentTextExtraction)
            .filter(DocumentTextExtraction.document_id == document_id)
            .count()
            == 0
        )

