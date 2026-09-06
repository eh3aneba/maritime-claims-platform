from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.email_ingestion import provider_execution
from app.modules.email_ingestion.models import EmailAdapterRun, EmailProviderAdapter
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_email_provider_execution import _adapter


def setup_function() -> None:
    reset_database()


def _rotate(adapter_id: str, reference: str, *, confirm: bool = True, reason: str | None = None):
    return client.post(
        f"/api/v1/email-ingestion/adapters/{adapter_id}/credential-reference-rotation",
        json={
            "confirm_rotation": confirm,
            "credential_reference": reference,
            "reason": reason or "Rotate the external provider credential reference under operator control.",
        },
    )


def test_rotation_redacts_locators_preserves_checkpoint_and_invalidates_live_authority(monkeypatch) -> None:
    old_reference = "env://MCRI_PROVIDER_TEST_TOKEN"
    new_reference = "vault://production/mcri/graph-alpha"
    reason = "Rotate after an external credential custody change for the production mailbox."
    _, _, adapter = _adapter("microsoft_graph", credential_reference=old_reference)
    checkpoint_hash = sha256(b"already-acknowledged-cursor").hexdigest()
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert item.live_execution_enabled is True
        item.checkpoint_hash = checkpoint_hash
        db.commit()

    network_calls = {"count": 0}

    def must_not_call_provider(*args, **kwargs):
        network_calls["count"] += 1
        raise AssertionError("Credential reference rotation must not call a provider")

    monkeypatch.setattr(provider_execution, "_http_json", must_not_call_provider)
    rotated = _rotate(adapter["id"], new_reference, reason=reason)
    assert rotated.status_code == 200, rotated.text
    payload = rotated.json()
    assert payload["credential_backend"] == "vault"
    assert payload["credential_reference_version"] == 2
    assert payload["credential_reference_changed_at"] is not None
    assert payload["credential_resolver_available"] is False
    assert payload["checkpoint_preserved"] is True
    assert payload["live_execution_enabled"] is False
    assert payload["next_sync_at"] is None
    assert old_reference not in str(payload)
    assert new_reference not in str(payload)
    assert checkpoint_hash not in str(payload)
    assert network_calls["count"] == 0

    operations = client.get("/api/v1/email-ingestion/adapter-operations")
    assert operations.status_code == 200
    serialized_operations = str(operations.json())
    assert old_reference not in serialized_operations
    assert new_reference not in serialized_operations
    assert checkpoint_hash not in serialized_operations
    adapter_view = next(value for value in operations.json()["adapters"] if value["id"] == adapter["id"])
    assert adapter_view["credential_backend"] == "vault"
    assert adapter_view["credential_reference_configured"] is True
    assert adapter_view["credential_reference_version"] == 2
    assert adapter_view["checkpoint_present"] is True
    assert adapter_view["live_execution_enabled"] is False
    assert adapter_view["next_sync_at"] is None
    assert "credential_reference" not in adapter_view
    assert "checkpoint_hash" not in adapter_view

    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert item.credential_reference == new_reference
        assert item.credential_reference_version == 2
        assert item.checkpoint_hash == checkpoint_hash
        assert item.live_execution_enabled is False
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == item.id,
                AuditLog.action == "ROTATE_EMAIL_PROVIDER_CREDENTIAL_REFERENCE",
            )
        )
        assert audit is not None
        serialized_audit = str(audit.new_values) + str(audit.details)
        assert old_reference not in serialized_audit
        assert new_reference not in serialized_audit
        assert "production/mcri/graph-alpha" not in serialized_audit
        assert checkpoint_hash not in serialized_audit
        assert reason not in serialized_audit
        assert audit.new_values["credential_backend_before"] == "env"
        assert audit.new_values["credential_backend_after"] == "vault"
        assert audit.new_values["live_execution_invalidated"] is True


def test_unsupported_external_secret_backend_requires_reactivation_and_remains_fail_closed() -> None:
    _, _, adapter = _adapter("microsoft_graph")
    locator = "secret-manager://mcri/provider/graph-alpha"
    rotated = _rotate(adapter["id"], locator)
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["credential_backend"] == "secret-manager"
    assert rotated.json()["credential_resolver_available"] is False
    assert rotated.json()["live_execution_enabled"] is False

    execution = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "credential-resolver-unavailable-0001", "trigger": "manual"},
    )
    assert execution.status_code == 409

    activation = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/live-activation",
        json={
            "confirm_activation": True,
            "reason": "Verify unsupported external secret backend remains fail closed before live access.",
        },
    )
    assert activation.status_code == 409

    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert reconciliation.status_code == 200
    item = next(value for value in reconciliation.json()["items"] if value["adapter_id"] == adapter["id"])
    assert item["credential_backend"] == "secret-manager"
    assert item["credential_reference_configured"] is True
    assert item["credential_resolver_available"] is False
    assert item["live_execution_enabled"] is False
    assert item["operational_state"] == "activation_required"
    assert item["activation_blocker"] == "credential_resolver_unavailable"
    assert locator not in str(item)
    assert "mcri/provider/graph-alpha" not in str(item)


