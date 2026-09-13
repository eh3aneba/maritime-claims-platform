from datetime import timedelta
from uuid import UUID

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.connection_authorization_models import (
    ExternalDocumentSourceConnectionAuthorization,
)
from app.modules.external_document_sources.connection_authorization_service import (
    get_external_document_source_connection_authorization,
)
from app.modules.external_document_sources.connection_bootstrap_models import (
    ExternalDocumentSourceConnectionBootstrapExecution,
    ExternalDocumentSourceConnectionBootstrapExecutionReceipt,
)
from app.modules.external_document_sources.discovery_service import (
    clear_external_document_source_discovery_adapters,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_connection_authorization import (
    _approve_authorization,
    _profile_and_discovery,
    _request_authorization,
)
from tests.test_external_document_source_discovery import (
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()


def _authorized_chain(seed: str):
    org_id, requester_id, approver_id = _seed_tenant(seed)
    profile_id, run_id = _profile_and_discovery(requester_id, approver_id)
    requested = _request_authorization(profile_id, run_id, requester_id, key=f"{seed}-authorization")
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    approved = _approve_authorization(profile_id, authorization_id, approver_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "authorized"
    return org_id, requester_id, approver_id, profile_id, run_id, authorization_id


def _execute(profile_id: str, authorization_id: str, actor_id: UUID, *, key: str, reason: str | None = None):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/bootstrap-executions",
        headers=_headers(actor_id),
        json={
            "request_key": key,
            "reason": reason or "Consume this one-use authorization into an auditable bootstrap execution without provider traffic.",
        },
    )


def test_bootstrap_execution_consumes_authorization_exactly_once_without_provider_action() -> None:
    _, requester_id, _, profile_id, _, authorization_id = _authorized_chain("bootstrap-success")

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    response = _execute(profile_id, authorization_id, requester_id, key="bootstrap-success-exec")
    assert response.status_code == 201, response.text
    body = response.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["authorization_consumed"] is True
    assert len(body["scope_hash"]) == 64
    assert len(body["request_hash"]) == 64
    assert len(body["completion_hash"]) == 64
    assert len(body["authorization_terminal_hash"]) == 64
    for field in (
        "credential_stored",
        "credential_reference_stored",
        "oauth_token_exchanged",
        "provider_network_performed",
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

    replay = _execute(profile_id, authorization_id, requester_id, key="bootstrap-success-exec")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id

    conflict = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="bootstrap-success-exec",
        reason="Try to replay the already consumed authorization with materially changed execution facts.",
    )
    assert conflict.status_code == 409, conflict.text

    authorization = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}",
        headers=_headers(requester_id),
    )
    assert authorization.status_code == 200, authorization.text
    authorization_body = authorization.json()
    assert authorization_body["status"] == "expired"
    assert authorization_body["live_connection_authorized"] is False
    assert execution_id in authorization_body["terminal_reason"]

    authorization_receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/receipts",
        headers=_headers(requester_id),
    )
    assert authorization_receipts.status_code == 200, authorization_receipts.text
    assert [row["event_type"] for row in authorization_receipts.json()] == ["requested", "authorized", "expired"]

    execution_receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/bootstrap-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert execution_receipts.status_code == 200, execution_receipts.text
    rows = execution_receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["authorization_consumed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceConnectionBootstrapExecution).count() == 1
        assert db.query(ExternalDocumentSourceConnectionBootstrapExecutionReceipt).count() == 2


def test_expired_authorization_cannot_be_consumed() -> None:
    org_id, requester_id, _, profile_id, _, authorization_id = _authorized_chain("bootstrap-expired")

    with TestingSessionLocal() as db:
        authorization = db.get(ExternalDocumentSourceConnectionAuthorization, UUID(authorization_id))
        assert authorization is not None and authorization.authorization_expires_at is not None
        future = authorization.authorization_expires_at + timedelta(seconds=1)
        expired, outcome = get_external_document_source_connection_authorization(
            db,
            organization_id=org_id,
            profile_id=UUID(profile_id),
            authorization_id=UUID(authorization_id),
            now=future,
        )
        assert outcome == "expired"
        assert expired.status == "expired"
        db.commit()

    response = _execute(profile_id, authorization_id, requester_id, key="bootstrap-expired-exec")
    assert response.status_code == 409, response.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceConnectionBootstrapExecution).count() == 0


def test_source_disable_prevents_bootstrap_consumption_fail_closed() -> None:
    _, requester_id, _, profile_id, _, authorization_id = _authorized_chain("bootstrap-disabled")
    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the governed source before bootstrap authority may be consumed."},
    )
    assert disabled.status_code == 200, disabled.text

    response = _execute(profile_id, authorization_id, requester_id, key="bootstrap-disabled-exec")
    assert response.status_code == 409, response.text
    authorization = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}",
        headers=_headers(requester_id),
    )
    assert authorization.status_code == 200, authorization.text
    assert authorization.json()["status"] == "expired"
    assert authorization.json()["live_connection_authorized"] is False


def test_bootstrap_execution_is_tenant_isolated() -> None:
    _, requester_id, _, profile_id, _, authorization_id = _authorized_chain("bootstrap-tenant-a")
    _, other_requester, _, = _seed_tenant("bootstrap-tenant-b")

    response = _execute(profile_id, authorization_id, other_requester, key="bootstrap-wrong-tenant")
    assert response.status_code == 404, response.text

    valid = _execute(profile_id, authorization_id, requester_id, key="bootstrap-right-tenant")
    assert valid.status_code == 201, valid.text


def test_bootstrap_receipt_tamper_fails_closed() -> None:
    _, requester_id, _, profile_id, _, authorization_id = _authorized_chain("bootstrap-tamper")
    response = _execute(profile_id, authorization_id, requester_id, key="bootstrap-tamper-exec")
    assert response.status_code == 201, response.text
    execution_id = response.json()["id"]

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceConnectionBootstrapExecutionReceipt)
            .filter(ExternalDocumentSourceConnectionBootstrapExecutionReceipt.execution_id == UUID(execution_id))
            .order_by(ExternalDocumentSourceConnectionBootstrapExecutionReceipt.sequence_number.asc())
            .first()
        )
        assert receipt is not None
        receipt.reason = "Tampered receipt reason that must invalidate the execution lineage."
        db.commit()

    read = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/bootstrap-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert read.status_code == 409, read.text
