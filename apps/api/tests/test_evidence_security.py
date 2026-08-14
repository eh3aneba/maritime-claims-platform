from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from app.modules.documents import evidence_security
from app.modules.documents import service as document_service
from app.modules.documents.malware import (
    MalwareScannerError,
    MalwareScanResult,
    MalwareScanVerdict,
)
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    QuarantinedUpload,
    QuarantineStatus,
)
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.processing.service import claim_next_job, process_job
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_documents_api import PASSWORD, configure_storage, login, seed_claim


def setup_function() -> None:
    reset_database()


def teardown_function() -> None:
    document_service.settings.malware_scan_enabled = False
    evidence_security.settings.malware_scan_enabled = False


def set_role(email: str, role: UserRole) -> None:
    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        user.role = role
        db.commit()


def upload_legacy_document(claim_id: str, tmp_path: Path, name: str = "legacy.pdf") -> str:
    configure_storage(tmp_path)
    document_service.settings.malware_scan_enabled = False
    response = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={"file": (name, b"%PDF-1.4\nlegacy evidence", "application/pdf")},
        data={"document_type": "chief_engineer_report"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["malware_scan_status"] == "legacy_unscanned"
    return response.json()["id"]


def process_security_job() -> DocumentProcessingJob:
    with TestingSessionLocal() as db:
        job = claim_next_job(db, worker_id="security-test-worker")
        assert job is not None
        assert job.job_type == ProcessingJobType.MALWARE_RESCAN
        process_job(db, job=job)
        db.refresh(job)
        return job


def test_claims_handler_cannot_queue_legacy_rescan(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    upload_legacy_document(ids["alpha_claim"], tmp_path)

    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/rescan-legacy",
        json={"limit": 10},
    )
    assert response.status_code == 403


def test_manager_queues_bounded_clean_legacy_rescan(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    set_role("alpha@example.com", UserRole.CLAIMS_MANAGER)
    login("alpha", "alpha@example.com")
    document_id = upload_legacy_document(ids["alpha_claim"], tmp_path)
    evidence_security.settings.malware_scan_enabled = True
    monkeypatch.setattr(
        evidence_security,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(
            MalwareScanVerdict.CLEAN,
            raw_response="stream: OK",
        ),
    )

    queued = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/rescan-legacy",
        json={"limit": 1},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["queued_count"] == 1

    job = process_security_job()
    assert job.status == ProcessingJobStatus.COMPLETED
    assert job.result["malware_scan_status"] == "clean"

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(document_id))
        assert document is not None
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert document.malware_scanned_at is not None
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "RESCAN_LEGACY_DOCUMENT_CLEAN")
        )
        assert audit is not None


def test_infected_legacy_document_is_quarantined_and_processing_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ids = seed_claim()
    set_role("alpha@example.com", UserRole.CLAIMS_MANAGER)
    login("alpha", "alpha@example.com")
    document_id = upload_legacy_document(ids["alpha_claim"], tmp_path, "legacy-infected.pdf")
    evidence_security.settings.malware_scan_enabled = True
    monkeypatch.setattr(
        evidence_security,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(
            MalwareScanVerdict.INFECTED,
            threat_name="Win.Test.EICAR_HDB-1",
            raw_response="stream: Win.Test.EICAR_HDB-1 FOUND",
        ),
    )
    queued = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/rescan-legacy",
        json={"limit": 10},
    )
    assert queued.status_code == 202
    process_security_job()

    download = client.get(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/{document_id}/download"
    )
    assert download.status_code == 423

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(document_id))
        quarantined = db.scalar(select(QuarantinedUpload))
        assert document is not None and quarantined is not None
        assert document.malware_scan_status == DocumentMalwareScanStatus.INFECTED_QUARANTINED
        assert quarantined.status == QuarantineStatus.INFECTED
        assert quarantined.source_document_id == document.id
        assert quarantined.threat_name == "Win.Test.EICAR_HDB-1"
        assert document_service._storage().path_for(quarantined.quarantine_key).is_file()
        pending_text_job = db.scalar(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.document_id == document.id,
                DocumentProcessingJob.job_type == ProcessingJobType.EXTRACT_TEXT,
            )
        )
        assert pending_text_job is not None
        assert pending_text_job.status == ProcessingJobStatus.FAILED


def test_scanner_error_quarantine_can_be_retried_and_cleanly_released(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ids = seed_claim()
    set_role("alpha@example.com", UserRole.CLAIMS_MANAGER)
    login("alpha", "alpha@example.com")
    document_id = upload_legacy_document(ids["alpha_claim"], tmp_path, "legacy-retry.pdf")
    evidence_security.settings.malware_scan_enabled = True

    def scanner_unavailable(*args, **kwargs):
        raise MalwareScannerError("ClamAV unavailable")

    monkeypatch.setattr(evidence_security, "scan_file", scanner_unavailable)
    client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/rescan-legacy",
        json={"limit": 10},
    )
    process_security_job()

    with TestingSessionLocal() as db:
        quarantined = db.scalar(select(QuarantinedUpload))
        assert quarantined is not None
        quarantine_id = str(quarantined.id)
        assert quarantined.status == QuarantineStatus.SCAN_ERROR

    monkeypatch.setattr(
        evidence_security,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(MalwareScanVerdict.CLEAN),
    )
    retry = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/quarantined-uploads/{quarantine_id}/retry"
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "released"
    assert retry.json()["released_document_id"] == document_id

    assert client.get(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/{document_id}/download"
    ).status_code == 200
    listing = client.get(f"/api/v1/claims/{ids['alpha_claim']}/documents").json()
    assert listing["quarantined_total"] == 0

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(document_id))
        quarantined = db.get(QuarantinedUpload, UUID(quarantine_id))
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert quarantined.status == QuarantineStatus.RELEASED
        assert quarantined.retry_count == 1


