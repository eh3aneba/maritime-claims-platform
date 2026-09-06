from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.documents.malware import (
    MalwareScannerError,
    MalwareScanResult,
    MalwareScanVerdict,
)
from app.modules.documents.models import Document
from app.modules.email_ingestion import provider_attachment_acquisition as acquisition
from app.modules.email_ingestion.models import (
    EmailAttachmentManifest,
    EmailIngestionConnection,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.email_ingestion.provider_source import _stage_email
from app.modules.email_ingestion.schemas import AttachmentManifestInput, NormalizedEmailInput
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_email_provider_execution import _adapter

_SAFE_PNG = b"\x89PNG\r\n\x1a\n" + b"provider-safe-payload"


def setup_function() -> None:
    reset_database()


def _stage_provider_attachment(
    provider_kind: str = "microsoft_graph",
    *,
    linked: bool = True,
    filename: str = "survey.png",
    mime_type: str = "image/png",
    payload: bytes = _SAFE_PNG,
    provider_sha256: str | None = None,
) -> tuple[str, dict, str, str]:
    claim_id, connection, adapter = _adapter(provider_kind)
    with TestingSessionLocal() as db:
        db_connection = db.get(EmailIngestionConnection, UUID(connection["id"]))
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        staged = _stage_email(
            db,
            connection=db_connection,
            adapter=db_adapter,
            payload=NormalizedEmailInput(
                provider_message_id=f"{provider_kind}-attachment-message",
                internet_message_id=f"<{provider_kind}-attachment-message@example.test>",
                sender="master@example.test",
                recipients=[connection["mailbox_address"]],
                cc=[],
                subject="Provider attachment staging",
                body_text="External provider attachment awaiting human review.",
                received_at=datetime.now(UTC),
                attachments=[
                    AttachmentManifestInput(
                        filename=filename,
                        mime_type=mime_type,
                        file_size_bytes=len(payload),
                        sha256=provider_sha256,
                    )
                ],
            ),
        )
        message_id = str(staged.id)

    if linked:
        reviewed = client.post(
            f"/api/v1/email-ingestion/messages/{message_id}/review",
            json={
                "action": "link",
                "claim_id": claim_id,
                "confirm_link": True,
                "note": "Manager confirmed this staged provider email belongs to the claim.",
            },
        )
        assert reviewed.status_code == 200, reviewed.text

    inbox = client.get("/api/v1/email-ingestion/inbox")
    assert inbox.status_code == 200
    message = next(item for item in inbox.json()["messages"] if item["id"] == message_id)
    manifest_id = message["attachments"][0]["id"]
    return claim_id, adapter, message_id, manifest_id


def _enable_clean_scan(monkeypatch, *, payload: bytes = _SAFE_PNG):
    monkeypatch.setattr(acquisition.settings, "malware_scan_enabled", True)
    calls = {"locator": 0, "fetch": 0, "scan": 0}

    def locator(adapter, token, message, manifest):
        calls["locator"] += 1
        assert token == "runtime-only-token"
        return "provider-attachment-locator-1"

    def fetch(adapter, token, message, provider_attachment_id):
        calls["fetch"] += 1
        assert token == "runtime-only-token"
        assert provider_attachment_id == "provider-attachment-locator-1"
        return payload

    def scan(*args, **kwargs):
        calls["scan"] += 1
        return MalwareScanResult(verdict=MalwareScanVerdict.CLEAN)

    monkeypatch.setattr(acquisition, "_resolve_credential", lambda reference: "runtime-only-token")
    monkeypatch.setattr(acquisition, "_resolve_locator", locator)
    monkeypatch.setattr(acquisition, "_fetch_attachment_bytes", fetch)
    monkeypatch.setattr(acquisition, "scan_file", scan)
    return calls


def test_clean_provider_attachment_remains_quarantine_only_and_is_idempotent(monkeypatch) -> None:
    digest = sha256(_SAFE_PNG).hexdigest()
    claim_id, _, message_id, manifest_id = _stage_provider_attachment(provider_sha256=digest)
    calls = _enable_clean_scan(monkeypatch)

    first = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["admission_status"] == "clean_pending_human_admission"
    assert payload["malware_scan_status"] == "clean"
    assert payload["acquired_claim_id"] == claim_id
    assert payload["acquired_file_hash"] == digest
    assert payload["replayed"] is False
    assert "provider_attachment_id" not in payload
    assert "quarantine_key" not in payload

    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.provider_attachment_id == "provider-attachment-locator-1"
        assert manifest.quarantine_key is not None
        acquisition._storage().path_for(manifest.quarantine_key)
        assert db.query(Document).count() == 0
        assert db.query(DocumentProcessingJob).count() == 0
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == manifest.id,
                AuditLog.action == "ACQUIRE_EMAIL_PROVIDER_ATTACHMENT_QUARANTINE",
            )
        )
        assert audit is not None
        serialized = str(audit.new_values) + str(audit.details)
        assert "provider-attachment-locator-1" not in serialized
        assert "survey.png" not in serialized
        assert digest not in serialized
        assert "runtime-only-token" not in serialized

    inbox = client.get("/api/v1/email-ingestion/inbox").json()
    serialized_inbox = str(inbox)
    assert "provider-attachment-locator-1" not in serialized_inbox
    assert "_provider_quarantine" not in serialized_inbox

    second = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert calls == {"locator": 1, "fetch": 1, "scan": 1}