def test_rotation_is_explicit_manager_only_tenant_scoped_and_revoked_gated() -> None:
    _, _, adapter = _adapter("gmail_api")

    unconfirmed = _rotate(adapter["id"], "env://ROTATED_GMAIL_TOKEN", confirm=False)
    assert unconfirmed.status_code == 422

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = _rotate(adapter["id"], "env://ROTATED_GMAIL_TOKEN")
    assert denied.status_code == 403

    with TestingSessionLocal() as db:
        beta = db.query(Organization).filter(Organization.slug == "beta").one()
        db.add(
            User(
                organization_id=beta.id,
                email="beta-credential-admin@example.com",
                full_name="Beta Credential Admin",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    client.cookies.clear()
    login("beta", "beta-credential-admin@example.com")
    cross_tenant = _rotate(adapter["id"], "env://ROTATED_GMAIL_TOKEN")
    assert cross_tenant.status_code == 404

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    revoked = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "revoke", "note": "Revoke source before credential rotation gate test."},
    )
    assert revoked.status_code == 200
    assert revoked.json()["live_execution_enabled"] is False
    blocked = _rotate(adapter["id"], "env://ROTATED_GMAIL_TOKEN")
    assert blocked.status_code == 409


def test_pending_checkpoint_handoff_blocks_rotation() -> None:
    _, _, adapter = _adapter("microsoft_graph")
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        run = EmailAdapterRun(
            organization_id=item.organization_id,
            adapter_id=item.id,
            initiated_by_id=None,
            idempotency_key="pending-credential-rotation-gate",
            trigger="manual",
            status="succeeded",
            messages_seen=0,
            messages_ingested=0,
            checkpoint_hash=sha256(b"pending-cursor").hexdigest(),
            checkpoint_handoff_status="pending",
            failure_summary=None,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db.add(run)
        db.commit()

    blocked = _rotate(adapter["id"], "env://ROTATED_GRAPH_TOKEN")
    assert blocked.status_code == 409
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert item.credential_reference == "env://MCRI_PROVIDER_TEST_TOKEN"
        assert item.credential_reference_version == 1
        assert item.live_execution_enabled is True


def test_suspended_adapter_can_rotate_but_remains_unscheduled_and_disabled() -> None:
    _, _, adapter = _adapter("gmail_api")
    suspended = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "suspend", "note": "Pause provider source during planned external credential rotation."},
    )
    assert suspended.status_code == 200
    assert suspended.json()["next_sync_at"] is None
    assert suspended.json()["live_execution_enabled"] is False

    rotated = _rotate(adapter["id"], "env://ROTATED_GMAIL_TOKEN")
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["credential_backend"] == "env"
    assert rotated.json()["credential_reference_version"] == 2
    assert rotated.json()["next_sync_at"] is None
    assert rotated.json()["live_execution_enabled"] is False


def test_invalid_reference_is_rejected_but_legacy_invalid_reference_can_be_repaired() -> None:
    _, connection, _ = _adapter("provider_webhook")
    invalid_create = client.post(
        "/api/v1/email-ingestion/adapters",
        json={
            "connection_id": connection["id"],
            "provider_kind": "provider_webhook",
            "display_name": "Invalid credential source",
            "credential_reference": "env://BAD-NAME",
            "allowed_folder": "Claims",
            "permission_manifest": ["messages.read.allowed_folder"],
        },
    )
    assert invalid_create.status_code == 422

    reset_database()
    _, _, adapter = _adapter("gmail_api")
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        item.credential_reference = "legacy-invalid-reference"
        db.commit()

    repaired = _rotate(adapter["id"], "env://REPAIRED_GMAIL_TOKEN")
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["credential_backend"] == "env"
    assert repaired.json()["credential_reference_version"] == 2
    assert repaired.json()["live_execution_enabled"] is False
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == item.id,
                AuditLog.action == "ROTATE_EMAIL_PROVIDER_CREDENTIAL_REFERENCE",
            )
        )
        assert audit is not None
        assert audit.new_values["credential_backend_before"] == "invalid"
        serialized = str(audit.new_values) + str(audit.details)
        assert "legacy-invalid-reference" not in serialized
        assert "REPAIRED_GMAIL_TOKEN" not in serialized
