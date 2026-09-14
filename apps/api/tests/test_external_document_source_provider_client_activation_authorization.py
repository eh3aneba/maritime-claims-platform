from datetime import timedelta
from uuid import UUID

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.credential_reference_health_service import (
    clear_external_document_source_credential_reference_health_resolvers,
    register_external_document_source_credential_reference_health_resolver,
)
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_activation_authorization_models import (
    ExternalDocumentSourceProviderClientActivationAuthorization,
    ExternalDocumentSourceProviderClientActivationAuthorizationReceipt,
)
from app.modules.external_document_sources.provider_client_activation_authorization_service import (
    get_external_document_source_provider_client_activation_authorization,
    reject_external_document_source_provider_client_activation_authorization,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_credential_reference_health import (
    _DEFAULT_REASON as HEALTH_REASON,
    _DeterministicResolver,
    _active_binding,
    _additional_active_binding,
    _qualify,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant

_REQUEST_REASON = "Authorize one later bounded provider-client activation only, without OAuth or provider traffic."
_APPROVAL_REASON = "Independently approve one short-lived provider-client activation authorization only."
_REJECTION_REASON = "Independently reject this provider-client activation authorization without provider execution."


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()


def _request(profile_id: str, qualification_id: str, actor_id: UUID, *, key: str, reason: str = _REQUEST_REASON):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}/provider-client-activation-authorizations",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def _approve(profile_id: str, authorization_id: str, actor_id: UUID, *, reason: str = _APPROVAL_REASON):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/approve",
        headers=_headers(actor_id),
        json={"reason": reason},
    )