def test_provider_attachment_requires_human_link_manager_role_and_active_source(monkeypatch) -> None:
    _, adapter, message_id, manifest_id = _stage_provider_attachment(linked=False)
    calls = _enable_clean_scan(monkeypatch)
    unlinked = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert unlinked.status_code == 409
    assert calls == {"locator": 0, "fetch": 0, "scan": 0}

    reset_database()
    claim_id, adapter, message_id, manifest_id = _stage_provider_attachment(linked=True)
    calls = _enable_clean_scan(monkeypatch)
    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    role_denied = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert role_denied.status_code == 403
    assert calls == {"locator": 0, "fetch": 0, "scan": 0}

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    suspended = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "suspend", "note": "Pause provider while attachment authority is reviewed."},
    )
    assert suspended.status_code == 200
    inactive = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert inactive.status_code == 409
    assert calls == {"locator": 0, "fetch": 0, "scan": 0}


def test_provider_attachment_is_tenant_scoped(monkeypatch) -> None:
    _, _, message_id, manifest_id = _stage_provider_attachment(linked=True)
    calls = _enable_clean_scan(monkeypatch)
    with TestingSessionLocal() as db:
        beta = db.query(Organization).filter(Organization.slug == "beta").one()
        db.add(
            User(
                organization_id=beta.id,
                email="beta-attachment-admin@example.com",
                full_name="Beta Attachment Admin",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    client.cookies.clear()
    login("beta", "beta-attachment-admin@example.com")
    denied = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert denied.status_code == 404
    assert calls == {"locator": 0, "fetch": 0, "scan": 0}


def test_graph_locator_resolution_requires_one_exact_provider_object(monkeypatch) -> None:
    _, _, message_id, manifest_id = _stage_provider_attachment(linked=True)
    with TestingSessionLocal() as db:
        message = db.get(IngestedEmailMessage, UUID(message_id))
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))

        monkeypatch.setattr(
            acquisition,
            "_http_json",
            lambda *args, **kwargs: {
                "value": [
                    {
                        "id": "duplicate-a",
                        "name": manifest.filename,
                        "contentType": manifest.mime_type,
                        "size": manifest.file_size_bytes,
                    },
                    {
                        "id": "duplicate-b",
                        "name": manifest.filename,
                        "contentType": manifest.mime_type,
                        "size": manifest.file_size_bytes,
                    },
                ]
            },
        )
        with pytest.raises(acquisition.ProviderAttachmentFailure) as exc:
            acquisition._graph_locator("token-never-logged", message, manifest)
        assert exc.value.code == "provider_attachment_locator_unresolved"


