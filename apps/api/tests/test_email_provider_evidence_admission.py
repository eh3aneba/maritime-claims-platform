from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.documents.malware import (
    MalwareScannerError,
    MalwareScanResult,
    MalwareScanVerdict,
)
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
)
from app.modules.email_ingestion import provider_evidence_admission as admission
from app.modules.email_ingestion.models import (
    EmailAttachmentManifest,
    EmailIngestionConnection,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_email_provider_attachment_quarantine import (
    _SAFE_PNG,
    _enable_clean_scan,
    _stage_provider_attachment,
)


def setup_function() -> None:
    reset_database()


def _clean_quarantined_provider_attachment(monkeypatch) -> tuple[str, dict, str, str]:
    digest = sha256(_SAFE_PNG).hexdigest()
    claim_id, adapter, message_id, manifest_id = _stage_provider_attachment(
        linked=True,
        provider_sha256=digest,
    )
    _enable_clean_scan(monkeypatch)
    acquired = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert acquired.status_code == 200, acquired.text
    assert acquired.json()["admission_status"] == "clean_pending_human_admission"
    return claim_id, adapter, message_id, manifest_id


def _enable_clean_admission_scan(monkeypatch):
    monkeypatch.setattr(admission.settings, "malware_scan_enabled", True)
    calls = {"scan": 0}

    def scan(*args, **kwargs):
        calls["scan"] += 1
        return MalwareScanResult(verdict=MalwareScanVerdict.CLEAN)

    monkeypatch.setattr(admission, "scan_file", scan)
    return calls


def _admit(message_id: str, manifest_id: str, **overrides):
    payload = {
        "confirm_admission": True,
        "admission_note": "Manager verified the clean provider attachment and approved Evidence filing.",
        "document_type": "survey_report",
        "confidentiality_level": "confidential",
    }
    payload.update(overrides)
    return client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/admit-evidence",
        json=payload,
    )


def test_clean_provider_attachment_creates_one_document_without_processing(monkeypatch) -> None:
    claim_id, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)

    with TestingSessionLocal() as db:
        assert db.query(Document).count() == 0
        assert db.query(DocumentProcessingJob).count() == 0

    admitted = _admit(message_id, manifest_id)
    assert admitted.status_code == 200, admitted.text
    body = admitted.json()
    assert body["replayed"] is False
    document = body["document"]
    assert document["claim_id"] == claim_id
    assert document["source_email_attachment_manifest_id"] == manifest_id
    assert document["processing_status"] == "uploaded"
    assert document["malware_scan_status"] == "clean"
    assert document["document_type"] == "survey_report"
    assert document["confidentiality_level"] == "confidential"
    assert calls["scan"] == 1

    with TestingSessionLocal() as db:
        db_document = db.get(Document, UUID(document["id"]))
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert db_document is not None
        assert db_document.source_email_attachment_manifest_id == UUID(manifest_id)
        assert db_document.source_admission_note.startswith("Manager verified")
        assert db_document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert admission._storage().path_for(db_document.storage_key).is_file()
        assert manifest.admission_status == "admitted_to_evidence"
        assert manifest.quarantine_key is None
        assert manifest.evidence_admission_failure_code is None
        assert db.query(Document).count() == 1
        assert db.query(DocumentProcessingJob).count() == 0
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == db_document.id,
                AuditLog.action == "ADMIT_EMAIL_ATTACHMENT_TO_EVIDENCE",
            )
        )
        assert audit is not None
        serialized = str(audit.new_values) + str(audit.details)
        assert "provider-attachment-locator" not in serialized
        assert "_provider_quarantine" not in serialized
        assert "env://" not in serialized
        assert "runtime-only-token" not in serialized
        assert "Provider attachment staging" not in serialized

    replay = _admit(message_id, manifest_id)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["document"]["id"] == document["id"]
    assert calls["scan"] == 1

    processing = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document['id']}/processing/retry"
    )
    assert processing.status_code == 202, processing.text
    with TestingSessionLocal() as db:
        assert db.query(DocumentProcessingJob).count() == 1


