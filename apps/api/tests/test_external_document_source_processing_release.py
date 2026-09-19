from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException

import app.modules.intelligence.router as intelligence_router
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    get_external_document_source_evidence_family_binding,
)
from app.modules.external_document_sources.processing_release_models import (
    ExternalDocumentSourceProcessingRelease,
    ExternalDocumentSourceProcessingReleaseReceipt,
)
from app.modules.external_document_sources.processing_release_service import (
    get_active_processing_release_for_document,
)
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
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
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_evidence_family_binding import (
    _admit,
    _bind,
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)

_RELEASE_REASON = (
    "Authorize deterministic local text extraction and OCR for this exact current "
    "external Evidence version without granting external AI authority."
)
_REVOKE_REASON = (
    "Revoke local processing authority for this exact external Evidence version "
    "before any further downstream content processing executes."
)


def setup_function() -> None:
    _phase_y_setup()


def teardown_function() -> None:
    _phase_y_teardown()


def _bound(monkeypatch: pytest.MonkeyPatch, suffix: str):
    actor_id, profile_id, claim_id, execution, _adapter, _store = _admit(
        monkeypatch,
        f"z-{suffix}",
    )
    binding = _bind(
        profile_id,
        execution["id"],
        actor_id,
        key=f"phase-z-bind-{suffix}",
    )
    assert binding.status_code == 201, binding.text
    return actor_id, profile_id, claim_id, execution, binding.json()


def _grant(claim_id, document_id, actor_id, *, key: str, reason: str = _RELEASE_REASON, extra=None):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/release",
        headers=_headers(actor_id),
        json=payload,
    )


def _revoke(claim_id, document_id, actor_id, *, key: str, reason: str = _REVOKE_REASON):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/release/revoke",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_phase_z_release_unlocks_local_processing_without_granting_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, _profile_id, claim_id, execution, binding = _bound(monkeypatch, "grant")
    document_id = UUID(execution["document_id"])

    blocked = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert blocked.status_code == 409, blocked.text

    forbidden = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-forbidden-input",
        extra={"ai_authorized": True, "provider_item_id": "caller-controlled"},
    )
    assert forbidden.status_code == 422, forbidden.text

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-release-grant",
    )
    assert release.status_code == 201, release.text
    body = release.json()
    assert body["status"] == "active"
    assert body["binding_id"] == binding["id"]
    assert body["document_id"] == str(document_id)
    assert body["document_family_id"] == execution["document_id"]
    assert body["document_version_number"] == 1
    assert body["local_text_processing_authorized"] is True
    assert body["ai_processing_authorized"] is False
    assert body["provider_io_performed"] is False
    assert body["storage_io_performed"] is False
    assert body["document_mutated"] is False
    assert body["processing_enqueued"] is False
    assert body["claim_mutated"] is False

    replay = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-release-grant",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["processing_release_required"] is False
    assert summary.json()["processing_release_status"] == "active"

    retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["job_type"] == ProcessingJobType.EXTRACT_TEXT.value

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        job = enqueue_processing_job(
            db,
            document=document,
            requested_by_id=actor_id,
            job_type=ProcessingJobType.EXTRACT_TEXT,
        )
        assert job.job_type == ProcessingJobType.EXTRACT_TEXT
        assert job.id == UUID(retry.json()["id"])
        db.rollback()

        # Z is not AI permission. The release itself remains explicitly non-AI.
        release_row = db.get(ExternalDocumentSourceProcessingRelease, UUID(body["id"]))
        assert release_row is not None
        assert release_row.ai_processing_authorized is False


