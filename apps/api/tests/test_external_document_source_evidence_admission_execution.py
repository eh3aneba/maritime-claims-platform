import json
from uuid import UUID

import pytest

import app.modules.external_document_sources.evidence_admission_execution_service as admission_service
from app.modules.audit.models import AuditLog
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import Document, DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
    ExternalDocumentSourceEvidenceAdmissionExecutionReceipt,
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
    setup_function as _phase_w_setup,
    teardown_function as _phase_w_teardown,
)
from tests.test_external_document_source_generation_3_change_detection import _observe

_EXECUTION_REASON = (
    "Admit this exact human-authorized external file version into the Claim Evidence record after fresh currentness, integrity and malware verification."
)


def setup_function() -> None:
    _phase_w_setup()


def teardown_function() -> None:
    _phase_w_teardown()


def _enable_clean_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admission_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(admission_service, "validate_file_signature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        admission_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(verdict=MalwareScanVerdict.CLEAN),
    )


def _execute(profile_id: str, authorization_id: str, actor_id, *, key: str, reason: str = _EXECUTION_REASON, extra: dict | None = None):
    payload = {
        "request_key": key,
        "reason": reason,
        "document_type": "External survey evidence",
        "confidentiality_level": "confidential",
    }
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/evidence-admission-authorizations/{authorization_id}/executions",
        headers=_headers(actor_id),
        json=payload,
    )


def test_phase_x_consumes_one_authorization_and_creates_one_document_without_downstream_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream, metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    store = upstream[14]
    claim_id = _seed_claim(actor_id, "x-success")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key="phase-x-auth-success",
    )
    assert authorization.status_code == 201, authorization.text
    authorization_body = authorization.json()
    _enable_clean_admission(monkeypatch)

    with TestingSessionLocal() as db:
        document_count_before = db.query(Document).count()
    metadata_calls_before = metadata_adapter.calls
    storage_gets_before = store.get_calls

    forbidden = _execute(
        profile_id,
        authorization_body["id"],
        actor_id,
        key="phase-x-forbidden",
        extra={
            "provider_item_id": "caller-controlled",
            "storage_key": "caller/storage/key",
            "content": "caller-content",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert metadata_adapter.calls == metadata_calls_before
    assert store.get_calls == storage_gets_before

    response = _execute(
        profile_id,
        authorization_body["id"],
        actor_id,
        key="phase-x-admit-success",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    execution_id = body["id"]
    document_id = body["document_id"]
    assert body["status"] == "admitted"
    assert body["authorization_id"] == authorization_body["id"]
    assert body["claim_id"] == str(claim_id)
    assert body["fresh_projection_hash"] == authorization_body["authorized_projection_hash"]
    assert body["candidate_content_proof_hash"] == authorization_body["candidate_content_proof_hash"]
    assert body["document_file_hash"] == body["staged_content_sha256"]
    assert body["document_file_size_bytes"] == body["staged_content_byte_count"]
    assert metadata_adapter.calls == metadata_calls_before + 1
    assert store.get_calls > storage_gets_before

    for field in (
        "upstream_authorization_verified",
        "authorization_single_use_consumed",
        "latest_generation_3_observation_confirmed",
        "fresh_exact_item_metadata_read_performed",
        "fresh_remote_version_current",
        "staged_content_integrity_verified",
        "malware_scan_completed",
        "canonical_document_write_completed",
        "document_created",
        "evidence_admitted",
        "admission_execution_performed",
    ):
        assert body[field] is True
    for field in (
        "remote_list_performed",
        "remote_content_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "staged_storage_write_performed",
        "staged_storage_delete_performed",
        "content_parsed",
        "content_extracted",
        "processing_enqueued",
        "claim_mutated",
        "checkpoint_advanced",
        "background_sync_started",
    ):
        assert body[field] is False

    for forbidden_field in (
        "provider_item_id",
        "storage_key",
        "access_token",
        "client_secret",
        "raw_content",
    ):
        assert forbidden_field not in body

    with TestingSessionLocal() as db:
        assert db.query(Document).count() == document_count_before + 1
        document = db.get(Document, UUID(document_id))
        assert document is not None
        assert document.claim_id == claim_id
        assert document.processing_status == DocumentProcessingStatus.UPLOADED
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert document.source_admission_note == _EXECUTION_REASON[:1000]
        assert db.query(ExternalDocumentSourceEvidenceAdmissionExecution).count() == 1
        assert db.query(ExternalDocumentSourceEvidenceAdmissionExecutionReceipt).count() == 1
        audits = db.query(AuditLog).filter(
            AuditLog.action == "ADMIT_EXTERNAL_DOCUMENT_SOURCE_TO_EVIDENCE"
        ).all()
        assert len(audits) == 1
        audit_text = json.dumps(
            [{"new": row.new_values, "details": row.details} for row in audits], sort_keys=True
        )
        assert "provider_item_id" not in audit_text
        assert "storage_key" not in audit_text

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/evidence-admission-executions/{execution_id}/receipts",
        headers=_headers(actor_id),
    )
    assert receipts.status_code == 200, receipts.text
    assert len(receipts.json()) == 1
    assert receipts.json()[0]["event_type"] == "admitted"

    metadata_calls_after = metadata_adapter.calls
    storage_gets_after = store.get_calls
    replay = _execute(
        profile_id,
        authorization_body["id"],
        actor_id,
        key="phase-x-admit-success",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert metadata_adapter.calls == metadata_calls_after
    assert store.get_calls == storage_gets_after

    changed_replay = _execute(
        profile_id,
        authorization_body["id"],
        actor_id,
        key="phase-x-admit-success",
        reason="Attempt to alter a completed single-use external Evidence admission execution after it was committed.",
    )
    assert changed_replay.status_code == 409, changed_replay.text


def test_phase_x_rejects_stale_authorization_before_storage_or_document_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream, metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    u_body = upstream[9]
    store = upstream[14]
    claim_id = _seed_claim(actor_id, "x-stale")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key="phase-x-auth-stale",
    )
    assert authorization.status_code == 201, authorization.text
    _enable_clean_admission(monkeypatch)

    newer = _observe(
        profile_id,
        u_body["id"],
        actor_id,
        key="phase-x-newer-observation",
    )
    assert newer.status_code == 201, newer.text
    assert newer.json()["result_status"] == "unchanged"

    with TestingSessionLocal() as db:
        documents_before = db.query(Document).count()
    metadata_calls_before = metadata_adapter.calls
    storage_gets_before = store.get_calls
    rejected = _execute(
        profile_id,
        authorization.json()["id"],
        actor_id,
        key="phase-x-stale-execution",
    )
    assert rejected.status_code == 409, rejected.text
    assert "stale" in rejected.json()["detail"].lower()
    assert metadata_adapter.calls == metadata_calls_before
    assert store.get_calls == storage_gets_before
    with TestingSessionLocal() as db:
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceEvidenceAdmissionExecution).count() == 0


def _admit_phase_x_document_for_processing_guard(monkeypatch: pytest.MonkeyPatch):
    upstream, _metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    claim_id = _seed_claim(actor_id, "x-processing-guard")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key="phase-x-auth-processing-guard",
    )
    assert authorization.status_code == 201, authorization.text
    _enable_clean_admission(monkeypatch)
    admitted = _execute(
        profile_id,
        authorization.json()["id"],
        actor_id,
        key="phase-x-exec-processing-guard",
    )
    assert admitted.status_code == 201, admitted.text
    return actor_id, claim_id, UUID(admitted.json()["document_id"])


