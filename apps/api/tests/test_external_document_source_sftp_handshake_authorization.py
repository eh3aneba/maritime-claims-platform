from datetime import timedelta

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_credential_health_service import (
    clear_external_document_source_sftp_credential_health_resolvers,
    register_external_document_source_sftp_credential_health_resolver,
)
from app.modules.external_document_sources.sftp_handshake_authorization_models import (
    ExternalDocumentSourceSftpHandshakeAuthorization,
    ExternalDocumentSourceSftpHandshakeAuthorizationReceipt,
)
from app.modules.external_document_sources.sftp_handshake_authorization_service import (
    approve_external_document_source_sftp_handshake_authorization,
    get_external_document_source_sftp_handshake_authorization,
    request_external_document_source_sftp_handshake_authorization,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_credential_health import (
    _DeterministicResolver,
    _active_binding,
    _qualify,
)


_REQUEST_REASON = (
    "Authorize one future bounded SFTP handshake attempt without performing "
    "network or remote-file activity in this phase."
)
_APPROVAL_REASON = (
    "Independently approve exactly one short-lived future SFTP handshake attempt."
)


def setup_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()


def _qualified_health(seed: str):
    requester_id, approver_id, profile_id, binding_id = _active_binding(seed)
    resolver = _DeterministicResolver(
        resolved=True,
        material_kind="private_key",
    )
    register_external_document_source_sftp_credential_health_resolver(
        "hashicorp_vault",
        resolver,
    )
    response = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key=f"{seed}-health",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["result_status"] == "qualified"
    assert resolver.calls == 1
    return (
        requester_id,
        approver_id,
        profile_id,
        binding_id,
        body["id"],
    )


def _request_authorization(
    profile_id: str,
    qualification_id: str,
    actor_id,
    *,
    key: str,
    reason: str = _REQUEST_REASON,
):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-credential-health-qualifications/{qualification_id}/"
            "handshake-authorizations"
        ),
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_sftp_handshake_authorization_four_eyes_replay_and_zero_execution() -> None:
    (
        requester_id,
        approver_id,
        profile_id,
        _binding_id,
        qualification_id,
    ) = _qualified_health("sftp-handshake-auth-happy")
    _, other_requester_id, _, _ = _seed_tenant(
        "sftp-handshake-auth-other-tenant"
    )

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    wrong_tenant = _request_authorization(
        profile_id,
        qualification_id,
        other_requester_id,
        key="sftp-handshake-auth-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text

    requested = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="sftp-handshake-auth-happy",
    )
    assert requested.status_code == 201, requested.text
    body = requested.json()
    authorization_id = body["id"]
    assert body["status"] == "pending_second_approval"
    assert body["execution_limit"] == 1
    assert body["sftp_handshake_authorized"] is False

    replay = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="sftp-handshake-auth-happy",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == authorization_id

    changed_replay = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="sftp-handshake-auth-happy",
        reason=(
            "Attempt a changed replay that must conflict and create no new "
            "handshake authority."
        ),
    )
    assert changed_replay.status_code == 409, changed_replay.text

    self_approval = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/approve"
        ),
        headers=_headers(requester_id),
        json={"reason": _APPROVAL_REASON},
    )
    assert self_approval.status_code == 409, self_approval.text

    approved = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/approve"
        ),
        headers=_headers(approver_id),
        json={"reason": _APPROVAL_REASON},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "authorized"
    assert approved_body["sftp_handshake_authorized"] is True
    assert approved_body["execution_limit"] == 1

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
        assert approved_body[field] is False

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/receipts"
        ),
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == [
        "requested",
        "authorized",
    ]
    assert rows[0]["sftp_handshake_authorized"] is False
    assert rows[1]["sftp_handshake_authorized"] is True
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before