def test_scanner_disabled_and_invalid_signature_fail_closed_without_evidence(monkeypatch) -> None:
    _, _, message_id, manifest_id = _stage_provider_attachment(linked=True)
    monkeypatch.setattr(acquisition.settings, "malware_scan_enabled", False)
    no_scanner = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert no_scanner.status_code == 503
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "acquisition_failed"
        assert manifest.acquisition_failure_code == "malware_scanner_disabled"
        assert db.query(Document).count() == 0

    reset_database()
    _, _, message_id, manifest_id = _stage_provider_attachment(linked=True)
    monkeypatch.setattr(acquisition.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(acquisition, "_resolve_credential", lambda reference: "runtime-only-token")
    monkeypatch.setattr(acquisition, "_resolve_locator", lambda *args: "bad-signature-locator")
    monkeypatch.setattr(acquisition, "_fetch_attachment_bytes", lambda *args: b"not-a-png")
    scan_called = {"value": False}

    def should_not_scan(*args, **kwargs):
        scan_called["value"] = True
        raise AssertionError("Invalid signature must be rejected before malware scanning")

    monkeypatch.setattr(acquisition, "scan_file", should_not_scan)
    invalid = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert invalid.status_code == 415
    assert scan_called["value"] is False
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "acquisition_failed"
        assert manifest.acquisition_failure_code == "provider_attachment_signature_rejected"
        assert db.query(Document).count() == 0
        assert db.query(DocumentProcessingJob).count() == 0


@pytest.mark.parametrize(
    ("scanner_mode", "expected_status", "expected_scan_status", "expected_failure"),
    [
        ("infected", "infected_quarantined", "infected", None),
        ("error", "scan_error_quarantined", "scan_error", "malware_scan_error"),
    ],
)
def test_infected_and_scan_error_provider_bytes_remain_quarantined(
    monkeypatch,
    scanner_mode: str,
    expected_status: str,
    expected_scan_status: str,
    expected_failure: str | None,
) -> None:
    _, _, message_id, manifest_id = _stage_provider_attachment(linked=True)
    monkeypatch.setattr(acquisition.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(acquisition, "_resolve_credential", lambda reference: "runtime-only-token")
    monkeypatch.setattr(acquisition, "_resolve_locator", lambda *args: "provider-attachment-locator-2")
    monkeypatch.setattr(acquisition, "_fetch_attachment_bytes", lambda *args: _SAFE_PNG)

    if scanner_mode == "infected":
        monkeypatch.setattr(
            acquisition,
            "scan_file",
            lambda *args, **kwargs: MalwareScanResult(
                verdict=MalwareScanVerdict.INFECTED,
                threat_name="test-signature",
            ),
        )
    else:
        def scanner_error(*args, **kwargs):
            raise MalwareScannerError("synthetic scanner transport failure")
        monkeypatch.setattr(acquisition, "scan_file", scanner_error)

    response = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert response.status_code == 200, response.text
    assert response.json()["admission_status"] == expected_status
    assert response.json()["malware_scan_status"] == expected_scan_status
    assert response.json()["acquisition_failure_code"] == expected_failure
    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.quarantine_key is not None
        acquisition._storage().path_for(manifest.quarantine_key)
        assert db.query(Document).count() == 0
        assert db.query(DocumentProcessingJob).count() == 0


def test_email_retention_purges_provider_quarantine_bytes_and_locator(monkeypatch) -> None:
    digest = sha256(_SAFE_PNG).hexdigest()
    _, _, message_id, manifest_id = _stage_provider_attachment(
        linked=True,
        provider_sha256=digest,
    )
    _enable_clean_scan(monkeypatch)
    acquired = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert acquired.status_code == 200

    with TestingSessionLocal() as db:
        message = db.get(IngestedEmailMessage, UUID(message_id))
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        quarantine_key = manifest.quarantine_key
        assert quarantine_key is not None
        acquisition._storage().path_for(quarantine_key)
        message.retain_until = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    expired = client.post("/api/v1/email-ingestion/expire-due")
    assert expired.status_code == 200, expired.text
    assert expired.json()["expired_count"] == 1

    with TestingSessionLocal() as db:
        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        assert manifest.admission_status == "expired_quarantine_purged"
        assert manifest.provider_attachment_id is None
        assert manifest.quarantine_key is None
        assert manifest.acquired_file_hash is None
        assert manifest.acquired_file_size_bytes is None
        assert manifest.provider_sha256 is None
        assert manifest.filename == "[expired]"
        assert manifest.mime_type == "application/octet-stream"
        assert manifest.file_size_bytes == 0
        with pytest.raises(FileNotFoundError):
            acquisition._storage().path_for(quarantine_key)
        assert db.query(Document).count() == 0
