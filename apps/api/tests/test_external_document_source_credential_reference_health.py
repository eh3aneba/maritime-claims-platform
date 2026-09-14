import json
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.credential_reference_health_models import (
    ExternalDocumentSourceCredentialReferenceHealthQualification,
    ExternalDocumentSourceCredentialReferenceHealthReceipt,
)
from app.modules.external_document_sources.credential_reference_health_service import (
    CredentialReferenceHealthProbeResult,
    clear_external_document_source_credential_reference_health_resolvers,
    register_external_document_source_credential_reference_health_resolver,
)
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_connection_authorization import (
    _approve_authorization,
    _request_authorization,
)
from tests.test_external_document_source_connection_bootstrap import _execute
from tests.test_external_document_source_credential_reference import (
    _approve_binding,
    _completed_bootstrap,
    _request_binding,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant

_SECRET_MARKER = "phase-f-secret-value-must-never-persist"
_DEFAULT_REASON = "Qualify only whether the governed external credential reference is resolvable."


class _DeterministicResolver:
    resolver_kind = "deterministic_test_resolver"

    def __init__(self, *, resolvable: bool, failure_code: str | None = None):
        self.resolvable = resolvable
        self.failure_code = failure_code
        self.calls = 0
        self._secret_value = _SECRET_MARKER

    def check(self, locator):
        self.calls += 1
        assert locator.backend == "azure_key_vault"
        assert locator.namespace == "mcri-prod"
        assert locator.name == "sharepoint-provider-credential"
        assert locator.version == "v1"
        # Simulate a resolver possessing a value in memory. The service contract
        # receives only the bounded health result below, never this value.
        assert self._secret_value == _SECRET_MARKER
        return CredentialReferenceHealthProbeResult(
            resolvable=self.resolvable,
            failure_code=self.failure_code,
        )


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()


def _active_binding(seed: str):
    _, requester_id, approver_id, profile_id, run_id, _, execution_id = _completed_bootstrap(seed)
    requested = _request_binding(profile_id, execution_id, requester_id, key=f"{seed}-binding")
    assert requested.status_code == 201, requested.text
    binding_id = requested.json()["id"]
    approved = _approve_binding(profile_id, binding_id, approver_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    return requester_id, approver_id, profile_id, run_id, binding_id


def _additional_active_binding(
    profile_id: str,
    run_id: str,
    requester_id: UUID,
    approver_id: UUID,
    *,
    seed: str,
) -> str:
    authorization = _request_authorization(
        profile_id,
        run_id,
        requester_id,
        key=f"{seed}-authorization",
    )
    assert authorization.status_code == 201, authorization.text
    authorization_id = authorization.json()["id"]
    approved_authorization = _approve_authorization(profile_id, authorization_id, approver_id)
    assert approved_authorization.status_code == 200, approved_authorization.text
    assert approved_authorization.json()["status"] == "authorized"

    executed = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key=f"{seed}-bootstrap",
    )
    assert executed.status_code == 201, executed.text
    assert executed.json()["status"] == "completed"
    execution_id = executed.json()["id"]

    requested_binding = _request_binding(
        profile_id,
        execution_id,
        requester_id,
        key=f"{seed}-binding",
    )
    assert requested_binding.status_code == 201, requested_binding.text
    binding_id = requested_binding.json()["id"]
    approved_binding = _approve_binding(profile_id, binding_id, approver_id)
    assert approved_binding.status_code == 200, approved_binding.text
    assert approved_binding.json()["status"] == "active"
    return binding_id


def _qualify(
    profile_id: str,
    binding_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _DEFAULT_REASON,
):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/health-qualifications",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_credential_reference_health_full_governance_and_bounded_results_without_secret_persistence() -> None:
    requester_id, approver_id, profile_id, run_id, binding_id = _active_binding("cred-health-success")
    _, other_requester, _ = _seed_tenant("cred-health-other-tenant")
    resolver = _DeterministicResolver(resolvable=True)
    register_external_document_source_credential_reference_health_resolver("azure_key_vault", resolver)

    wrong_tenant = _qualify(profile_id, binding_id, other_requester, key="cred-health-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert resolver.calls == 0

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    qualified = _qualify(profile_id, binding_id, requester_id, key="cred-health-success-check")
    assert qualified.status_code == 201, qualified.text
    body = qualified.json()
    qualification_id = body["id"]
    assert body["result_status"] == "resolvable"
    assert body["failure_code"] is None
    assert body["credential_reference_stored"] is True
    assert body["credential_reference_resolution_performed"] is True
    assert body["reference_backend"] == "azure_key_vault"
    assert body["resolver_kind"] == "deterministic_test_resolver"
    assert len(body["scope_hash"]) == 64
    assert len(body["request_hash"]) == 64
    assert len(body["result_hash"]) == 64
    assert _SECRET_MARKER not in qualified.text
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
    assert resolver.calls == 1

    replay = _qualify(profile_id, binding_id, requester_id, key="cred-health-success-check")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == qualification_id
    assert resolver.calls == 1

    conflict = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="cred-health-success-check",
        reason="Attempt a changed replay that must not gain a second credential-resolution attempt.",
    )
    assert conflict.status_code == 409, conflict.text
    assert resolver.calls == 1

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == ["requested", "completed"]
    assert [row["status_after"] for row in receipt_rows] == ["requested", "resolvable"]
    assert receipt_rows[0]["credential_reference_resolution_performed"] is False
    assert receipt_rows[1]["credential_reference_resolution_performed"] is True
    assert receipt_rows[1]["prior_receipt_hash"] == receipt_rows[0]["receipt_hash"]
    assert _SECRET_MARKER not in receipts.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        row = db.query(ExternalDocumentSourceCredentialReferenceHealthQualification).one()
        stored_receipts = db.query(ExternalDocumentSourceCredentialReferenceHealthReceipt).all()
        audit_rows = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "external_document_source_credential_reference_health_qualification")
            .all()
        )
        persisted = json.dumps(
            {
                "qualification": {key: str(value) for key, value in row.__dict__.items() if not key.startswith("_")},
                "receipts": [
                    {key: str(value) for key, value in receipt.__dict__.items() if not key.startswith("_")}
                    for receipt in stored_receipts
                ],
                "audit": [
                    {
                        "new_values": audit.new_values,
                        "old_values": audit.old_values,
                        "details": audit.details,
                    }
                    for audit in audit_rows
                ],
            },
            sort_keys=True,
        )
        assert _SECRET_MARKER not in persisted
        assert len(stored_receipts) == 2
        assert len(audit_rows) == 1

        stored_receipts[0].reason = "Tampered Phase F receipt reason that must invalidate the qualification chain."
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceCredentialReferenceHealthReceipt)
            .filter(
                ExternalDocumentSourceCredentialReferenceHealthReceipt.qualification_id == UUID(qualification_id),
                ExternalDocumentSourceCredentialReferenceHealthReceipt.sequence_number == 1,
            )
            .one()
        )
        receipt.reason = _DEFAULT_REASON
        db.commit()

    restored = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}",
        headers=_headers(requester_id),
    )
    assert restored.status_code == 200, restored.text

    with TestingSessionLocal() as db:
        first_row = db.get(ExternalDocumentSourceCredentialReferenceHealthQualification, UUID(qualification_id))
        assert first_row is not None
        first_row.binding_approval_hash = "0" * 64
        db.commit()

    drifted = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}",
        headers=_headers(requester_id),
    )
    assert drifted.status_code == 409, drifted.text

    clear_external_document_source_credential_reference_health_resolvers()
    second_binding_id = _additional_active_binding(
        profile_id,
        run_id,
        requester_id,
        approver_id,
        seed="cred-health-unresolvable",
    )

    unavailable = _qualify(
        profile_id,
        second_binding_id,
        requester_id,
        key="cred-health-unavailable-check",
    )
    assert unavailable.status_code == 409, unavailable.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceCredentialReferenceHealthQualification).count() == 1

    unresolvable_resolver = _DeterministicResolver(resolvable=False, failure_code="reference_not_found")
    register_external_document_source_credential_reference_health_resolver(
        "azure_key_vault",
        unresolvable_resolver,
    )
    unresolvable = _qualify(
        profile_id,
        second_binding_id,
        requester_id,
        key="cred-health-unavailable-check",
    )
    assert unresolvable.status_code == 201, unresolvable.text
    unresolvable_body = unresolvable.json()
    second_qualification_id = unresolvable_body["id"]
    assert unresolvable_body["result_status"] == "unresolvable"
    assert unresolvable_body["failure_code"] == "reference_not_found"
    assert unresolvable_body["provider_network_performed"] is False
    assert unresolvable_body["oauth_token_exchanged"] is False
    assert unresolvable_resolver.calls == 1

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{second_binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so Phase F must immediately fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"

    read = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{second_qualification_id}",
        headers=_headers(requester_id),
    )
    assert read.status_code == 409, read.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceCredentialReferenceHealthQualification).count() == 2
