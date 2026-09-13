from datetime import datetime, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.discovery_service import (
    ExternalDocumentSourceMetadataItem,
    clear_external_document_source_discovery_adapters,
    register_external_document_source_discovery_adapter,
)
from app.modules.external_document_sources.models import (
    ExternalDocumentSourceDiscoveryItem,
    ExternalDocumentSourceDiscoveryReceipt,
    ExternalDocumentSourceDiscoveryRun,
)
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


class _DeterministicSharePointAdapter:
    adapter_kind = "deterministic-sharepoint-test-v1"

    def list_metadata(self, *, provider_kind: str, normalized_config: dict[str, str], max_results: int):
        assert provider_kind == "sharepoint"
        assert normalized_config["site_id"] == "site-001"
        rows = [
            ExternalDocumentSourceMetadataItem(
                provider_item_id="item-b",
                parent_item_id="folder-root",
                display_name="Survey Report.pdf",
                item_kind="file",
                mime_type="application/pdf",
                size_bytes=2048,
                modified_at=datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc),
                provider_etag="etag-b",
            ),
            ExternalDocumentSourceMetadataItem(
                provider_item_id="item-a",
                display_name="Claims",
                item_kind="folder",
                provider_etag="etag-a",
            ),
        ]
        return rows[:max_results]


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()


def _headers(user_id: UUID) -> dict[str, str]:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        session = create_auth_session(db, user=user)
        db.commit()
        token = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
            session_id=session.id,
            identity_source=session.identity_source,
            auth_method=session.auth_method,
        )
    return {"Authorization": f"Bearer {token}"}


def _seed_tenant(slug: str):
    with TestingSessionLocal() as db:
        org = Organization(name=f"Discovery {slug}", slug=f"discovery-{slug}")
        db.add(org)
        db.flush()
        requester = User(
            organization_id=org.id,
            email=f"requester-{slug}@example.com",
            full_name=f"Requester {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        approver = User(
            organization_id=org.id,
            email=f"approver-{slug}@example.com",
            full_name=f"Approver {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add_all([requester, approver])
        db.commit()
        return org.id, requester.id, approver.id


def _create_profile(requester_id: UUID, approver_id: UUID, *, approve: bool = True) -> str:
    requested = client.post(
        "/api/v1/external-document-sources/profiles",
        headers=_headers(requester_id),
        json={
            "provider_kind": "sharepoint",
            "display_name": "Claims Evidence Library",
            "config": {
                "tenant_domain": "example.onmicrosoft.com",
                "site_id": "site-001",
                "library_id": "library-001",
            },
            "reason": "Govern this SharePoint source before any read-only metadata discovery.",
        },
    )
    assert requested.status_code == 201, requested.text
    profile_id = requested.json()["id"]
    if approve:
        approved = client.post(
            f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
            headers=_headers(approver_id),
            json={"reason": "Independently approve this configuration-only external source profile."},
        )
        assert approved.status_code == 200, approved.text
    return profile_id


def _discover(profile_id: str, requester_id: UUID, *, key: str = "discovery-001", max_results: int = 100):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/discoveries",
        headers=_headers(requester_id),
        json={"request_key": key, "max_results": max_results},
    )