def test_sftp_handshake_authorization_expiry_rejection_and_tamper_fail_closed() -> None:
    (
        requester_id,
        approver_id,
        profile_id,
        _binding_id,
        qualification_id,
    ) = _qualified_health("sftp-handshake-auth-expiry")

    with TestingSessionLocal() as db:
        health = client.get(
            (
                f"/api/v1/external-document-sources/profiles/{profile_id}/"
                f"sftp-credential-health-qualifications/{qualification_id}"
            ),
            headers=_headers(requester_id),
        )
        assert health.status_code == 200, health.text

        from app.modules.external_document_sources.sftp_credential_health_models import (
            ExternalDocumentSourceSftpCredentialHealthQualification,
        )

        qualification = db.get(
            ExternalDocumentSourceSftpCredentialHealthQualification,
            qualification_id,
        )
        assert qualification is not None
        base_time = qualification.checked_at + timedelta(seconds=1)

        row, outcome = request_external_document_source_sftp_handshake_authorization(
            db,
            organization_id=qualification.organization_id,
            profile_id=qualification.profile_id,
            health_qualification_id=qualification.id,
            requested_by_id=requester_id,
            request_key="sftp-handshake-expiry-service",
            request_reason=_REQUEST_REASON,
            now=base_time,
        )
        assert outcome == "requested"
        db.commit()

        row, outcome = approve_external_document_source_sftp_handshake_authorization(
            db,
            organization_id=qualification.organization_id,
            profile_id=qualification.profile_id,
            authorization_id=row.id,
            approved_by_id=approver_id,
            decision_reason=_APPROVAL_REASON,
            now=base_time + timedelta(minutes=1),
        )
        assert outcome == "authorized"
        assert row.sftp_handshake_authorized is True
        db.commit()

        row, outcome = get_external_document_source_sftp_handshake_authorization(
            db,
            organization_id=qualification.organization_id,
            profile_id=qualification.profile_id,
            authorization_id=row.id,
            now=base_time + timedelta(minutes=12),
        )
        assert outcome == "expired"
        assert row.status == "expired"
        assert row.sftp_handshake_authorized is False
        db.commit()

    # Separate lifecycle for explicit rejection and receipt tamper.
    reset_database()
    clear_external_document_source_sftp_credential_health_resolvers()
    (
        requester_id,
        approver_id,
        profile_id,
        _binding_id,
        qualification_id,
    ) = _qualified_health("sftp-handshake-auth-reject")

    requested = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="sftp-handshake-reject",
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]

    rejected = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/reject"
        ),
        headers=_headers(approver_id),
        json={
            "reason": (
                "Reject this handshake authorization before any network activity."
            )
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["sftp_handshake_authorized"] is False

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceSftpHandshakeAuthorizationReceipt)
            .filter(
                ExternalDocumentSourceSftpHandshakeAuthorizationReceipt.authorization_id
                == authorization_id
            )
            .order_by(
                ExternalDocumentSourceSftpHandshakeAuthorizationReceipt.sequence_number
            )
            .first()
        )
        assert receipt is not None
        receipt.reason = "tampered authorization receipt"
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}"
        ),
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text


def test_sftp_handshake_authorization_rejects_unqualified_and_upstream_disable() -> None:
    (
        requester_id,
        _approver_id,
        profile_id,
        binding_id,
    ) = _active_binding(
        "sftp-handshake-auth-unqualified",
        authentication_kind="password",
    )
    resolver = _DeterministicResolver(
        resolved=True,
        material_kind="private_key",
    )
    register_external_document_source_sftp_credential_health_resolver(
        "hashicorp_vault",
        resolver,
    )
    health = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="sftp-handshake-auth-unqualified-health",
    )
    assert health.status_code == 201, health.text
    assert health.json()["result_status"] == "unqualified"

    denied = _request_authorization(
        profile_id,
        health.json()["id"],
        requester_id,
        key="sftp-handshake-auth-unqualified-request",
    )
    assert denied.status_code == 409, denied.text

    # Fresh qualified chain, then invalidate upstream B custody.
    reset_database()
    clear_external_document_source_sftp_credential_health_resolvers()
    (
        requester_id,
        _approver_id,
        profile_id,
        binding_id,
        qualification_id,
    ) = _qualified_health("sftp-handshake-auth-upstream-disable")

    requested = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="sftp-handshake-auth-upstream-disable",
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]

    disabled = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-credential-reference-bindings/{binding_id}/disable"
        ),
        headers=_headers(requester_id),
        json={
            "reason": (
                "Disable upstream SFTP credential custody so handshake "
                "authorization must fail closed."
            )
        },
    )
    assert disabled.status_code == 200, disabled.text

    read = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}"
        ),
        headers=_headers(requester_id),
    )
    assert read.status_code == 409, read.text
