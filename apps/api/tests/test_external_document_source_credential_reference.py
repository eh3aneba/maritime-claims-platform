from uuid import UUID

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.credential_reference_models import (
    ExternalDocumentSourceCredentialReferenceBinding,
    ExternalDocumentSourceCredentialReferenceReceipt,
)
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_connection_authorization import _disable_profile
from tests.test_external_document_source_connection_bootstrap import _authorized_chain, _execute
from tests.test_external_document_source_discovery import _headers, _seed_tenant


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()


def _completed_bootstrap(seed: str):
    org_id, requester_id, approver_id, profile_id, run_id, authorization_id = _authorized_chain(seed)
    executed = _execute(profile_id, authorization_id, requester_id, key=f"{seed}-bootstrap")
    assert executed.status_code == 201, executed.text
    body = executed.json()
    assert body["status"] == "completed"
    return org_id, requester_id, approver_id, profile_id, run_id, authorization_id, body["id"]


def _request_binding(
    profile_id: str,
    execution_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = "Register only a governed non-secret locator for the future provider credential resolver.",
    backend: str = "azure_key_vault",
    namespace: str = "mcri-prod",
    name: str = "sharepoint-provider-credential",
    version: str | None = "v1",
    extra: dict | None = None,
):
    payload = {
        "request_key": key,
        "reason": reason,
        "reference_backend": backend,
        "reference_namespace": namespace,
        "reference_name": name,
        "reference_version": version,
    }
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/bootstrap-executions/{execution_id}/credential-reference-bindings",
        headers=_headers(actor_id),
        json=payload,
    )


def _approve_binding(profile_id: str, binding_id: str, actor_id: UUID):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/approve",
        headers=_headers(actor_id),
        json={"reason": "Independently approve the non-secret credential-reference metadata only."},
    )


def test_credential_reference_requires_real_bootstrap_and_four_eyes_without_secret_execution() -> None:
    _, requester_id, approver_id, profile_id, _, _, execution_id = _completed_bootstrap("cred-ref-success")

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    requested = _request_binding(profile_id, execution_id, requester_id, key="cred-ref-success-binding")
    assert requested.status_code == 201, requested.text
    body = requested.json()
    binding_id = body["id"]
    assert body["status"] == "pending_second_approval"
    assert body["credential_reference_stored"] is True
    assert body["reference_backend"] == "azure_key_vault"
    assert body["reference_namespace"] == "mcri-prod"
    assert body["reference_name"] == "sharepoint-provider-credential"
    assert body["reference_version"] == "v1"
    assert len(body["locator_hash"]) == 64
    assert len(body["scope_hash"]) == 64
    assert len(body["request_hash"]) == 64
    for field in (
        "credential_stored",
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

    replay = _request_binding(profile_id, execution_id, requester_id, key="cred-ref-success-binding")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == binding_id

    conflict = _request_binding(
        profile_id,
        execution_id,
        requester_id,
        key="cred-ref-success-binding",
        reason="Attempt to replay the same bootstrap execution with materially changed reference custody facts.",
    )
    assert conflict.status_code == 409, conflict.text

    self_approval = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/approve",
        headers=_headers(requester_id),
        json={"reason": "Attempt same-actor approval that must violate the four-eyes boundary."},
    )
    assert self_approval.status_code == 409, self_approval.text

    approved = _approve_binding(profile_id, binding_id, approver_id)
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "active"
    assert approved_body["approved_by_id"] == str(approver_id)
    assert len(approved_body["approval_hash"]) == 64
    assert approved_body["credential_reference_stored"] is True
    assert approved_body["credential_stored"] is False
    assert approved_body["oauth_token_exchanged"] is False
    assert approved_body["provider_network_performed"] is False

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "approved"]
    assert [row["sequence_number"] for row in rows] == [1, 2]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert all(row["credential_reference_stored"] is True for row in rows)

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceCredentialReferenceBinding).count() == 1
        assert db.query(ExternalDocumentSourceCredentialReferenceReceipt).count() == 2


def test_credential_reference_rejects_extra_secret_fields_and_secret_like_or_url_locators() -> None:
    _, requester_id, _, profile_id, _, _, execution_id = _completed_bootstrap("cred-ref-input-safety")

    extra_secret = _request_binding(
        profile_id,
        execution_id,
        requester_id,
        key="cred-ref-extra-secret",
        extra={"client_secret": "must-not-be-accepted"},
    )
    assert extra_secret.status_code == 422, extra_secret.text

    secret_like = _request_binding(
        profile_id,
        execution_id,
        requester_id,
        key="cred-ref-secret-like",
        name="AK" + "IA1234567890123456",
    )
    assert secret_like.status_code == 422, secret_like.text

    url_like = _request_binding(
        profile_id,
        execution_id,
        requester_id,
        key="cred-ref-url-like",
        name="https://vault.example/secret?token=value",
    )
    assert url_like.status_code == 422, url_like.text

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceCredentialReferenceBinding).count() == 0


def test_active_credential_reference_fails_closed_when_source_profile_is_disabled_then_can_be_disabled_for_history() -> None:
    _, requester_id, approver_id, profile_id, _, _, execution_id = _completed_bootstrap("cred-ref-profile-disable")
    requested = _request_binding(profile_id, execution_id, requester_id, key="cred-ref-profile-disable-binding")
    assert requested.status_code == 201, requested.text
    binding_id = requested.json()["id"]
    approved = _approve_binding(profile_id, binding_id, approver_id)
    assert approved.status_code == 200, approved.text

    disabled_profile = _disable_profile(profile_id, requester_id)
    assert disabled_profile.status_code == 200, disabled_profile.text

    read = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}",
        headers=_headers(requester_id),
    )
    assert read.status_code == 409, read.text

    disabled_binding = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable this historical credential-reference binding after the governed source was disabled."},
    )
    assert disabled_binding.status_code == 200, disabled_binding.text
    assert disabled_binding.json()["status"] == "disabled"
    assert disabled_binding.json()["credential_reference_stored"] is True
    assert disabled_binding.json()["credential_stored"] is False

    historical = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}",
        headers=_headers(requester_id),
    )
    assert historical.status_code == 200, historical.text
    assert historical.json()["status"] == "disabled"


def test_credential_reference_rejection_is_terminal_and_auditable() -> None:
    _, requester_id, approver_id, profile_id, _, _, execution_id = _completed_bootstrap("cred-ref-reject")
    requested = _request_binding(profile_id, execution_id, requester_id, key="cred-ref-reject-binding")
    assert requested.status_code == 201, requested.text
    binding_id = requested.json()["id"]

    rejected = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/reject",
        headers=_headers(approver_id),
        json={"reason": "Reject this locator because it is not approved for future provider resolution."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["approval_hash"] is None
    assert len(rejected.json()["terminal_hash"]) == 64

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    assert [row["event_type"] for row in receipts.json()] == ["requested", "rejected"]


def test_credential_reference_is_tenant_isolated() -> None:
    _, requester_id, _, profile_id, _, _, execution_id = _completed_bootstrap("cred-ref-tenant-a")
    _, other_requester, _ = _seed_tenant("cred-ref-tenant-b")

    wrong_tenant = _request_binding(
        profile_id,
        execution_id,
        other_requester,
        key="cred-ref-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text

    valid = _request_binding(profile_id, execution_id, requester_id, key="cred-ref-right-tenant")
    assert valid.status_code == 201, valid.text


def test_credential_reference_receipt_tamper_fails_closed() -> None:
    _, requester_id, approver_id, profile_id, _, _, execution_id = _completed_bootstrap("cred-ref-tamper")
    requested = _request_binding(profile_id, execution_id, requester_id, key="cred-ref-tamper-binding")
    assert requested.status_code == 201, requested.text
    binding_id = requested.json()["id"]
    approved = _approve_binding(profile_id, binding_id, approver_id)
    assert approved.status_code == 200, approved.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceCredentialReferenceReceipt)
            .filter(ExternalDocumentSourceCredentialReferenceReceipt.binding_id == UUID(binding_id))
            .order_by(ExternalDocumentSourceCredentialReferenceReceipt.sequence_number.asc())
            .first()
        )
        assert receipt is not None
        receipt.reason = "Tampered credential-reference receipt reason that must invalidate the chain."
        db.commit()

    read = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}",
        headers=_headers(requester_id),
    )
    assert read.status_code == 409, read.text