def test_phase_z_worker_revalidates_release_and_revocation_blocks_queued_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, _profile_id, claim_id, execution, _binding = _bound(monkeypatch, "revoke")
    document_id = UUID(execution["document_id"])

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-release-before-worker",
    )
    assert release.status_code == 201, release.text

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        job = DocumentProcessingJob(
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
        db.add(job)
        db.commit()
        job_id = job.id

    revoked = _revoke(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-revoke-before-worker",
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    replay = _revoke(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-revoke-before-worker",
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == revoked.json()["id"]

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["processing_release_required"] is True
    assert summary.json()["processing_release_status"] == "revoked"
    assert summary.json()["can_retry"] is False

    with TestingSessionLocal() as db:
        job = db.get(DocumentProcessingJob, job_id)
        document = db.get(Document, document_id)
        assert job is not None
        assert document is not None

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
        release_row = db.get(
            ExternalDocumentSourceProcessingRelease,
            UUID(revoked.json()["id"]),
        )
        assert release_row is not None
        assert get_active_processing_release_for_document(
            db,
            document=db.get(Document, document_id),
        ) is None
        receipts = (
            db.query(ExternalDocumentSourceProcessingReleaseReceipt)
            .filter(
                ExternalDocumentSourceProcessingReleaseReceipt.release_id
                == release_row.id
            )
            .order_by(ExternalDocumentSourceProcessingReleaseReceipt.sequence_number)
            .all()
        )
        assert [row.event_type for row in receipts] == ["granted", "revoked"]


def test_phase_z_family_binding_remains_valid_after_processing_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, execution, binding = _bound(monkeypatch, "binding")
    document_id = UUID(execution["document_id"])

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        document.processing_status = DocumentProcessingStatus.PROCESSED
        db.commit()

    with TestingSessionLocal() as db:
        restored = get_external_document_source_evidence_family_binding(
            db,
            organization_id=db.get(Document, document_id).organization_id,
            profile_id=UUID(profile_id),
            binding_id=UUID(binding["id"]),
        )
        assert restored.id == UUID(binding["id"])


def test_phase_z_tampered_or_stale_release_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, _profile_id, claim_id, execution, _binding = _bound(monkeypatch, "tamper")
    document_id = UUID(execution["document_id"])

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-release-tamper",
    )
    assert release.status_code == 201, release.text
    release_id = UUID(release.json()["id"])

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceProcessingRelease, release_id)
        assert row is not None
        row.document_version_number = 2
        db.commit()

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["processing_release_required"] is True
    assert summary.json()["processing_release_status"] == "required"

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        with pytest.raises(ExternalDocumentSourceConflictError):
            get_active_processing_release_for_document(db, document=document)

@pytest.mark.parametrize("mutation", ["superseded", "deleted"])
def test_phase_z_release_fails_closed_when_document_ceases_to_be_current(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    actor_id, _profile_id, claim_id, execution, _binding = _bound(
        monkeypatch,
        f"stale-{mutation}",
    )
    document_id = UUID(execution["document_id"])

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key=f"phase-z-release-{mutation}",
    )
    assert release.status_code == 201, release.text

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        if mutation == "superseded":
            document.is_current = False
            document.superseded_at = datetime.now(UTC)
        else:
            document.deleted_at = datetime.now(UTC)
        db.commit()

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    if mutation == "deleted":
        assert summary.status_code == 404, summary.text
    else:
        assert summary.status_code == 200, summary.text
        assert summary.json()["processing_release_required"] is True
        assert summary.json()["processing_release_status"] == "required"
        assert summary.json()["can_retry"] is False

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        with pytest.raises(
            (ExternalDocumentSourceConflictError, ExternalEvidenceProcessingAuthorizationRequired)
        ):
            if mutation == "deleted":
                get_active_processing_release_for_document(db, document=document)
            else:
                enqueue_processing_job(
                    db,
                    document=document,
                    requested_by_id=actor_id,
                    job_type=ProcessingJobType.EXTRACT_TEXT,
                )

def test_phase_z_cross_tenant_release_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _actor_id, _profile_id, claim_id, execution, _binding = _bound(
        monkeypatch,
        "cross-tenant",
    )
    document_id = UUID(execution["document_id"])
    _other_org_id, other_admin_id, _other_approver_id = _seed_tenant(
        "phase-z-cross-tenant"
    )

    rejected = _grant(
        claim_id,
        document_id,
        other_admin_id,
        key="phase-z-cross-tenant-release",
    )
    assert rejected.status_code == 404, rejected.text

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceProcessingRelease).count() == 0

def test_phase_z_local_release_does_not_bypass_independent_ai_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, _profile_id, claim_id, execution, _binding = _bound(
        monkeypatch,
        "ai-boundary",
    )
    document_id = UUID(execution["document_id"])

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-z-release-ai-boundary",
    )
    assert release.status_code == 201, release.text
    assert release.json()["ai_processing_authorized"] is False

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        document.processing_status = DocumentProcessingStatus.PROCESSED
        db.add(
            DocumentTextExtraction(
                organization_id=document.organization_id,
                document_id=document.id,
                extraction_method="phase-z-test",
                extractor_version="phase-z-test-v1",
                char_count=120,
                segment_count=1,
                requires_ocr=False,
                text_hash="a" * 64,
                warnings=[],
            )
        )
        db.commit()

    class _OpenAIProvider:
        name = "openai"

    calls = {"count": 0}

    def _deny_ai(*_args, **_kwargs):
        calls["count"] += 1
        raise HTTPException(
            status_code=409,
            detail="Independent AI runtime authorization is still required.",
        )

    monkeypatch.setattr(
        intelligence_router,
        "_provider_for_document",
        lambda _document: _OpenAIProvider(),
    )
    monkeypatch.setattr(
        intelligence_router,
        "require_external_ai_runtime_authorization",
        _deny_ai,
    )

    response = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/intelligence/ce-report",
        headers=_headers(actor_id),
    )
    assert response.status_code == 409, response.text
    assert "independent ai runtime authorization" in response.json()["detail"].lower()
    assert calls["count"] == 1

    with TestingSessionLocal() as db:
        assert (
            db.query(DocumentProcessingJob)
            .filter(
                DocumentProcessingJob.document_id == document_id,
                DocumentProcessingJob.job_type == ProcessingJobType.AI_EXTRACT_CE_REPORT,
            )
            .count()
            == 0
        )

