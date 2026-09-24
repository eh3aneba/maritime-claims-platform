from datetime import timedelta
from uuid import UUID

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_credential_health_service import (
    clear_external_document_source_sftp_credential_health_resolvers,
)
from app.modules.external_document_sources.sftp_handshake_authorization_models import (
    ExternalDocumentSourceSftpHandshakeAuthorization,
)
from app.modules.external_document_sources.sftp_handshake_authorization_service import (
    get_external_document_source_sftp_handshake_authorization,
    reject_external_document_source_sftp_handshake_authorization,
)
from app.modules.external_document_sources.sftp_handshake_execution_models import (
    ExternalDocumentSourceSftpHandshakeExecution,
    ExternalDocumentSourceSftpHandshakeExecutionReceipt,
)
from app.modules.external_document_sources.sftp_handshake_execution_service import (
    execute_external_document_source_sftp_handshake_authorization,
    get_external_document_source_sftp_handshake_execution,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_handshake_authorization import (
    _APPROVAL_REASON,
    _qualified_health,
    _request_authorization,
)


_EXECUTION_REASON = (
    "Consume one bounded SFTP handshake authorization locally without DNS, "
    "network, SSH/SFTP session or remote-file activity."
)
_REJECTION_REASON = (
    "Reject this SFTP handshake authorization before Phase 17.6-E local consumption."
)


def setup_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()


def _approve(profile_id: str, authorization_id: str, actor_id):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/approve"
        ),
        headers=_headers(actor_id),
        json={"reason": _APPROVAL_REASON},
    )


