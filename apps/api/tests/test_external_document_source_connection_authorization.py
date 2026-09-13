from datetime import timedelta
from uuid import UUID

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.connection_authorization_models import (
    ExternalDocumentSourceConnectionAuthorization,
    ExternalDocumentSourceConnectionAuthorizationReceipt,
)
from app.modules.external_document_sources.connection_authorization_service import (
    get_external_document_source_connection_authorization,
)
from app.modules.external_document_sources.discovery_service import (
    clear_external_document_source_discovery_adapters,
    register_external_document_source_discovery_adapter,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_discovery import (
    _DeterministicSharePointAdapter,
    _create_profile,
    _discover,
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()


def _profile_and_discovery(requester_id: UUID, approver_id: UUID) -> tuple[str, str]:
    profile_id = _create_profile(requester_id, approver_id)
    register_external_document_source_discovery_adapter("sharepoint", _DeterministicSharePointAdapter())
    discovery = _discover(profile_id, requester_id, key="connection-auth-discovery")
    assert discovery.status_code == 201, discovery.text
    return profile_id, discovery.json()["id"]


def _request_authorization(profile_id: str, run_id: str, requester_id: UUID, *, key: str = "connection-auth-001"):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}/connection-authorizations",
        headers=_headers(requester_id),
        json={
            "request_key": key,
            "reason": "Authorize one later bounded provider connection bootstrap without executing provider traffic.",
        },
    )


def test_connection_authorization_requires_four_eyes_and_grants_no_execution_authority() -> None:
    _, requester_id, approver_id = _seed_tenant("conn-auth-success")
    profile_id, run_id = _profile_and_discovery(requester_id, approver_id)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    requested = _request_authorization(profile_id, run_id, requester_id)
    assert requested.status_code == 201, requested.text
    body = requested.json()
    authorization_id = body["id"]
    assert body["status"] == "pending_second_approval"
    assert body["execution_limit"] == 1
    assert body["live_connection_authorized"] is False
    assert len(body["scope_hash"]) == 64
    assert len(body["request_hash"]) == 64
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
    ):
        assert body[field] is False

    replay = _request_authorization(profile_id, run_id, requester_id)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == authorization_id

    self_approval = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/approve",
        headers=_headers(requester_id),
        json={"reason": "Attempt to approve the same authorization without independent second approval."},
    )
    assert self_approval.status_code == 409, self_approval.text

    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/approve",
        headers=_headers(approver_id),
        json={"reason": "Independently approve one short-lived connection bootstrap authorization only."},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "authorized"
    assert approved_body["live_connection_authorized"] is True
    assert approved_body["approved_by_id"] == str(approver_id)
    assert len(approved_body["authorization_hash"]) == 64
    assert approved_body["authorization_expires_at"] is not None
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
    ):
        assert approved_body[field] is False

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/receipts",
        headers=_headers(approver_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "authorized"]
    assert [row["sequence_number"] for row in rows] == [1, 2]
    assert rows[0]["live_connection_authorized"] is False
    assert rows[1]["live_connection_authorized"] is True
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceConnectionAuthorization).count() == 1
        assert db.query(ExternalDocumentSourceConnectionAuthorizationReceipt).count() == 2


def test_authorized_connection_bootstrap_expires_fail_closed_without_execution() -> None:
    org_id, requester_id, approver_id = _seed_tenant("conn-auth-expiry")
    profile_id, run_id = _profile_and_discovery(requester_id, approver_id)
    requested = _request_authorization(profile_id, run_id, requester_id, key="connection-expiry")
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/approve",
        headers=_headers(approver_id),
        json={"reason": "Approve only the bounded short-lived connection bootstrap authorization."},
    )
    assert approved.status_code == 200, approved.text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceConnectionAuthorization, UUID(authorization_id))
        assert row is not None and row.authorization_expires_at is not None
        future = row.authorization_expires_at + timedelta(seconds=1)
        expired, outcome = get_external_document_source_connection_authorization(
            db,
            organization_id=org_id,
            profile_id=UUID(profile_id),
            authorization_id=UUID(authorization_id),
            now=future,
        )
        assert outcome == "expired"
        assert expired.status == "expired"
        assert expired.live_connection_authorized is False
        assert expired.oauth_token_exchanged is False
        assert expired.remote_read_performed is False
        assert expired.evidence_admitted is False
        db.commit()

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    assert [row["event_type"] for row in receipts.json()] == ["requested", "authorized", "expired"]


def test_profile_disable_blocks_pending_connection_authorization_approval() -> None:
    _, requester_id, approver_id = _seed_tenant("conn-auth-disable")
    profile_id, run_id = _profile_and_discovery(requester_id, approver_id)
    requested = _request_authorization(profile_id, run_id, requester_id, key="connection-disable")
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the governed source profile before provider connection authority is approved."},
    )
    assert disabled.status_code == 200, disabled.text

    blocked = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/approve",
        headers=_headers(approver_id),
        json={"reason": "Attempt approval after the governed external source profile was disabled."},
    )
    assert blocked.status_code == 409, blocked.text


def test_connection_authorization_reads_are_tenant_isolated() -> None:
    _, requester_id, approver_id = _seed_tenant("conn-auth-tenant-a")
    _, other_requester_id, _ = _seed_tenant("conn-auth-tenant-b")
    profile_id, run_id = _profile_and_discovery(requester_id, approver_id)
    requested = _request_authorization(profile_id, run_id, requester_id, key="connection-tenant")
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]

    hidden = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}",
        headers=_headers(other_requester_id),
    )
    assert hidden.status_code == 404, hidden.text


def test_connection_authorization_receipt_tamper_fails_closed() -> None:
    _, requester_id, approver_id = _seed_tenant("conn-auth-tamper")
    profile_id, run_id = _profile_and_discovery(requester_id, approver_id)
    requested = _request_authorization(profile_id, run_id, requester_id, key="connection-tamper")
    assert requested.status_code == 201, requested.text
    authorization_id = UUID(requested.json()["id"])

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceConnectionAuthorizationReceipt)
            .filter_by(authorization_id=authorization_id, sequence_number=1)
            .one()
        )
        receipt.receipt_hash = "0" * 64
        db.commit()

    blocked = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}",
        headers=_headers(approver_id),
    )
    assert blocked.status_code == 409, blocked.text
    assert "integrity" in blocked.text.lower() or "receipt" in blocked.text.lower()