def test_evidence_admission_requires_manager_and_explicit_confirmation(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = _admit(message_id, manifest_id)
    assert denied.status_code == 403
    assert calls["scan"] == 0

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    unconfirmed = _admit(message_id, manifest_id, confirm_admission=False)
    assert unconfirmed.status_code == 422
    assert calls["scan"] == 0
    with TestingSessionLocal() as db:
        assert db.query(Document).count() == 0


def test_evidence_admission_is_tenant_scoped(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)
    with TestingSessionLocal() as db:
        beta = db.query(Organization).filter(Organization.slug == "beta").one()
        db.add(
            User(
                organization_id=beta.id,
                email="beta-evidence-admin@example.com",
                full_name="Beta Evidence Admin",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    client.cookies.clear()
    login("beta", "beta-evidence-admin@example.com")
    denied = _admit(message_id, manifest_id)
    assert denied.status_code == 404
    assert calls["scan"] == 0


def test_inactive_adapter_or_connection_blocks_evidence_admission(monkeypatch) -> None:
    _, adapter, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)
    suspended = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "suspend", "note": "Pause provider source before Evidence filing."},
    )
    assert suspended.status_code == 200
    blocked = _admit(message_id, manifest_id)
    assert blocked.status_code == 409
    assert calls["scan"] == 0

    reset_database()
    _, adapter, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)
    suspended_connection = client.post(
        f"/api/v1/email-ingestion/connections/{adapter['connection_id']}/transition",
        json={"action": "suspend", "note": "Mailbox consent source is temporarily suspended."},
    )
    assert suspended_connection.status_code == 200
    blocked_connection = _admit(message_id, manifest_id)
    assert blocked_connection.status_code == 409
    assert calls["scan"] == 0


def test_non_clean_or_unlinked_manifest_cannot_be_admitted(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        manifest.admission_status = "infected_quarantined"
        manifest.malware_scan_status = "infected"
        db.commit()
    infected = _admit(message_id, manifest_id)
    assert infected.status_code == 409
    assert calls["scan"] == 0

    reset_database()
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)
    with TestingSessionLocal() as db:
        message = db.get(IngestedEmailMessage, UUID(message_id))
        message.status = "pending_review"
        db.commit()
    unlinked = _admit(message_id, manifest_id)
    assert unlinked.status_code == 409
    assert calls["scan"] == 0


