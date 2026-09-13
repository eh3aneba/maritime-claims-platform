from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.models import (
    ExternalDocumentSourceProfile,
    ExternalDocumentSourceProfileReceipt,
)
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


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
        org = Organization(name=f"External Source {slug}", slug=f"external-source-{slug}")
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
        manager = User(
            organization_id=org.id,
            email=f"manager-{slug}@example.com",
            full_name=f"Manager {slug}",
            password_hash="local",
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        db.add_all([requester, approver, manager])
        db.commit()
        return org.id, requester.id, approver.id, manager.id


def _request_sharepoint(headers: dict[str, str], *, extra_config: dict | None = None):
    config = {
        "tenant_domain": " Example.ONMICROSOFT.com ",
        "site_id": "site-001",
        "library_id": "library-001",
    }
    if extra_config:
        config.update(extra_config)
    return client.post(
        "/api/v1/external-document-sources/profiles",
        headers=headers,
        json={
            "provider_kind": "sharepoint",
            "display_name": " Claims Evidence Library ",
            "config": config,
            "reason": "Govern the intended SharePoint evidence source before any provider connection exists.",
        },
    )


def test_sharepoint_profile_requires_independent_approval_and_never_creates_live_authority() -> None:
    org_id, requester_id, approver_id, manager_id = _seed_tenant("sharepoint")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    manager_headers = _headers(manager_id)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    requested = _request_sharepoint(requester_headers)
    assert requested.status_code == 201, requested.text
    body = requested.json()
    profile_id = body["id"]
    assert body["organization_id"] == str(org_id)
    assert body["status"] == "pending_second_approval"
    assert body["provider_kind"] == "sharepoint"
    assert body["display_name"] == "Claims Evidence Library"
    assert body["normalized_config"] == {
        "library_id": "library-001",
        "site_id": "site-001",
        "tenant_domain": "example.onmicrosoft.com",
    }
    assert len(body["config_hash"]) == 64
    assert len(body["profile_hash"]) == 64
    for field in (
        "credential_stored",
        "oauth_token_exchanged",
        "remote_list_performed",
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

    replay = _request_sharepoint(requester_headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == profile_id

    self_approval = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=requester_headers,
        json={"reason": "Independently approve the governed source profile configuration."},
    )
    assert self_approval.status_code == 409, self_approval.text

    manager_attempt = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=manager_headers,
        json={"reason": "Attempt approval without the required administrator role."},
    )
    assert manager_attempt.status_code == 403, manager_attempt.text

    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=approver_headers,
        json={"reason": "Independently approve the governed source profile configuration."},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "active"
    assert approved_body["approved_by_id"] == str(approver_id)
    assert len(approved_body["approval_hash"]) == 64
    assert approved_body["live_connection_authorized"] is False
    assert approved_body["credential_stored"] is False
    assert approved_body["remote_read_performed"] is False
    assert approved_body["evidence_admitted"] is False

    replay_approval = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=approver_headers,
        json={"reason": "Independently approve the governed source profile configuration."},
    )
    assert replay_approval.status_code == 200, replay_approval.text
    assert replay_approval.json()["approval_hash"] == approved_body["approval_hash"]

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/receipts",
        headers=approver_headers,
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "approved"]
    assert [row["sequence_number"] for row in rows] == [1, 2]
    assert rows[0]["prior_receipt_hash"] is None
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert all(row["live_connection_authorized"] is False for row in rows)
    assert all(row["remote_read_performed"] is False for row in rows)

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceProfile).count() == 1
        assert db.query(ExternalDocumentSourceProfileReceipt).count() == 2


def test_unknown_or_secret_like_provider_fields_are_rejected_fail_closed() -> None:
    _, requester_id, _, _ = _seed_tenant("secret-reject")
    response = _request_sharepoint(
        _headers(requester_id),
        extra_config={"client_secret": "must-never-be-stored"},
    )
    assert response.status_code == 422, response.text
    assert "unsupported or secret-like" in response.text.lower()
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceProfile).count() == 0
        assert db.query(ExternalDocumentSourceProfileReceipt).count() == 0


def test_google_drive_profile_can_be_approved_then_disabled_without_remote_execution() -> None:
    _, requester_id, approver_id, _ = _seed_tenant("drive")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = client.post(
        "/api/v1/external-document-sources/profiles",
        headers=requester_headers,
        json={
            "provider_kind": "google_drive",
            "display_name": "Shared Claims Drive",
            "config": {"shared_drive_id": "drive-123", "folder_id": "folder-456"},
            "reason": "Govern the intended shared drive scope before any Google provider connection.",
        },
    )
    assert requested.status_code == 201, requested.text
    profile_id = requested.json()["id"]

    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=approver_headers,
        json={"reason": "Approve only the non-secret governed drive source scope."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/disable",
        headers=requester_headers,
        json={"reason": "Disable this governed source profile without touching the remote provider."},
    )
    assert disabled.status_code == 200, disabled.text
    body = disabled.json()
    assert body["status"] == "disabled"
    assert len(body["terminal_hash"]) == 64
    assert body["live_connection_authorized"] is False
    assert body["oauth_token_exchanged"] is False
    assert body["sync_executed"] is False

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/receipts",
        headers=requester_headers,
    )
    assert receipts.status_code == 200, receipts.text
    assert [row["event_type"] for row in receipts.json()] == ["requested", "approved", "disabled"]


def test_profile_reads_are_tenant_isolated() -> None:
    _, requester_id, _, _ = _seed_tenant("tenant-a")
    _, other_requester_id, _, _ = _seed_tenant("tenant-b")
    requested = _request_sharepoint(_headers(requester_id))
    assert requested.status_code == 201, requested.text
    profile_id = requested.json()["id"]

    hidden = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}",
        headers=_headers(other_requester_id),
    )
    assert hidden.status_code == 404, hidden.text


def test_receipt_tamper_blocks_further_governance_transition() -> None:
    _, requester_id, approver_id, _ = _seed_tenant("tamper")
    requested = _request_sharepoint(_headers(requester_id))
    assert requested.status_code == 201, requested.text
    profile_id = UUID(requested.json()["id"])
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceProfileReceipt).filter_by(profile_id=profile_id).one()
        receipt.receipt_hash = "0" * 64
        db.commit()

    blocked = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=_headers(approver_id),
        json={"reason": "Attempt approval after the lifecycle receipt was tampered."},
    )
    assert blocked.status_code == 409, blocked.text
    assert "integrity" in blocked.text.lower()
