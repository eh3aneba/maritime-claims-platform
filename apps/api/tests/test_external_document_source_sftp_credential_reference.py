from uuid import UUID

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_credential_reference_models import (
    ExternalDocumentSourceSftpCredentialReferenceBinding,
    ExternalDocumentSourceSftpCredentialReferenceReceipt,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import _headers, _request_sharepoint, _seed_tenant
from tests.test_external_document_source_sftp_profiles import _request_sftp


def setup_function() -> None:
    reset_database()


def _active_sftp_profile(slug: str):
    org_id, requester_id, approver_id, manager_id = _seed_tenant(slug)
    requested = _request_sftp(_headers(requester_id))
    assert requested.status_code == 201, requested.text
    profile_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve only the pinned read-only SFTP source profile."
            )
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    return org_id, requester_id, approver_id, manager_id, profile_id


def _request_binding(
    profile_id: str,
    actor_id: UUID,
    *,
    key: str,
    authentication_kind: str = "private_key",
    backend: str = "hashicorp_vault",
    namespace: str = "mcri-prod",
    name: str = "sftp-claims-reader",
    version: str | None = "v1",
    extra: dict | None = None,
):
    payload = {
        "request_key": key,
        "reason": (
            "Govern only the non-secret locator for future SFTP authentication "
            "material without resolving it or opening a network session."
        ),
        "authentication_kind": authentication_kind,
        "reference_backend": backend,
        "reference_namespace": namespace,
        "reference_name": name,
        "reference_version": version,
    }
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings",
        headers=_headers(actor_id),
        json=payload,
    )


def test_sftp_credential_reference_four_eyes_replay_and_receipt_integrity() -> None:
    (
        org_id,
        requester_id,
        approver_id,
        _manager_id,
        profile_id,
    ) = _active_sftp_profile("sftp-cred-ref-governance")

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    requested = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-request-1",
    )
    assert requested.status_code == 201, requested.text
    body = requested.json()
    binding_id = body["id"]
    assert body["organization_id"] == str(org_id)
    assert body["provider_kind"] == "sftp"
    assert body["authentication_kind"] == "private_key"
    assert body["status"] == "pending_second_approval"
    assert body["reference_backend"] == "hashicorp_vault"
    assert body["reference_namespace"] == "mcri-prod"
    assert body["reference_name"] == "sftp-claims-reader"
    assert body["reference_version"] == "v1"
    assert len(body["locator_hash"]) == 64
    assert len(body["scope_hash"]) == 64
    assert len(body["request_hash"]) == 64
    assert body["credential_reference_stored"] is True
    for field in (
        "credential_stored",
        "secret_resolution_performed",
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

    replay = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-request-1",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == binding_id

    changed_replay = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-request-1",
        version="v2",
    )
    assert changed_replay.status_code == 409, changed_replay.text

    self_approval = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/approve",
        headers=_headers(requester_id),
        json={
            "reason": (
                "Attempt same-actor approval that must violate the four-eyes boundary."
            )
        },
    )
    assert self_approval.status_code == 409, self_approval.text

    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve only the non-secret SFTP credential locator."
            )
        },
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "active"
    assert approved_body["approved_by_id"] == str(approver_id)
    assert len(approved_body["approval_hash"]) == 64

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "approved"]
    assert [row["sequence_number"] for row in rows] == [1, 2]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpCredentialReferenceBinding).count() == 1
        assert db.query(ExternalDocumentSourceSftpCredentialReferenceReceipt).count() == 2
        receipt = (
            db.query(ExternalDocumentSourceSftpCredentialReferenceReceipt)
            .filter(
                ExternalDocumentSourceSftpCredentialReferenceReceipt.binding_id
                == UUID(binding_id)
            )
            .order_by(
                ExternalDocumentSourceSftpCredentialReferenceReceipt.sequence_number.asc()
            )
            .first()
        )
        assert receipt is not None
        receipt.reason = (
            "Tampered SFTP credential-reference receipt reason that must invalidate "
            "the hash chain."
        )
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text


def test_sftp_credential_reference_rejects_secret_like_unknown_and_invalid_auth_inputs() -> None:
    _, requester_id, _, _, profile_id = _active_sftp_profile(
        "sftp-cred-ref-input-safety"
    )

    raw_password = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-raw-password",
        extra={"password": "must-never-be-stored"},
    )
    assert raw_password.status_code == 422, raw_password.text

    raw_private_key = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-raw-private-key",
        extra={"private_key": "-----BEGIN " + "PRIVATE KEY-----"},
    )
    assert raw_private_key.status_code == 422, raw_private_key.text

    secret_like = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-secret-like",
        name="AK" + "IA1234567890123456",
    )
    assert secret_like.status_code == 422, secret_like.text
    assert "secret material" in secret_like.text.lower()

    invalid_auth = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-invalid-auth",
        authentication_kind="keyboard_interactive",
    )
    assert invalid_auth.status_code == 422, invalid_auth.text
    assert "authentication kind" in invalid_auth.text.lower()

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpCredentialReferenceBinding).count() == 0



def test_sftp_credential_reference_requires_active_sftp_profile() -> None:
    _, requester_id, approver_id, _ = _seed_tenant("sftp-cred-ref-profile-boundary")
    pending = _request_sftp(_headers(requester_id))
    assert pending.status_code == 201, pending.text
    pending_profile_id = pending.json()["id"]

    pending_binding = _request_binding(
        pending_profile_id,
        requester_id,
        key="sftp-cred-ref-pending-profile",
    )
    assert pending_binding.status_code == 409, pending_binding.text
    assert "not active" in pending_binding.text.lower()

    sharepoint = _request_sharepoint(_headers(requester_id))
    assert sharepoint.status_code == 201, sharepoint.text
    sharepoint_profile_id = sharepoint.json()["id"]
    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{sharepoint_profile_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve this SharePoint profile only to prove SFTP "
                "credential custody rejects a non-SFTP provider."
            )
        },
    )
    assert approved.status_code == 200, approved.text

    wrong_provider = _request_binding(
        sharepoint_profile_id,
        requester_id,
        key="sftp-cred-ref-wrong-provider",
    )
    assert wrong_provider.status_code == 409, wrong_provider.text
    assert "sftp source profile" in wrong_provider.text.lower()


def test_sftp_credential_reference_tenant_isolation_and_rejection() -> None:
    _, requester_id, approver_id, _, profile_id = _active_sftp_profile(
        "sftp-cred-ref-tenant-a"
    )
    _, other_requester_id, _, _ = _seed_tenant("sftp-cred-ref-tenant-b")

    hidden = _request_binding(
        profile_id,
        other_requester_id,
        key="sftp-cred-ref-wrong-tenant",
    )
    assert hidden.status_code == 404, hidden.text

    requested = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-reject",
        authentication_kind="password",
        name="sftp-password-reference",
    )
    assert requested.status_code == 201, requested.text
    binding_id = requested.json()["id"]

    rejected = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/reject",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Reject this locator because it is not approved for future SFTP "
                "authentication resolution."
            )
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["approval_hash"] is None
    assert len(rejected.json()["terminal_hash"]) == 64

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    assert [row["event_type"] for row in receipts.json()] == [
        "requested",
        "rejected",
    ]


def test_active_sftp_credential_reference_fails_closed_after_profile_disable_then_remains_historical() -> None:
    _, requester_id, approver_id, _, profile_id = _active_sftp_profile(
        "sftp-cred-ref-disable"
    )
    requested = _request_binding(
        profile_id,
        requester_id,
        key="sftp-cred-ref-disable-binding",
    )
    assert requested.status_code == 201, requested.text
    binding_id = requested.json()["id"]

    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve this SFTP credential reference before "
                "testing source-profile disable behavior."
            )
        },
    )
    assert approved.status_code == 200, approved.text

    disabled_profile = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/disable",
        headers=_headers(requester_id),
        json={
            "reason": (
                "Disable the governed SFTP source so active downstream custody "
                "must fail closed."
            )
        },
    )
    assert disabled_profile.status_code == 200, disabled_profile.text

    active_read = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}",
        headers=_headers(requester_id),
    )
    assert active_read.status_code == 409, active_read.text

    disabled_binding = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={
            "reason": (
                "Disable the historical SFTP credential reference after its source "
                "profile was disabled."
            )
        },
    )
    assert disabled_binding.status_code == 200, disabled_binding.text
    assert disabled_binding.json()["status"] == "disabled"

    historical = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}",
        headers=_headers(requester_id),
    )
    assert historical.status_code == 200, historical.text
    assert historical.json()["status"] == "disabled"