def test_new_upload_scan_error_retains_metadata_for_clean_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    set_role("alpha@example.com", UserRole.CLAIMS_MANAGER)
    login("alpha", "alpha@example.com")
    document_service.settings.malware_scan_enabled = True
    evidence_security.settings.malware_scan_enabled = True

    def scanner_unavailable(*args, **kwargs):
        raise MalwareScannerError("ClamAV unavailable")

    monkeypatch.setattr(document_service, "scan_file", scanner_unavailable)
    upload = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("held.pdf", b"%PDF-1.4\nheld evidence", "application/pdf")},
        data={"document_type": "workshop_report", "confidentiality_level": "restricted"},
    )
    assert upload.status_code == 503

    with TestingSessionLocal() as db:
        quarantined = db.scalar(select(QuarantinedUpload))
        assert quarantined is not None
        quarantine_id = str(quarantined.id)
        assert quarantined.document_type == "workshop_report"
        assert quarantined.confidentiality_level.value == "restricted"

    monkeypatch.setattr(
        evidence_security,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(MalwareScanVerdict.CLEAN),
    )
    retry = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/quarantined-uploads/{quarantine_id}/retry"
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["released_document_id"] == quarantine_id

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(quarantine_id))
        assert document is not None
        assert document.document_type == "workshop_report"
        assert document.confidentiality_level.value == "restricted"
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert db.scalar(
            select(func.count()).select_from(DocumentProcessingJob).where(
                DocumentProcessingJob.document_id == document.id,
                DocumentProcessingJob.job_type == ProcessingJobType.EXTRACT_TEXT,
            )
        ) == 1


def test_only_admin_can_purge_quarantined_bytes(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    set_role("alpha@example.com", UserRole.CLAIMS_MANAGER)
    login("alpha", "alpha@example.com")
    document_service.settings.malware_scan_enabled = True
    monkeypatch.setattr(
        document_service,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(
            MalwareScanVerdict.INFECTED,
            threat_name="Win.Test.EICAR_HDB-1",
        ),
    )
    upload = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("infected.pdf", b"%PDF-1.4\nblocked", "application/pdf")},
    )
    assert upload.status_code == 422

    with TestingSessionLocal() as db:
        quarantined = db.scalar(select(QuarantinedUpload))
        assert quarantined is not None
        quarantine_id = str(quarantined.id)
        path = document_service._storage().path_for(quarantined.quarantine_key)

    forbidden = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/quarantined-uploads/{quarantine_id}/purge",
        json={
            "confirm_upload_id": quarantine_id,
            "reason": "Confirmed infected test evidence retained only for validation.",
        },
    )
    assert forbidden.status_code == 403

    set_role("alpha@example.com", UserRole.ADMIN)
    client.cookies.clear()
    login("alpha", "alpha@example.com")
    purged = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/quarantined-uploads/{quarantine_id}/purge",
        json={
            "confirm_upload_id": quarantine_id,
            "reason": "Confirmed infected test evidence retained only for validation.",
        },
    )
    assert purged.status_code == 200, purged.text
    assert purged.json()["status"] == "purged"
    assert not path.exists()

    with TestingSessionLocal() as db:
        quarantined = db.get(QuarantinedUpload, UUID(quarantine_id))
        assert quarantined.status == QuarantineStatus.PURGED
        assert quarantined.resolution_note is not None
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "PURGE_QUARANTINED_UPLOAD")
        )
        assert audit is not None


def test_cross_tenant_quarantine_retry_is_hidden(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    set_role("alpha@example.com", UserRole.CLAIMS_MANAGER)
    set_role("beta@example.com", UserRole.CLAIMS_MANAGER)
    login("alpha", "alpha@example.com")
    document_service.settings.malware_scan_enabled = True

    def scanner_unavailable(*args, **kwargs):
        raise MalwareScannerError("ClamAV unavailable")

    monkeypatch.setattr(document_service, "scan_file", scanner_unavailable)
    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("tenant-held.pdf", b"%PDF-1.4\nheld", "application/pdf")},
    )
    assert response.status_code == 503
    with TestingSessionLocal() as db:
        quarantine_id = str(db.scalar(select(QuarantinedUpload)).id)

    client.cookies.clear()
    login("beta", "beta@example.com")
    retry = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/quarantined-uploads/{quarantine_id}/retry"
    )
    assert retry.status_code == 404