def test_missing_or_changed_quarantine_bytes_fail_closed_and_require_reacquisition(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    _enable_clean_admission_scan(monkeypatch)
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        key = manifest.quarantine_key
        assert key is not None
        admission._storage().delete_physical(key)
    missing = _admit(message_id, manifest_id)
    assert missing.status_code == 409
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "acquisition_failed"
        assert manifest.quarantine_key is None
        assert db.query(Document).count() == 0

    reset_database()
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    _enable_clean_admission_scan(monkeypatch)
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        key = manifest.quarantine_key
        path = admission._storage().path_for(key)
        path.write_bytes(_SAFE_PNG + b"tampered")
    mismatch = _admit(message_id, manifest_id)
    assert mismatch.status_code == 409
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "acquisition_failed"
        assert manifest.quarantine_key is None
        assert db.query(Document).count() == 0


def test_signature_mismatch_fails_before_admission_scan(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)
    invalid_bytes = b"not-a-valid-png-file"
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        key = manifest.quarantine_key
        path = admission._storage().path_for(key)
        path.write_bytes(invalid_bytes)
        manifest.acquired_file_hash = sha256(invalid_bytes).hexdigest()
        manifest.acquired_file_size_bytes = len(invalid_bytes)
        db.commit()
    invalid = _admit(message_id, manifest_id)
    assert invalid.status_code == 415
    assert calls["scan"] == 0
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "acquisition_failed"
        assert db.query(Document).count() == 0


def test_admission_scanner_disabled_error_and_infected_all_create_zero_evidence(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    monkeypatch.setattr(admission.settings, "malware_scan_enabled", False)
    disabled = _admit(message_id, manifest_id)
    assert disabled.status_code == 503
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "clean_pending_human_admission"
        assert manifest.evidence_admission_failure_code == "evidence_admission_scanner_disabled"
        assert db.query(Document).count() == 0

    reset_database()
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    monkeypatch.setattr(admission.settings, "malware_scan_enabled", True)

    def scan_error(*args, **kwargs):
        raise MalwareScannerError("synthetic admission scanner error")

    monkeypatch.setattr(admission, "scan_file", scan_error)
    unavailable = _admit(message_id, manifest_id)
    assert unavailable.status_code == 503
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "clean_pending_human_admission"
        assert manifest.evidence_admission_failure_code == "evidence_admission_scan_error"
        assert db.query(Document).count() == 0

    reset_database()
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    monkeypatch.setattr(admission.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(
        admission,
        "scan_file",
        lambda *args, **kwargs: MalwareScanResult(
            verdict=MalwareScanVerdict.INFECTED,
            threat_name="synthetic-test-signature",
        ),
    )
    infected = _admit(message_id, manifest_id)
    assert infected.status_code == 422
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "infected_quarantined"
        assert manifest.malware_scan_status == "infected"
        assert manifest.evidence_admission_failure_code == "evidence_admission_infected"
        assert db.query(Document).count() == 0
        assert db.query(DocumentProcessingJob).count() == 0


def test_duplicate_claim_bytes_from_another_document_are_not_silently_rebound(monkeypatch) -> None:
    claim_id, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    calls = _enable_clean_admission_scan(monkeypatch)
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        duplicate_id = uuid4()
        db.add(
            Document(
                id=duplicate_id,
                organization_id=manifest.organization_id,
                claim_id=UUID(claim_id),
                uploaded_by_id=None,
                document_family_id=duplicate_id,
                filename="existing.png",
                original_filename="existing.png",
                mime_type="image/png",
                file_size_bytes=manifest.acquired_file_size_bytes,
                file_hash=manifest.acquired_file_hash,
                storage_key=f"synthetic/{duplicate_id}.png",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
                malware_scan_status=DocumentMalwareScanStatus.CLEAN,
                malware_scanned_at=datetime.now(UTC),
            )
        )
        db.commit()
    duplicate = _admit(message_id, manifest_id)
    assert duplicate.status_code == 409
    assert calls["scan"] == 0
    with TestingSessionLocal() as db:
        assert db.query(Document).count() == 1
        source_docs = list(
            db.scalars(
                select(Document).where(Document.source_email_attachment_manifest_id == UUID(manifest_id))
            )
        )
        assert source_docs == []


def test_email_retention_after_admission_never_deletes_canonical_evidence(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    _enable_clean_admission_scan(monkeypatch)
    admitted = _admit(message_id, manifest_id)
    assert admitted.status_code == 200
    document_id = admitted.json()["document"]["id"]

    with TestingSessionLocal() as db:
        message = db.get(IngestedEmailMessage, UUID(message_id))
        document = db.get(Document, UUID(document_id))
        canonical_key = document.storage_key
        assert admission._storage().path_for(canonical_key).is_file()
        message.retain_until = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    expired = client.post("/api/v1/email-ingestion/expire-due")
    assert expired.status_code == 200
    assert expired.json()["expired_count"] == 1

    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(document_id))
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert document is not None
        assert document.deleted_at is None
        assert document.source_email_attachment_manifest_id == UUID(manifest_id)
        assert admission._storage().path_for(document.storage_key).is_file()
        assert manifest.quarantine_key is None
        assert manifest.filename == "[expired]"


def test_document_response_exposes_only_bounded_source_provenance(monkeypatch) -> None:
    _, _, message_id, manifest_id = _clean_quarantined_provider_attachment(monkeypatch)
    _enable_clean_admission_scan(monkeypatch)
    admitted = _admit(message_id, manifest_id)
    assert admitted.status_code == 200
    serialized = str(admitted.json())
    assert manifest_id in serialized
    assert "provider_attachment_id" not in serialized
    assert "quarantine_key" not in serialized
    assert "credential_reference" not in serialized
    assert "source_admission_note" not in serialized
