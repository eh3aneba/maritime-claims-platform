from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.correspondence.models import ClaimCorrespondence, CorrespondenceStatus
from app.modules.email_ingestion.models import EmailAttachmentManifest, IngestedEmailMessage
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _connection() -> tuple[str, dict, str]:
    result = create_orion_claim()
    created = client.post(
        "/api/v1/email-ingestion/connections",
        json={"provider_label": "Normalized Webhook", "mailbox_address": "claims-intake@alpha-maritime.com",
              "consent_confirmed": True,
              "consent_basis": "Mailbox owner and organization approved claim-email intake.",
              "retention_days": 30},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert len(payload["ingestion_token"]) >= 32
    return result["claim"]["id"], payload, payload["ingestion_token"]


def _email_payload(claim_reference: str) -> dict:
    return {
        "provider_message_id": "provider-001", "internet_message_id": "<mail-001@orion-shipping.com>",
        "sender": "master@orion-shipping.com", "recipients": ["claims-intake@alpha-maritime.com"], "cc": [],
        "subject": f"{claim_reference} - Turbocharger documents",
        "body_text": "Please find the requested Chief Engineer report attached.",
        "received_at": "2026-08-15T10:00:00Z",
        "attachments": [{"filename": "chief-engineer-report.pdf", "mime_type": "application/pdf",
                         "file_size_bytes": 12000, "sha256": "a" * 64}],
    }


def test_email_ingestion_is_consent_gated_deduplicated_and_human_linked() -> None:
    claim_id, connection, token = _connection()
    claim_reference = client.get(f"/api/v1/claims/{claim_id}").json()["claim_reference"]
    url = f"/api/v1/email-ingestion/webhooks/{connection['id']}"
    invalid = client.post(url, headers={"X-MCRI-Ingestion-Token": "wrong"}, json=_email_payload(claim_reference))
    assert invalid.status_code == 401
    ingested = client.post(url, headers={"X-MCRI-Ingestion-Token": token}, json=_email_payload(claim_reference))
    assert ingested.status_code == 201, ingested.text
    message = ingested.json()
    assert message["status"] == "pending_review"
    assert message["suggested_claim_id"] == claim_id
    assert message["linked_claim_id"] is None
    assert message["attachments"][0]["admission_status"] == "blocked_pending_quarantine"
    duplicate = client.post(url, headers={"X-MCRI-Ingestion-Token": token}, json=_email_payload(claim_reference))
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == message["id"]

    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    linked = client.post(
        f"/api/v1/email-ingestion/messages/{message['id']}/review",
        json={"action": "link", "claim_id": claim_id, "confirm_link": True,
              "sensitivity": "confidential", "note": "Claim reference and sender context checked manually."},
    )
    assert linked.status_code == 200, linked.text
    linked_payload = linked.json()
    assert linked_payload["status"] == "linked"
    assert linked_payload["linked_claim_id"] == claim_id
    assert linked_payload["correspondence_id"]
    assert linked_payload["body_text"].startswith("[Promoted to correspondence")

    with TestingSessionLocal() as db:
        correspondence = db.get(ClaimCorrespondence, UUID(linked_payload["correspondence_id"]))
        assert correspondence.status == CorrespondenceStatus.RECEIVED_EXTERNAL
        assert correspondence.subject.startswith(claim_reference)
        manifest = db.scalar(select(EmailAttachmentManifest).where(EmailAttachmentManifest.message_id == UUID(message["id"])))
        assert manifest.admission_status == "blocked_pending_quarantine"
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == UUID(message["id"]))))
        assert {"INGEST_EMAIL_PENDING_REVIEW", "LINK_INGESTED_EMAIL_TO_CLAIM"}.issubset(actions)


def test_connection_lifecycle_retention_and_tenant_scope_are_enforced() -> None:
    claim_id, connection, token = _connection()
    claim_reference = client.get(f"/api/v1/claims/{claim_id}").json()["claim_reference"]
    url = f"/api/v1/email-ingestion/webhooks/{connection['id']}"
    ingested = client.post(url, headers={"X-MCRI-Ingestion-Token": token}, json=_email_payload(claim_reference)).json()
    suspended = client.post(
        f"/api/v1/email-ingestion/connections/{connection['id']}/transition",
        json={"action": "suspend", "note": "Consent scope is being reviewed."},
    )
    assert suspended.status_code == 200
    blocked = client.post(url, headers={"X-MCRI-Ingestion-Token": token},
                          json={**_email_payload(claim_reference), "provider_message_id": "provider-002"})
    assert blocked.status_code == 409

    with TestingSessionLocal() as db:
        message = db.get(IngestedEmailMessage, UUID(ingested["id"]))
        message.retain_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    expired = client.post("/api/v1/email-ingestion/expire-due")
    assert expired.status_code == 200 and expired.json()["expired_count"] == 1
    inbox = client.get("/api/v1/email-ingestion/inbox").json()
    record = next(x for x in inbox["messages"] if x["id"] == ingested["id"])
    assert record["status"] == "expired"
    assert record["subject"] == "[expired by retention policy]"

    client.cookies.clear(); login("beta", "beta-handler@example.com")
    beta_inbox = client.get("/api/v1/email-ingestion/inbox")
    assert beta_inbox.status_code == 200 and beta_inbox.json()["messages"] == []
    cross_tenant = client.post(
        f"/api/v1/email-ingestion/messages/{ingested['id']}/review",
        json={"action": "reject", "note": "Must not see Alpha email."},
    )
    assert cross_tenant.status_code == 404


def test_connection_requires_explicit_consent_and_manager_role() -> None:
    create_orion_claim()
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    denied = client.post(
        "/api/v1/email-ingestion/connections",
        json={"provider_label": "Webhook", "mailbox_address": "handler@alpha-maritime.com",
              "consent_confirmed": True, "consent_basis": "Valid consent basis recorded here.",
              "retention_days": 14},
    )
    assert denied.status_code == 403
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    missing_consent = client.post(
        "/api/v1/email-ingestion/connections",
        json={"provider_label": "Webhook", "mailbox_address": "manager@alpha-maritime.com",
              "consent_confirmed": False, "consent_basis": "Consent was not actually confirmed.",
              "retention_days": 14},
    )
    assert missing_consent.status_code == 422
