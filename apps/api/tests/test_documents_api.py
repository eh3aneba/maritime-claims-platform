from datetime import date
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
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
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database

PASSWORD = "Strong-Document-Test-2026"


def setup_function() -> None:
    reset_database()


def seed_claim() -> dict[str, str]:
    with TestingSessionLocal() as db:
        alpha = Organization(name="Alpha Marine", slug="alpha")
        beta = Organization(name="Beta Marine", slug="beta")
        db.add_all([alpha, beta])
        db.flush()
        alpha_user = User(
            organization_id=alpha.id,
            email="alpha@example.com",
            full_name="Alpha Handler",
            password_hash=hash_password(PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        beta_user = User(
            organization_id=beta.id,
            email="beta@example.com",
            full_name="Beta Handler",
            password_hash=hash_password(PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        alpha_vessel = Vessel(organization_id=alpha.id, name="MT ORION", imo_number="7000001")
        beta_vessel = Vessel(organization_id=beta.id, name="MT BETA", imo_number="7000002")
        db.add_all([alpha_user, beta_user, alpha_vessel, beta_vessel])
        db.flush()
        alpha_claim = Claim(
            organization_id=alpha.id,
            vessel_id=alpha_vessel.id,
            claim_reference="MCRI-HM-2026-0001",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Turbocharger failure",
            currency="USD",
        )
        beta_claim = Claim(
            organization_id=beta.id,
            vessel_id=beta_vessel.id,
            claim_reference="MCRI-HM-2026-0001",
            incident_date=date(2026, 7, 12),
            notification_date=date(2026, 7, 13),
            incident_description="Beta machinery claim",
            currency="USD",
        )
        db.add_all([alpha_claim, beta_claim])
        db.commit()
        return {
            "alpha_claim": str(alpha_claim.id),
            "beta_claim": str(beta_claim.id),
        }


def login(slug: str, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization_slug": slug, "email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def configure_storage(tmp_path: Path) -> None:
    document_service.settings.local_storage_path = str(tmp_path / "documents")
    document_service.settings.max_upload_mb = 1
    document_service.settings.malware_scan_enabled = False


def test_upload_list_download_and_audit(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")

    content = b"%PDF-1.4\nmock chief engineer report\n%%EOF"
    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("CE_Report.pdf", content, "application/pdf")},
        data={"document_type": "chief_engineer_report", "confidentiality_level": "confidential"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["original_filename"] == "CE_Report.pdf"
    assert payload["document_type"] == "chief_engineer_report"
    assert payload["file_size_bytes"] == len(content)
    assert payload["malware_scan_status"] == "legacy_unscanned"
    assert len(payload["file_hash"]) == 64

    listed = client.get(f"/api/v1/claims/{ids['alpha_claim']}/documents")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["quarantined_total"] == 0

    downloaded = client.get(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/{payload['id']}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == content

    with TestingSessionLocal() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "UPLOAD_DOCUMENT"))
        assert audit is not None
        document = db.get(Document, UUID(payload["id"]))
        assert document is not None
        assert Path(document_service._storage().path_for(document.storage_key)).is_file()


def test_clean_scan_promotes_upload_and_queues_processing(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    document_service.settings.malware_scan_enabled = True
    monkeypatch.setattr(
        document_service,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(MalwareScanVerdict.CLEAN, raw_response="stream: OK"),
    )
    login("alpha", "alpha@example.com")

    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("clean.pdf", b"%PDF-1.4\nclean evidence", "application/pdf")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["malware_scan_status"] == "clean"
    assert response.json()["malware_scanned_at"] is not None

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(response.json()["id"]))
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert not document.storage_key.startswith("_quarantine/")
        assert document_service._storage().path_for(document.storage_key).is_file()
        assert db.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 1
        assert db.scalar(select(func.count()).select_from(QuarantinedUpload)) == 0


def test_infected_upload_is_blocked_and_retained_in_quarantine(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    document_service.settings.malware_scan_enabled = True
    monkeypatch.setattr(
        document_service,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(
            MalwareScanVerdict.INFECTED,
            threat_name="Win.Test.EICAR_HDB-1",
            raw_response="stream: Win.Test.EICAR_HDB-1 FOUND",
        ),
    )
    login("alpha", "alpha@example.com")

    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("blocked.pdf", b"%PDF-1.4\nquarantine test", "application/pdf")},
    )
    assert response.status_code == 422, response.text
    assert "blocked and quarantined" in response.json()["detail"]

    listed = client.get(f"/api/v1/claims/{ids['alpha_claim']}/documents").json()
    assert listed["total"] == 0
    assert listed["quarantined_total"] == 1
    assert listed["quarantined_items"][0]["status"] == "infected"
    assert listed["quarantined_items"][0]["threat_name"] == "Win.Test.EICAR_HDB-1"

    with TestingSessionLocal() as db:
        quarantined = db.scalar(select(QuarantinedUpload))
        assert quarantined is not None
        assert quarantined.status == QuarantineStatus.INFECTED
        assert quarantined.quarantine_key.startswith("_quarantine/")
        assert document_service._storage().path_for(quarantined.quarantine_key).is_file()
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 0
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "QUARANTINE_DOCUMENT_UPLOAD")
        )
        assert audit is not None


def test_scanner_error_fails_closed_and_retains_quarantine(tmp_path: Path, monkeypatch) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    document_service.settings.malware_scan_enabled = True

    def unavailable(*args, **kwargs):
        raise MalwareScannerError("ClamAV is unavailable")

    monkeypatch.setattr(document_service, "scan_file", unavailable)
    login("alpha", "alpha@example.com")
    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("pending.pdf", b"%PDF-1.4\nscanner unavailable", "application/pdf")},
    )
    assert response.status_code == 503, response.text
    assert "remains quarantined" in response.json()["detail"]

    with TestingSessionLocal() as db:
        quarantined = db.scalar(select(QuarantinedUpload))
        assert quarantined.status == QuarantineStatus.SCAN_ERROR
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 0


