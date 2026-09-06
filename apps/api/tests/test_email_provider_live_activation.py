from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.email_ingestion import provider_execution
from app.modules.email_ingestion.models import EmailAdapterRun, EmailProviderAdapter
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import login
from tests.test_controlled_email_ingestion import _connection
from tests.test_email_provider_attachment_quarantine import (
    _enable_clean_scan,
    _stage_provider_attachment,
)


def setup_function() -> None:
    reset_database()


def _raw_pull_adapter(
    provider_kind: str = "microsoft_graph",
    *,
    credential_reference: str = "env://MCRI_LIVE_ACTIVATION_TEST_TOKEN",
    permissions: list[str] | None = None,
) -> tuple[dict, dict]:
    _, connection, _ = _connection()
    created = client.post(
        "/api/v1/email-ingestion/adapters",
        json={
            "connection_id": connection["id"],
            "provider_kind": provider_kind,
            "display_name": f"{provider_kind} activation test",
            "credential_reference": credential_reference,
            "allowed_folder": "INBOX" if provider_kind == "gmail_api" else "Claims",
            "permission_manifest": permissions
            or ["messages.read.allowed_folder", "attachments.metadata.read"],
            "batch_limit": 10,
            "retention_schedule_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    return connection, created.json()


def _activate(adapter_id: str, *, confirm: bool = True, reason: str | None = None):
    return client.post(
        f"/api/v1/email-ingestion/adapters/{adapter_id}/live-activation",
        json={
            "confirm_activation": confirm,
            "reason": reason
            or "Manager verified the local runtime credential boundary before live provider access.",
        },
    )


def test_pull_adapter_defaults_disabled_and_execution_never_reaches_provider(monkeypatch) -> None:
    _, adapter = _raw_pull_adapter()
    assert adapter["live_execution_enabled"] is False
    assert adapter["live_execution_enabled_at"] is None
    assert adapter["next_sync_at"] is None

    calls = {"count": 0}

    def must_not_call(*args, **kwargs):
        calls["count"] += 1
        raise AssertionError("Provider network must not be reached before explicit activation")

    monkeypatch.setattr(provider_execution, "_http_json", must_not_call)
    blocked = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "pre-activation-block-0001", "trigger": "manual"},
    )
    assert blocked.status_code == 409
    assert calls["count"] == 0

    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert reconciliation.status_code == 200
    item = next(value for value in reconciliation.json()["items"] if value["adapter_id"] == adapter["id"])
    assert item["operational_state"] == "activation_required"
    assert item["activation_blocker"] == "operator_activation_required"
    assert item["live_execution_enabled"] is False
    assert item["next_sync_at"] is None


def test_activation_is_local_content_free_preflight_and_does_not_call_provider(monkeypatch) -> None:
    _, adapter = _raw_pull_adapter()
    secret_value = "runtime-only-live-provider-secret"
    reason = "Manager confirmed the deployment-injected credential is ready for the private pilot."
    monkeypatch.setenv("MCRI_LIVE_ACTIVATION_TEST_TOKEN", secret_value)

    calls = {"count": 0}

    def must_not_call(*args, **kwargs):
        calls["count"] += 1
        raise AssertionError("Activation must not call Graph or Gmail")

    monkeypatch.setattr(provider_execution, "_http_json", must_not_call)
    activated = _activate(adapter["id"], reason=reason)
    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert body["live_execution_enabled"] is True
    assert body["live_execution_enabled_at"] is not None
    assert body["credential_backend"] == "env"
    assert body["credential_reference_version"] == 1
    assert body["checkpoint_present"] is False
    assert body["next_sync_at"] is not None
    assert calls["count"] == 0

    operations = client.get("/api/v1/email-ingestion/adapter-operations")
    view = next(value for value in operations.json()["adapters"] if value["id"] == adapter["id"])
    assert view["live_execution_enabled"] is True
    assert view["live_execution_enabled_at"] is not None
    serialized_view = str(view)
    assert "MCRI_LIVE_ACTIVATION_TEST_TOKEN" not in serialized_view
    assert secret_value not in serialized_view

    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == item.id,
                AuditLog.action == "ACTIVATE_EMAIL_PROVIDER_LIVE_EXECUTION",
            )
        )
        assert audit is not None
        serialized_audit = str(audit.new_values) + str(audit.details)
        assert "MCRI_LIVE_ACTIVATION_TEST_TOKEN" not in serialized_audit
        assert secret_value not in serialized_audit
        assert reason not in serialized_audit
        assert "env://" not in serialized_audit
        assert audit.new_values["credential_backend"] == "env"
        assert audit.new_values["operator_reason_supplied"] is True


def test_activation_fails_closed_for_missing_or_unsupported_runtime_credentials(monkeypatch) -> None:
    _, missing = _raw_pull_adapter()
    monkeypatch.delenv("MCRI_LIVE_ACTIVATION_TEST_TOKEN", raising=False)
    unresolved = _activate(missing["id"])
    assert unresolved.status_code == 409
    with TestingSessionLocal() as db:
        assert db.get(EmailProviderAdapter, UUID(missing["id"])).live_execution_enabled is False

    reset_database()
    _, vault = _raw_pull_adapter(credential_reference="vault://production/mcri/graph-alpha")
    unsupported = _activate(vault["id"])
    assert unsupported.status_code == 409
    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation").json()
    item = next(value for value in reconciliation["items"] if value["adapter_id"] == vault["id"])
    assert item["activation_blocker"] == "credential_resolver_unavailable"
    assert item["live_execution_enabled"] is False
    serialized = str(item)
    assert "production/mcri/graph-alpha" not in serialized
    assert "vault://" not in serialized