def _execute(
    profile_id: str,
    authorization_id: str,
    actor_id,
    *,
    key: str,
    reason: str = _EXECUTION_REASON,
):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/"
            "handshake-executions"
        ),
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_sftp_handshake_execution_consumes_one_authorization_without_network_authority() -> None:
    (
        requester_id,
        approver_id,
        profile_id,
        binding_id,
        qualification_id,
    ) = _qualified_health("sftp-handshake-execution")

    requested = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="sftp-handshake-execution-authorization",
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    assert requested.json()["status"] == "pending_second_approval"

    pending = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="sftp-handshake-execution-pending",
    )
    assert pending.status_code == 409, pending.text

    with TestingSessionLocal() as db:
        authorization = db.get(
            ExternalDocumentSourceSftpHandshakeAuthorization,
            UUID(authorization_id),
        )
        assert authorization is not None
        rejected, outcome = (
            reject_external_document_source_sftp_handshake_authorization(
                db,
                organization_id=authorization.organization_id,
                profile_id=authorization.profile_id,
                authorization_id=authorization.id,
                rejected_by_id=approver_id,
                decision_reason=_REJECTION_REASON,
            )
        )
        assert outcome == "rejected"
        assert rejected.status == "rejected"
        try:
            execute_external_document_source_sftp_handshake_authorization(
                db,
                organization_id=authorization.organization_id,
                profile_id=authorization.profile_id,
                authorization_id=authorization.id,
                requested_by_id=requester_id,
                request_key="sftp-handshake-execution-rejected",
                request_reason=_EXECUTION_REASON,
            )
        except ExternalDocumentSourceConflictError:
            pass
        else:
            raise AssertionError(
                "Rejected Phase 17.6-D authorization must not be consumable"
            )
        db.rollback()

    approved = _approve(
        profile_id,
        authorization_id,
        approver_id,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "authorized"
    assert approved.json()["sftp_handshake_authorized"] is True

    forbidden_secret_field = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/"
            "handshake-executions"
        ),
        headers=_headers(requester_id),
        json={
            "request_key": "sftp-handshake-execution-secret-field",
            "reason": _EXECUTION_REASON,
            "password": "not-accepted-by-phase-17-6-e",
        },
    )
    assert forbidden_secret_field.status_code == 422, forbidden_secret_field.text

    with TestingSessionLocal() as db:
        authorization = db.get(
            ExternalDocumentSourceSftpHandshakeAuthorization,
            UUID(authorization_id),
        )
        assert authorization is not None
        assert authorization.authorization_expires_at is not None
        future = authorization.authorization_expires_at + timedelta(seconds=1)
        expired, outcome = get_external_document_source_sftp_handshake_authorization(
            db,
            organization_id=authorization.organization_id,
            profile_id=authorization.profile_id,
            authorization_id=authorization.id,
            now=future,
        )
        assert outcome == "expired"
        assert expired.status == "expired"
        try:
            execute_external_document_source_sftp_handshake_authorization(
                db,
                organization_id=authorization.organization_id,
                profile_id=authorization.profile_id,
                authorization_id=authorization.id,
                requested_by_id=requester_id,
                request_key="sftp-handshake-execution-expired",
                request_reason=_EXECUTION_REASON,
                now=future,
            )
        except ExternalDocumentSourceConflictError:
            pass
        else:
            raise AssertionError(
                "Expired Phase 17.6-D authorization must not be consumable"
            )
        db.rollback()

    _, other_requester, _, _ = _seed_tenant(
        "sftp-handshake-execution-other-tenant"
    )
    wrong_tenant = _execute(
        profile_id,
        authorization_id,
        other_requester,
        key="sftp-handshake-execution-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    executed = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="sftp-handshake-execution-001",
    )
    assert executed.status_code == 201, executed.text
    body = executed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["execution_limit"] == 1
    assert body["health_result_status"] == "qualified"
    assert body["handshake_authorization_consumed"] is True
    assert body["sftp_handshake_authorized"] is False
    assert body["credential_reference_stored"] is True
    assert len(body["authorization_terminal_hash"]) == 64
    assert len(body["completion_hash"]) == 64

    for field in (
        "secret_resolution_performed",
        "credential_stored",
        "provider_network_performed",
        "authentication_performed",
        "sftp_session_opened",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "evidence_admitted",
        "document_created",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
    ):
        assert body[field] is False

    consumed_d = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}"
        ),
        headers=_headers(requester_id),
    )
    assert consumed_d.status_code == 200, consumed_d.text
    assert consumed_d.json()["status"] == "expired"
    assert consumed_d.json()["sftp_handshake_authorized"] is False
    assert execution_id in consumed_d.json()["terminal_reason"]
    assert (
        consumed_d.json()["terminal_hash"]
        == body["authorization_terminal_hash"]
    )

    replay = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="sftp-handshake-execution-001",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id

    changed_replay = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="sftp-handshake-execution-001",
        reason=(
            "Attempt to materially change an already consumed Phase 17.6-E "
            "handshake execution request."
        ),
    )
    assert changed_replay.status_code == 409, changed_replay.text

    second_execution = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key="sftp-handshake-execution-002",
    )
    assert second_execution.status_code == 409, second_execution.text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-executions/{execution_id}/receipts"
        ),
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["handshake_authorization_consumed"] for row in rows] == [
        False,
        True,
    ]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    for row in rows:
        assert row["sftp_handshake_authorized"] is False
        assert row["secret_resolution_performed"] is False
        assert row["provider_network_performed"] is False
        assert row["sftp_session_opened"] is False
        assert row["remote_read_performed"] is False
        assert row["evidence_admitted"] is False
        assert row["document_created"] is False
        assert row["processing_enqueued"] is False
        assert row["ai_executed"] is False
        assert row["claim_mutated"] is False

    with TestingSessionLocal() as db:
        completed_receipt = (
            db.query(ExternalDocumentSourceSftpHandshakeExecutionReceipt)
            .filter(
                ExternalDocumentSourceSftpHandshakeExecutionReceipt.execution_id
                == UUID(execution_id),
                ExternalDocumentSourceSftpHandshakeExecutionReceipt.sequence_number
                == 2,
            )
            .one()
        )
        db.delete(completed_receipt)
        db.flush()
        execution = db.get(
            ExternalDocumentSourceSftpHandshakeExecution,
            UUID(execution_id),
        )
        assert execution is not None
        try:
            get_external_document_source_sftp_handshake_execution(
                db,
                organization_id=execution.organization_id,
                profile_id=execution.profile_id,
                execution_id=execution.id,
            )
        except ExternalDocumentSourceConflictError:
            pass
        else:
            raise AssertionError(
                "Truncated Phase 17.6-E receipt chain must fail closed"
            )
        db.rollback()

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpHandshakeExecution).count() == 1
        assert (
            db.query(ExternalDocumentSourceSftpHandshakeExecutionReceipt).count()
            == 2
        )
        receipt = (
            db.query(ExternalDocumentSourceSftpHandshakeExecutionReceipt)
            .filter(
                ExternalDocumentSourceSftpHandshakeExecutionReceipt.execution_id
                == UUID(execution_id),
                ExternalDocumentSourceSftpHandshakeExecutionReceipt.sequence_number
                == 1,
            )
            .one()
        )
        receipt.reason = "Tampered Phase 17.6-E request receipt reason."
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-executions/{execution_id}"
        ),
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceSftpHandshakeExecutionReceipt)
            .filter(
                ExternalDocumentSourceSftpHandshakeExecutionReceipt.execution_id
                == UUID(execution_id),
                ExternalDocumentSourceSftpHandshakeExecutionReceipt.sequence_number
                == 1,
            )
            .one()
        )
        receipt.reason = _EXECUTION_REASON
        db.commit()

    disabled = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-credential-reference-bindings/{binding_id}/disable"
        ),
        headers=_headers(requester_id),
        json={
            "reason": (
                "Disable the upstream SFTP credential reference so completed "
                "Phase 17.6-E lineage must fail closed."
            )
        },
    )
    assert disabled.status_code == 200, disabled.text

    fail_closed = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-executions/{execution_id}"
        ),
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpHandshakeExecution).count() == 1
        assert (
            db.query(ExternalDocumentSourceSftpHandshakeExecutionReceipt).count()
            == 2
        )