def test_duplicate_upload_is_rejected(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    files = {"file": ("Engine_Log.pdf", b"%PDF-1.4\nsame bytes", "application/pdf")}
    first = client.post(f"/api/v1/claims/{ids['alpha_claim']}/documents", files=files)
    assert first.status_code == 201
    second = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("Engine_Log_Copy.pdf", b"%PDF-1.4\nsame bytes", "application/pdf")},
    )
    assert second.status_code == 409


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_mismatched_file_signature_is_rejected(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("renamed.pdf", b"MZ executable content", "application/pdf")},
    )
    assert response.status_code == 415


def test_upload_size_limit_is_enforced(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    response = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("large.pdf", b"%PDF-1.4\n" + b"a" * (1024 * 1024 + 1), "application/pdf")},
    )
    assert response.status_code == 413


def test_cross_tenant_document_access_is_hidden(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    upload = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("Survey.pdf", b"%PDF-1.4\nsurvey", "application/pdf")},
    )
    document_id = upload.json()["id"]

    client.cookies.clear()
    login("beta", "beta@example.com")
    assert client.get(f"/api/v1/claims/{ids['alpha_claim']}/documents").status_code == 404
    assert client.get(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/{document_id}/download"
    ).status_code == 404


def test_soft_delete_hides_metadata_but_retains_file(tmp_path: Path) -> None:
    ids = seed_claim()
    configure_storage(tmp_path)
    login("alpha", "alpha@example.com")
    upload = client.post(
        f"/api/v1/claims/{ids['alpha_claim']}/documents",
        files={"file": ("Workshop_Report.pdf", b"%PDF-1.4\nworkshop evidence", "application/pdf")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["id"]

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(document_id))
        stored_path = document_service._storage().path_for(document.storage_key)
        assert stored_path.is_file()

    deleted = client.delete(f"/api/v1/claims/{ids['alpha_claim']}/documents/{document_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/claims/{ids['alpha_claim']}/documents").json()["total"] == 0
    assert client.get(
        f"/api/v1/claims/{ids['alpha_claim']}/documents/{document_id}/download"
    ).status_code == 404
    assert stored_path.is_file()

    with TestingSessionLocal() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "DELETE_DOCUMENT"))
        assert audit is not None
        document = db.get(Document, UUID(document_id))
        assert document.deleted_at is not None