def test_phase_x_admitted_external_evidence_cannot_be_retried_into_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, claim_id, document_id = _admit_phase_x_document_for_processing_guard(monkeypatch)

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
        assert (
            db.query(DocumentProcessingJob)
            .filter(DocumentProcessingJob.document_id == document_id)
            .count()
            == 0
        )


def test_phase_x_processing_guard_blocks_content_jobs_but_allows_security_rescan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, _claim_id, document_id = _admit_phase_x_document_for_processing_guard(monkeypatch)

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None

        for job_type in (
            ProcessingJobType.EXTRACT_TEXT,
            ProcessingJobType.AI_EXTRACT_CE_REPORT,
            ProcessingJobType.AI_EXTRACT_ENGINE_LOG,
            ProcessingJobType.AI_EXTRACT_RUNNING_HOURS,
            ProcessingJobType.AI_EXTRACT_PMS_HISTORY,
            ProcessingJobType.AI_EXTRACT_WORKSHOP_REPORT,
            ProcessingJobType.AI_EXTRACT_QUOTATION,
            ProcessingJobType.AI_EXTRACT_INVOICE,
        ):
            with pytest.raises(ExternalEvidenceProcessingAuthorizationRequired):
                enqueue_processing_job(
                    db,
                    document=document,
                    requested_by_id=actor_id,
                    job_type=job_type,
                )
            db.rollback()

        security_job = enqueue_processing_job(
            db,
            document=document,
            requested_by_id=actor_id,
            job_type=ProcessingJobType.MALWARE_RESCAN,
        )
        assert security_job.job_type == ProcessingJobType.MALWARE_RESCAN
        db.rollback()



def test_phase_x_worker_revalidates_authority_for_preexisting_content_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, claim_id, document_id = _admit_phase_x_document_for_processing_guard(monkeypatch)

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None

        # Simulate a stale/legacy job that exists despite the enqueue-time guard.
        job = DocumentProcessingJob(
            organization_id=document.organization_id,
            claim_id=claim_id,
            document_id=document.id,
            requested_by_id=actor_id,
            job_type=ProcessingJobType.EXTRACT_TEXT,
            status=ProcessingJobStatus.RUNNING,
            max_attempts=3,
            attempt_count=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        process_job(db, job=job)

        db.refresh(job)
        db.refresh(document)
        assert job.status == ProcessingJobStatus.FAILED
        assert job.result == {
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


def test_phase_x_security_rescan_cannot_escalate_into_content_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, _claim_id, document_id = _admit_phase_x_document_for_processing_guard(monkeypatch)

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN

        security_job = enqueue_processing_job(
            db,
            document=document,
            requested_by_id=actor_id,
            job_type=ProcessingJobType.MALWARE_RESCAN,
        )
        db.commit()
        db.refresh(security_job)

        process_job(db, job=security_job)

        db.refresh(security_job)
        db.refresh(document)
        assert security_job.status == ProcessingJobStatus.COMPLETED
        assert document.processing_status == DocumentProcessingStatus.UPLOADED
        assert (
            db.query(DocumentTextExtraction)
            .filter(DocumentTextExtraction.document_id == document_id)
            .count()
            == 0
        )
        assert (
            db.query(DocumentProcessingJob)
            .filter(
                DocumentProcessingJob.document_id == document_id,
                DocumentProcessingJob.job_type != ProcessingJobType.MALWARE_RESCAN,
            )
            .count()
            == 0
        )



def test_phase_x_admitted_external_evidence_is_not_presented_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, claim_id, document_id = _admit_phase_x_document_for_processing_guard(monkeypatch)

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["operator_status"] == "uploaded"
    assert body["can_retry"] is False
    assert body["retry_recommended"] is False
    assert body["job"] is None