def test_provider_client_activation_authorization_full_governance_without_provider_execution() -> None:
    requester_id, approver_id, profile_id, run_id, binding_id = _active_binding("provider-client-activation")
    resolver = _DeterministicResolver(resolvable=True)
    register_external_document_source_credential_reference_health_resolver("azure_key_vault", resolver)
    qualified = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="provider-client-activation-health",
        reason=HEALTH_REASON,
    )
    assert qualified.status_code == 201, qualified.text
    assert qualified.json()["result_status"] == "resolvable"
    qualification_id = qualified.json()["id"]

    _, other_requester, _ = _seed_tenant("provider-client-activation-other-tenant")
    wrong_tenant = _request(profile_id, qualification_id, other_requester, key="provider-client-activation-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    requested = _request(profile_id, qualification_id, requester_id, key="provider-client-activation-001")
    assert requested.status_code == 201, requested.text
    body = requested.json()
    authorization_id = body["id"]
    assert body["status"] == "pending_second_approval"
    assert body["execution_limit"] == 1
    assert body["health_result_status"] == "resolvable"
    assert body["provider_client_activation_authorized"] is False
    assert body["credential_reference_stored"] is True
    for field in (
        "credential_reference_resolution_performed",
        "credential_stored",
        "oauth_authorization_code_stored",
        "oauth_token_exchanged",
        "access_token_stored",
        "refresh_token_stored",
        "client_secret_stored",
        "private_key_stored",
        "provider_network_performed",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "subscription_created",
        "checkpoint_created",
        "sync_executed",
        "evidence_admitted",
        "document_created",
        "claim_mutated",
    ):
        assert body[field] is False

    replay = _request(profile_id, qualification_id, requester_id, key="provider-client-activation-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == authorization_id

    changed_replay = _request(
        profile_id,
        qualification_id,
        requester_id,
        key="provider-client-activation-001",
        reason="Attempt to change the governed activation authorization request after its first immutable request.",
    )
    assert changed_replay.status_code == 409, changed_replay.text

    # Exercise pending-review expiry on the same real lineage, but roll the
    # transaction back so this one authorization can continue through the
    # independent rejection and approval paths without another expensive setup.
    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceProviderClientActivationAuthorization, UUID(authorization_id))
        assert row is not None
        pending_future = row.review_expires_at + timedelta(seconds=1)
        pending_expired, outcome = get_external_document_source_provider_client_activation_authorization(
            db,
            organization_id=row.organization_id,
            profile_id=row.profile_id,
            authorization_id=row.id,
            now=pending_future,
        )
        assert outcome == "expired"
        assert pending_expired.status == "expired"
        assert pending_expired.authorization_hash is None
        assert pending_expired.provider_client_activation_authorized is False
        db.rollback()

    # Exercise the independent rejection lifecycle in a rollback transaction,
    # preserving the committed pending state for the real approval path below.
    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceProviderClientActivationAuthorization, UUID(authorization_id))
        assert row is not None
        rejected, outcome = reject_external_document_source_provider_client_activation_authorization(
            db,
            organization_id=row.organization_id,
            profile_id=row.profile_id,
            authorization_id=row.id,
            rejected_by_id=approver_id,
            decision_reason=_REJECTION_REASON,
        )
        assert outcome == "rejected"
        assert rejected.status == "rejected"
        assert rejected.terminal_by_id == approver_id
        assert rejected.provider_client_activation_authorized is False
        db.rollback()

    self_approval = _approve(profile_id, authorization_id, requester_id)
    assert self_approval.status_code == 409, self_approval.text

    approved = _approve(profile_id, authorization_id, approver_id)
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "authorized"
    assert approved_body["provider_client_activation_authorized"] is True
    assert approved_body["approved_by_id"] == str(approver_id)
    assert len(approved_body["authorization_hash"]) == 64
    assert approved_body["authorization_expires_at"] is not None
    assert approved_body["oauth_token_exchanged"] is False
    assert approved_body["provider_network_performed"] is False
    assert approved_body["remote_read_performed"] is False
    assert approved_body["evidence_admitted"] is False

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "authorized"]
    assert [row["provider_client_activation_authorized"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceProviderClientActivationAuthorization).count() == 1
        assert db.query(ExternalDocumentSourceProviderClientActivationAuthorizationReceipt).count() == 2
        receipt = (
            db.query(ExternalDocumentSourceProviderClientActivationAuthorizationReceipt)
            .filter(
                ExternalDocumentSourceProviderClientActivationAuthorizationReceipt.authorization_id == UUID(authorization_id),
                ExternalDocumentSourceProviderClientActivationAuthorizationReceipt.sequence_number == 1,
            )
            .one()
        )
        receipt.reason = "Tampered Phase G request receipt reason."
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceProviderClientActivationAuthorizationReceipt)
            .filter(
                ExternalDocumentSourceProviderClientActivationAuthorizationReceipt.authorization_id == UUID(authorization_id),
                ExternalDocumentSourceProviderClientActivationAuthorizationReceipt.sequence_number == 1,
            )
            .one()
        )
        receipt.reason = _REQUEST_REASON
        row = db.get(ExternalDocumentSourceProviderClientActivationAuthorization, UUID(authorization_id))
        assert row is not None and row.authorization_expires_at is not None
        future = row.authorization_expires_at + timedelta(seconds=1)
        expired, outcome = get_external_document_source_provider_client_activation_authorization(
            db,
            organization_id=row.organization_id,
            profile_id=row.profile_id,
            authorization_id=row.id,
            now=future,
        )
        assert outcome == "expired"
        assert expired.status == "expired"
        assert expired.provider_client_activation_authorized is False
        db.commit()

    expired_read = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}",
        headers=_headers(requester_id),
    )
    assert expired_read.status_code == 200, expired_read.text
    assert expired_read.json()["status"] == "expired"
    assert expired_read.json()["provider_client_activation_authorized"] is False

    expired_receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/receipts",
        headers=_headers(requester_id),
    )
    assert expired_receipts.status_code == 200, expired_receipts.text
    assert [row["event_type"] for row in expired_receipts.json()] == ["requested", "authorized", "expired"]

    clear_external_document_source_credential_reference_health_resolvers()
    second_binding_id = _additional_active_binding(
        profile_id,
        run_id,
        requester_id,
        approver_id,
        seed="provider-client-activation-unresolvable",
    )
    unresolvable_resolver = _DeterministicResolver(resolvable=False, failure_code="reference_not_found")
    register_external_document_source_credential_reference_health_resolver("azure_key_vault", unresolvable_resolver)
    unresolvable = _qualify(
        profile_id,
        second_binding_id,
        requester_id,
        key="provider-client-activation-unresolvable-health",
    )
    assert unresolvable.status_code == 201, unresolvable.text
    assert unresolvable.json()["result_status"] == "unresolvable"

    denied = _request(
        profile_id,
        unresolvable.json()["id"],
        requester_id,
        key="provider-client-activation-denied",
    )
    assert denied.status_code == 409, denied.text

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so the completed Phase G lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text

    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceProviderClientActivationAuthorization).count() == 1
