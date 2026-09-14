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
)
from app.modules.external_document_sources.provider_client_activation_authorization_service import (
    get_external_document_source_provider_client_activation_authorization,
    reject_external_document_source_provider_client_activation_authorization,
)
from app.modules.external_document_sources.provider_client_activation_execution_models import (
    ExternalDocumentSourceProviderClientActivationExecution,
    ExternalDocumentSourceProviderClientActivationExecutionReceipt,
)
from app.modules.external_document_sources.provider_client_activation_execution_service import (
    execute_external_document_source_provider_client_activation,
)
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_credential_reference_health import (
    _DEFAULT_REASON as HEALTH_REASON,
    _DeterministicResolver,
    _active_binding,
    _qualify,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_provider_client_activation_authorization import (
    _approve as _approve_activation_authorization,
    _request as _request_activation_authorization,
)

_EXECUTION_REASON = "Consume one bounded provider-client activation authorization locally without OAuth or provider traffic."
_REJECTION_REASON = "Reject this provider-client activation authorization before Phase H execution without provider traffic."


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()


def _execute(profile_id: str, authorization_id: str, actor_id: UUID, *, key: str, reason: str = _EXECUTION_REASON):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/activation-executions",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_provider_client_activation_execution_consumes_one_authorization_without_provider_authority() -> None:
    requester_id, approver_id, profile_id, _, binding_id = _active_binding("provider-client-activation-execution")
    register_external_document_source_credential_reference_health_resolver(
        "azure_key_vault",
        _DeterministicResolver(resolvable=True),
    )
    qualified = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="provider-client-activation-execution-health",
        reason=HEALTH_REASON,
    )
    assert qualified.status_code == 201, qualified.text
    assert qualified.json()["result_status"] == "resolvable"
    qualification_id = qualified.json()["id"]

    requested = _request_activation_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="provider-client-activation-execution-authorization",
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    assert requested.json()["status"] == "pending_second_approval"

    # Pending authorization is not consumable.
    pending = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="provider-client-activation-execution-pending",
    )
    assert pending.status_code == 409, pending.text

    # Exercise a legitimate rejected G state on the same lineage, then roll it
    # back so the committed authorization can continue to the approval path.
    with TestingSessionLocal() as db:
        authorization = db.get(ExternalDocumentSourceProviderClientActivationAuthorization, UUID(authorization_id))
        assert authorization is not None
        rejected, outcome = reject_external_document_source_provider_client_activation_authorization(
            db,
            organization_id=authorization.organization_id,
            profile_id=authorization.profile_id,
            authorization_id=authorization.id,
            rejected_by_id=approver_id,
            decision_reason=_REJECTION_REASON,
        )
        assert outcome == "rejected"
        assert rejected.status == "rejected"
        try:
            execute_external_document_source_provider_client_activation(
                db,
                organization_id=authorization.organization_id,
                profile_id=authorization.profile_id,
                authorization_id=authorization.id,
                requested_by_id=requester_id,
                request_key="provider-client-activation-execution-rejected",
                request_reason=_EXECUTION_REASON,
            )
        except ExternalDocumentSourceConflictError:
            pass
        else:
            raise AssertionError("Rejected Phase G authorization must not be consumable")
        db.rollback()

    approved = _approve_activation_authorization(profile_id, authorization_id, approver_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "authorized"
    assert approved.json()["provider_client_activation_authorized"] is True

    # Exercise approved-but-expired G state in a rollback transaction, preserving
    # the committed authorized state for the successful H consumption below.
    with TestingSessionLocal() as db:
        authorization = db.get(ExternalDocumentSourceProviderClientActivationAuthorization, UUID(authorization_id))
        assert authorization is not None and authorization.authorization_expires_at is not None
        future = authorization.authorization_expires_at + timedelta(seconds=1)
        expired, outcome = get_external_document_source_provider_client_activation_authorization(
            db,
            organization_id=authorization.organization_id,
            profile_id=authorization.profile_id,
            authorization_id=authorization.id,
            now=future,
        )
        assert outcome == "expired"
        assert expired.status == "expired"
        try:
            execute_external_document_source_provider_client_activation(
                db,
                organization_id=authorization.organization_id,
                profile_id=authorization.profile_id,
                authorization_id=authorization.id,
                requested_by_id=requester_id,
                request_key="provider-client-activation-execution-expired",
                request_reason=_EXECUTION_REASON,
                now=future,
            )
        except ExternalDocumentSourceConflictError:
            pass
        else:
            raise AssertionError("Expired Phase G authorization must not be consumable")
        db.rollback()

    _, other_requester, _ = _seed_tenant("provider-client-activation-execution-other-tenant")
    wrong_tenant = _execute(
        profile_id,
        authorization_id,
        other_requester,
        key="provider-client-activation-execution-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    executed = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="provider-client-activation-execution-001",
    )
    assert executed.status_code == 201, executed.text
    body = executed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["execution_limit"] == 1
    assert body["health_result_status"] == "resolvable"
    assert body["activation_authorization_consumed"] is True
    assert body["provider_client_activation_authorized"] is False
    assert body["credential_reference_stored"] is True
    assert len(body["authorization_terminal_hash"]) == 64
    assert len(body["completion_hash"]) == 64
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

    # H atomically terminalizes the consumed G authorization so it cannot remain
    # live until its original TTL.
    consumed_g = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}",
        headers=_headers(requester_id),
    )
    assert consumed_g.status_code == 200, consumed_g.text
    assert consumed_g.json()["status"] == "expired"
    assert consumed_g.json()["provider_client_activation_authorized"] is False
    assert execution_id in consumed_g.json()["terminal_reason"]
    assert consumed_g.json()["terminal_hash"] == body["authorization_terminal_hash"]

    replay = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="provider-client-activation-execution-001",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id

    changed_replay = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="provider-client-activation-execution-001",
        reason="Attempt to materially change an already consumed Phase H activation execution request.",
    )
    assert changed_replay.status_code == 409, changed_replay.text

    second_execution = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="provider-client-activation-execution-002",
    )
    assert second_execution.status_code == 409, second_execution.text

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["activation_authorization_consumed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    for row in rows:
        assert row["provider_client_activation_authorized"] is False
        assert row["oauth_token_exchanged"] is False
        assert row["provider_network_performed"] is False
        assert row["remote_read_performed"] is False
        assert row["evidence_admitted"] is False
        assert row["document_created"] is False
        assert row["claim_mutated"] is False

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceProviderClientActivationExecution).count() == 1
        assert db.query(ExternalDocumentSourceProviderClientActivationExecutionReceipt).count() == 2
        receipt = (
            db.query(ExternalDocumentSourceProviderClientActivationExecutionReceipt)
            .filter(
                ExternalDocumentSourceProviderClientActivationExecutionReceipt.execution_id == UUID(execution_id),
                ExternalDocumentSourceProviderClientActivationExecutionReceipt.sequence_number == 1,
            )
            .one()
        )
        receipt.reason = "Tampered Phase H request receipt reason."
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceProviderClientActivationExecutionReceipt)
            .filter(
                ExternalDocumentSourceProviderClientActivationExecutionReceipt.execution_id == UUID(execution_id),
                ExternalDocumentSourceProviderClientActivationExecutionReceipt.sequence_number == 1,
            )
            .one()
        )
        receipt.reason = _EXECUTION_REASON
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase H lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text

    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceProviderClientActivationExecution).count() == 1
        assert db.query(ExternalDocumentSourceProviderClientActivationExecutionReceipt).count() == 2
