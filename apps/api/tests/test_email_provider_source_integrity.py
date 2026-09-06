import json
from uuid import UUID

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.correspondence.models import ClaimCorrespondence
from app.modules.email_ingestion.models import EmailProviderAdapter, IngestedEmailMessage
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_controlled_email_ingestion import _connection, _email_payload


def setup_function() -> None:
    reset_database()


def _adapter(connection_id: str, provider_kind: str = "provider_webhook") -> dict:
    created = client.post(
        "/api/v1/email-ingestion/adapters",
        json={
            "connection_id": connection_id,
            "provider_kind": provider_kind,
            "display_name": f"{provider_kind} intake",
            "credential_reference": f"env://{provider_kind.upper()}_SOURCE",
            "allowed_folder": "Claims Intake",
            "permission_manifest": ["messages.read.allowed_folder", "attachments.metadata.read"],
            "batch_limit": 25,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _claim_reference(claim_id: str) -> str:
    response = client.get(f"/api/v1/claims/{claim_id}")
    assert response.status_code == 200, response.text
    return response.json()["claim_reference"]


def test_provider_webhook_is_source_bound_idempotent_and_content_safe() -> None:
    claim_id, connection, token = _connection()
    claim_reference = _claim_reference(claim_id)
    adapter = _adapter(connection["id"])
    payload = _email_payload(claim_reference)
    provider_url = f"/api/v1/email-ingestion/adapters/{adapter['id']}/webhook"

    # Once a provider source is configured, the generic connection route cannot bypass it.
    legacy = client.post(
        f"/api/v1/email-ingestion/webhooks/{connection['id']}",
        headers={"X-MCRI-Ingestion-Token": token},
        json=payload,
    )
    assert legacy.status_code == 409

    first = client.post(
        provider_url,
        headers={"X-MCRI-Ingestion-Token": token},
        json=payload,
    )
    assert first.status_code == 201, first.text
    message = first.json()
    assert message["adapter_id"] == adapter["id"]
    assert message["status"] == "pending_review"
    assert message["suggested_claim_id"] == claim_id
    assert message["linked_claim_id"] is None
    assert message["correspondence_id"] is None
    assert message["attachments"][0]["admission_status"] == "blocked_pending_quarantine"

    exact_replay = client.post(
        provider_url,
        headers={"X-MCRI-Ingestion-Token": token},
        json=payload,
    )
    assert exact_replay.status_code == 201
    assert exact_replay.json()["id"] == message["id"]

    changed = {
        **payload,
        "body_text": "Materially different replay content that must not replace the staged message.",
    }
    conflict = client.post(
        provider_url,
        headers={"X-MCRI-Ingestion-Token": token},
        json=changed,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Provider message replay content mismatch"

    with TestingSessionLocal() as db:
        stored = db.get(IngestedEmailMessage, UUID(message["id"]))
        assert stored is not None
        assert str(stored.adapter_id) == adapter["id"]
        assert db.query(IngestedEmailMessage).count() == 1
        assert db.query(ClaimCorrespondence).count() == 0
        audit = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.entity_id == UUID(message["id"]),
                AuditLog.action == "REJECT_EMAIL_PROVIDER_REPLAY",
            )
            .order_by(AuditLog.created_at.desc())
        )
        assert audit is not None
        serialized_audit = json.dumps(
            {"new_values": audit.new_values, "details": audit.details},
            sort_keys=True,
        )
        for forbidden in (
            changed["body_text"],
            payload["subject"],
            payload["sender"],
            payload["recipients"][0],
        ):
            assert forbidden not in serialized_audit


def test_historical_legacy_message_cannot_be_silently_rebound_to_new_adapter() -> None:
    claim_id, connection, token = _connection()
    payload = _email_payload(_claim_reference(claim_id))
    legacy_url = f"/api/v1/email-ingestion/webhooks/{connection['id']}"

    legacy = client.post(
        legacy_url,
        headers={"X-MCRI-Ingestion-Token": token},
        json=payload,
    )
    assert legacy.status_code == 201, legacy.text
    assert legacy.json()["adapter_id"] is None

    adapter = _adapter(connection["id"])
    provider_replay = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/webhook",
        headers={"X-MCRI-Ingestion-Token": token},
        json=payload,
    )
    assert provider_replay.status_code == 409
    assert provider_replay.json()["detail"] == "Provider message replay source mismatch"

    legacy_after_binding = client.post(
        legacy_url,
        headers={"X-MCRI-Ingestion-Token": token},
        json={**payload, "provider_message_id": "provider-legacy-after-binding"},
    )
    assert legacy_after_binding.status_code == 409

    with TestingSessionLocal() as db:
        stored = db.get(IngestedEmailMessage, UUID(legacy.json()["id"]))
        assert stored.adapter_id is None
        assert db.query(IngestedEmailMessage).count() == 1


@pytest.mark.parametrize("provider_kind", ["microsoft_graph", "gmail_api"])
def test_graph_and_gmail_adapters_do_not_gain_webhook_execution_authority(provider_kind: str) -> None:
    claim_id, connection, token = _connection()
    adapter = _adapter(connection["id"], provider_kind=provider_kind)
    blocked = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/webhook",
        headers={"X-MCRI-Ingestion-Token": token},
        json=_email_payload(_claim_reference(claim_id)),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "This adapter kind has no normalized webhook execution authority"
    with TestingSessionLocal() as db:
        assert db.query(IngestedEmailMessage).count() == 0


def test_inactive_provider_adapter_blocks_new_intake() -> None:
    claim_id, connection, token = _connection()
    adapter = _adapter(connection["id"])
    suspended = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "suspend", "note": "Provider intake paused for operational review."},
    )
    assert suspended.status_code == 200

    blocked = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/webhook",
        headers={"X-MCRI-Ingestion-Token": token},
        json={
            **_email_payload(_claim_reference(claim_id)),
            "provider_message_id": "provider-suspended-001",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Email provider adapter is not active"
    with TestingSessionLocal() as db:
        assert db.query(IngestedEmailMessage).count() == 0
        stored_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert stored_adapter.status == "suspended"