def test_activation_is_manager_only_and_not_available_for_webhooks(monkeypatch) -> None:
    _, adapter = _raw_pull_adapter()
    monkeypatch.setenv("MCRI_LIVE_ACTIVATION_TEST_TOKEN", "role-test-secret")
    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = _activate(adapter["id"])
    assert denied.status_code == 403

    reset_database()
    _, connection, _ = _connection()
    webhook = client.post(
        "/api/v1/email-ingestion/adapters",
        json={
            "connection_id": connection["id"],
            "provider_kind": "provider_webhook",
            "display_name": "Webhook activation test",
            "credential_reference": "env://WEBHOOK_ACTIVATION_TOKEN",
            "allowed_folder": "Claims",
            "permission_manifest": ["messages.read.allowed_folder"],
            "batch_limit": 10,
            "retention_schedule_enabled": True,
        },
    ).json()
    monkeypatch.setenv("WEBHOOK_ACTIVATION_TOKEN", "webhook-secret")
    rejected = _activate(webhook["id"])
    assert rejected.status_code == 409


def test_activation_requires_selected_folder_read_permission_and_no_pending_handoff(monkeypatch) -> None:
    _, no_read = _raw_pull_adapter(permissions=["attachments.metadata.read"])
    monkeypatch.setenv("MCRI_LIVE_ACTIVATION_TEST_TOKEN", "permission-test-secret")
    denied = _activate(no_read["id"])
    assert denied.status_code == 409

    reset_database()
    _, pending = _raw_pull_adapter()
    monkeypatch.setenv("MCRI_LIVE_ACTIVATION_TEST_TOKEN", "pending-handoff-secret")
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(pending["id"]))
        db.add(
            EmailAdapterRun(
                organization_id=item.organization_id,
                adapter_id=item.id,
                initiated_by_id=None,
                idempotency_key="pending-run",
                trigger="manual",
                status="succeeded",
                messages_seen=0,
                messages_ingested=0,
                checkpoint_hash=sha256(b"pending-activation-cursor").hexdigest(),
                checkpoint_handoff_status="pending",
                failure_summary=None,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        db.commit()
    blocked = _activate(pending["id"])
    assert blocked.status_code == 409
    with TestingSessionLocal() as db:
        assert db.get(EmailProviderAdapter, UUID(pending["id"])).live_execution_enabled is False


def test_credential_rotation_and_lifecycle_transitions_require_reactivation(monkeypatch) -> None:
    connection, adapter = _raw_pull_adapter()
    monkeypatch.setenv("MCRI_LIVE_ACTIVATION_TEST_TOKEN", "initial-secret")
    assert _activate(adapter["id"]).status_code == 200

    rotated = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/credential-reference-rotation",
        json={
            "confirm_rotation": True,
            "credential_reference": "env://MCRI_ROTATED_LIVE_TOKEN",
            "reason": "Rotate the credential reference and require a fresh operator live readiness decision.",
        },
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["live_execution_enabled"] is False
    assert rotated.json()["next_sync_at"] is None

    monkeypatch.setenv("MCRI_ROTATED_LIVE_TOKEN", "rotated-secret")
    assert _activate(adapter["id"]).status_code == 200
    suspended = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "suspend", "note": "Pause the live provider source for an operational review."},
    )
    assert suspended.status_code == 200
    assert suspended.json()["live_execution_enabled"] is False
    reactivated = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "reactivate", "note": "Restore configuration only; live access needs a new preflight."},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["live_execution_enabled"] is False
    assert reactivated.json()["next_sync_at"] is None

    assert _activate(adapter["id"]).status_code == 200
    connection_suspended = client.post(
        f"/api/v1/email-ingestion/connections/{connection['id']}/transition",
        json={"action": "suspend", "note": "Pause mailbox consented connection for operational review."},
    )
    assert connection_suspended.status_code == 200
    connection_reactivated = client.post(
        f"/api/v1/email-ingestion/connections/{connection['id']}/transition",
        json={"action": "reactivate", "note": "Restore consented configuration; require live preflight again."},
    )
    assert connection_reactivated.status_code == 200
    operations = client.get("/api/v1/email-ingestion/adapter-operations").json()
    view = next(value for value in operations["adapters"] if value["id"] == adapter["id"])
    assert view["live_execution_enabled"] is False
    assert view["next_sync_at"] is None


def test_fresh_attachment_network_access_is_blocked_after_activation_is_cleared(monkeypatch) -> None:
    _, adapter, message_id, manifest_id = _stage_provider_attachment(linked=True)
    calls = _enable_clean_scan(monkeypatch)
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        item.live_execution_enabled = False
        item.live_execution_enabled_at = None
        item.live_execution_enabled_by_id = None
        item.next_sync_at = None
        db.commit()

    blocked = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert blocked.status_code == 409
    assert calls == {"locator": 0, "fetch": 0, "scan": 0}


def test_existing_quarantine_replay_remains_local_after_live_authority_is_cleared(monkeypatch) -> None:
    _, adapter, message_id, manifest_id = _stage_provider_attachment(linked=True)
    calls = _enable_clean_scan(monkeypatch)
    first = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert first.status_code == 200, first.text
    assert first.json()["replayed"] is False
    assert calls == {"locator": 1, "fetch": 1, "scan": 1}

    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        item.live_execution_enabled = False
        item.live_execution_enabled_at = None
        item.live_execution_enabled_by_id = None
        item.next_sync_at = None
        db.commit()

    replay = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert calls == {"locator": 1, "fetch": 1, "scan": 1}