def test_metadata_only_discovery_is_deterministic_idempotent_and_has_zero_ingestion_authority() -> None:
    _, requester_id, approver_id = _seed_tenant("success")
    profile_id = _create_profile(requester_id, approver_id)
    register_external_document_source_discovery_adapter("sharepoint", _DeterministicSharePointAdapter())

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    response = _discover(profile_id, requester_id)
    assert response.status_code == 201, response.text
    body = response.json()
    run_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_count"] == 2
    assert body["adapter_kind"] == "deterministic-sharepoint-test-v1"
    assert len(body["scope_hash"]) == 64
    assert len(body["manifest_hash"]) == 64
    assert len(body["run_hash"]) == 64
    assert body["remote_list_performed"] is True
    for field in (
        "credential_stored",
        "oauth_token_exchanged",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "subscription_created",
        "sync_executed",
        "evidence_admitted",
        "document_created",
        "claim_mutated",
        "live_connection_authorized",
    ):
        assert body[field] is False

    items = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}/items",
        headers=_headers(requester_id),
    )
    assert items.status_code == 200, items.text
    rows = items.json()
    assert [row["provider_item_id"] for row in rows] == ["item-a", "item-b"]
    assert [row["ordinal"] for row in rows] == [1, 2]
    assert all(len(row["item_hash"]) == 64 for row in rows)

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == ["requested", "completed"]
    assert receipt_rows[0]["remote_list_performed"] is False
    assert receipt_rows[1]["remote_list_performed"] is True
    assert receipt_rows[1]["prior_receipt_hash"] == receipt_rows[0]["receipt_hash"]

    replay = _discover(profile_id, requester_id)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == run_id
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceDiscoveryRun).count() == 1
        assert db.query(ExternalDocumentSourceDiscoveryItem).count() == 2
        assert db.query(ExternalDocumentSourceDiscoveryReceipt).count() == 2
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before


def test_discovery_requires_active_profile_and_enabled_adapter() -> None:
    _, requester_id, approver_id = _seed_tenant("gates")
    pending_profile_id = _create_profile(requester_id, approver_id, approve=False)
    pending = _discover(pending_profile_id, requester_id)
    assert pending.status_code == 409, pending.text
    assert "active" in pending.text.lower()

    active_profile_id = _create_profile(requester_id, approver_id)
    unavailable = _discover(active_profile_id, requester_id, key="no-live-adapter")
    assert unavailable.status_code == 409, unavailable.text
    assert "adapter is not enabled" in unavailable.text.lower()
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceDiscoveryRun).count() == 0


def test_request_key_conflict_and_tenant_isolation_fail_closed() -> None:
    _, requester_id, approver_id = _seed_tenant("tenant-a")
    _, other_requester_id, _ = _seed_tenant("tenant-b")
    profile_id = _create_profile(requester_id, approver_id)
    register_external_document_source_discovery_adapter("sharepoint", _DeterministicSharePointAdapter())
    first = _discover(profile_id, requester_id, key="stable-key", max_results=100)
    assert first.status_code == 201, first.text
    run_id = first.json()["id"]

    conflict = _discover(profile_id, requester_id, key="stable-key", max_results=1)
    assert conflict.status_code == 409, conflict.text

    hidden = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}",
        headers=_headers(other_requester_id),
    )
    assert hidden.status_code == 404, hidden.text


def test_item_tamper_and_receipt_truncation_are_detected() -> None:
    _, requester_id, approver_id = _seed_tenant("tamper")
    profile_id = _create_profile(requester_id, approver_id)
    register_external_document_source_discovery_adapter("sharepoint", _DeterministicSharePointAdapter())
    created = _discover(profile_id, requester_id, key="tamper-item")
    assert created.status_code == 201, created.text
    run_id = UUID(created.json()["id"])

    with TestingSessionLocal() as db:
        item = db.query(ExternalDocumentSourceDiscoveryItem).filter_by(run_id=run_id, ordinal=1).one()
        item.display_name = "Tampered name"
        db.commit()
    blocked = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}",
        headers=_headers(requester_id),
    )
    assert blocked.status_code == 409, blocked.text
    assert "integrity" in blocked.text.lower()

    reset_database()
    clear_external_document_source_discovery_adapters()
    _, requester_id, approver_id = _seed_tenant("truncate")
    profile_id = _create_profile(requester_id, approver_id)
    register_external_document_source_discovery_adapter("sharepoint", _DeterministicSharePointAdapter())
    created = _discover(profile_id, requester_id, key="truncate-receipt")
    assert created.status_code == 201, created.text
    run_id = UUID(created.json()["id"])
    with TestingSessionLocal() as db:
        completed = db.query(ExternalDocumentSourceDiscoveryReceipt).filter_by(run_id=run_id, sequence_number=2).one()
        db.delete(completed)
        db.commit()
    blocked = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}",
        headers=_headers(requester_id),
    )
    assert blocked.status_code == 409, blocked.text
    assert "lifecycle" in blocked.text.lower()
