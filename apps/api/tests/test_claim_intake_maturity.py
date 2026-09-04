from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.modules.documents.models import Document
from app.modules.intake import maturity as intake_maturity
from app.modules.intake import service as intake_service
from app.modules.intake.models import ClaimIntakeDraft, ClaimIntakeProcessingJob, ClaimIntakeStatus
from app.modules.processing.extractors import TextExtractionResult
from app.modules.processing.models import ProcessingJobStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claim_intake import (
    approval_payload,
    configure_intake,
    login,
    make_fnol,
    seed,
    upload_and_process,
)


def setup_function() -> None:
    reset_database()


def _upload_processing_draft(tmp_path, monkeypatch) -> UUID:
    configure_intake(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/claim-intake/drafts",
        files={
            "file": (
                "claim_notification.docx",
                make_fnol(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


def test_document_type_registry_is_controlled_and_unknown_is_not_approvable(
    tmp_path,
    monkeypatch,
) -> None:
    ids = seed()
    login("alpha", "alpha@example.com")

    registry = client.get("/api/v1/claim-intake/document-types")
    assert registry.status_code == 200
    assert registry.json()["unknown_requires_human_choice"] is True
    assert "claim_notification" in registry.json()["items"]
    assert "other" in registry.json()["items"]
    assert "unknown" not in registry.json()["items"]

    draft = upload_and_process(tmp_path, monkeypatch)
    payload = approval_payload(ids["alpha_vessel"], draft["extracted_fields"])

    omitted = dict(payload)
    omitted.pop("document_type")
    missing = client.post(f"/api/v1/claim-intake/drafts/{draft['id']}/approve", json=omitted)
    assert missing.status_code == 422

    payload["document_type"] = "unknown"
    rejected = client.post(f"/api/v1/claim-intake/drafts/{draft['id']}/approve", json=payload)
    assert rejected.status_code == 422

    payload["document_type"] = "other"
    approved = client.post(f"/api/v1/claim-intake/drafts/{draft['id']}/approve", json=payload)
    assert approved.status_code == 200, approved.text
    with TestingSessionLocal() as db:
        source = db.scalar(select(Document))
        assert source is not None
        assert source.document_type == "other"


def test_transient_intake_failure_is_requeued_until_attempt_limit(tmp_path, monkeypatch) -> None:
    seed()
    login("alpha", "alpha@example.com")
    draft_id = _upload_processing_draft(tmp_path, monkeypatch)

    monkeypatch.setattr(
        intake_service,
        "extract_document_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("temporary extractor outage")),
    )

    with TestingSessionLocal() as db:
        job = intake_service.claim_next_intake_job(db, worker_id="pytest-maturity")
        assert job is not None
        intake_maturity.process_intake_job(db, job=job)
        refreshed = db.get(ClaimIntakeProcessingJob, job.id)
        draft = db.get(ClaimIntakeDraft, draft_id)
        assert refreshed is not None
        assert draft is not None
        assert refreshed.status == ProcessingJobStatus.PENDING
        assert refreshed.attempt_count == 1
        assert refreshed.last_error == "temporary extractor outage"
        assert refreshed.available_at > datetime.now(UTC)
        assert draft.status == ClaimIntakeStatus.PROCESSING
        assert "automatic retry" in (draft.extraction_warnings or [""])[0]


def test_no_reviewable_text_is_terminal_but_operator_can_reprocess(tmp_path, monkeypatch) -> None:
    seed()
    login("alpha", "alpha@example.com")
    draft_id = _upload_processing_draft(tmp_path, monkeypatch)

    monkeypatch.setattr(
        intake_service,
        "extract_document_text",
        lambda *args, **kwargs: TextExtractionResult(method="python-docx", segments=[]),
    )

    with TestingSessionLocal() as db:
        job = intake_service.claim_next_intake_job(db, worker_id="pytest-terminal")
        assert job is not None
        intake_maturity.process_intake_job(db, job=job)
        refreshed = db.get(ClaimIntakeProcessingJob, job.id)
        draft = db.get(ClaimIntakeDraft, draft_id)
        assert refreshed is not None
        assert draft is not None
        assert refreshed.status == ProcessingJobStatus.FAILED
        assert draft.status == ClaimIntakeStatus.FAILED

    retry = client.post(f"/api/v1/claim-intake/drafts/{draft_id}/retry")
    assert retry.status_code == 202, retry.text
    assert retry.json()["status"] == "processing"
    retry_draft_id = UUID(retry.json()["id"])

    with TestingSessionLocal() as db:
        job = db.scalar(
            select(ClaimIntakeProcessingJob).where(
                ClaimIntakeProcessingJob.intake_draft_id == retry_draft_id
            )
        )
        assert job is not None
        assert job.status == ProcessingJobStatus.PENDING
        assert job.attempt_count == 0
        assert job.last_error is None
        assert job.completed_at is None
