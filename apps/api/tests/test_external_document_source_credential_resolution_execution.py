import json
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.credential_reference_health_service import (
    clear_external_document_source_credential_reference_health_resolvers,
    register_external_document_source_credential_reference_health_resolver,
)
from app.modules.external_document_sources.credential_resolution_execution_models import (
    ExternalDocumentSourceCredentialResolutionExecution,
    ExternalDocumentSourceCredentialResolutionExecutionReceipt,
)
from app.modules.external_document_sources.credential_resolution_execution_service import (
    CredentialReferenceResolutionResult,
    clear_external_document_source_credential_resolution_resolvers,
    get_external_document_source_credential_resolution_execution,
    register_external_document_source_credential_resolution_resolver,
)
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
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
from tests.test_external_document_source_provider_client_activation_execution import _execute as _execute_activation

_RESOLUTION_REASON = "Resolve the exact governed credential reference in memory without OAuth, provider traffic or document authority."
_RESOLUTION_SENTINEL = "value-observed-only-inside-resolver"


class _ResolutionResolver:
    resolver_kind = "deterministic_resolution_v1"

    def __init__(self, *, failure_code: str | None = None, raise_with_secret: bool = False):
        self.failure_code = failure_code
        self.raise_with_secret = raise_with_secret
        self.calls = 0
        self.last_locator = None

    def resolve(self, locator):
        self.calls += 1
        self.last_locator = locator
        resolved_value = _RESOLUTION_SENTINEL
        assert resolved_value
        if self.raise_with_secret:
            raise RuntimeError(f"backend failure containing forbidden secret {resolved_value}")
        if self.failure_code is not None:
            return CredentialReferenceResolutionResult(resolved=False, failure_code=self.failure_code)
        return CredentialReferenceResolutionResult(resolved=True)


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()


def _resolve(profile_id: str, activation_execution_id: str, actor_id: UUID, *, key: str, reason: str = _RESOLUTION_REASON):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{activation_execution_id}/credential-resolution-executions",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_credential_resolution_execution_resolves_only_in_memory_without_downstream_authority(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, approver_id, profile_id, _, binding_id = _active_binding("credential-resolution-execution")
    register_external_document_source_credential_reference_health_resolver(
        "azure_key_vault", _DeterministicResolver(resolvable=True)
    )
    qualified = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="credential-resolution-execution-health",
        reason=HEALTH_REASON,
    )
    assert qualified.status_code == 201, qualified.text
    qualification_id = qualified.json()["id"]
    assert qualified.json()["result_status"] == "resolvable"

    requested = _request_activation_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key="credential-resolution-execution-authorization",
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    approved = _approve_activation_authorization(profile_id, authorization_id, approver_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "authorized"

    activated = _execute_activation(
        profile_id,
        authorization_id,
        requester_id,
        key="credential-resolution-execution-phase-h",
    )
    assert activated.status_code == 201, activated.text
    activation_execution_id = activated.json()["id"]
    assert activated.json()["status"] == "completed"
    assert activated.json()["activation_authorization_consumed"] is True

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        assert db.query(ExternalDocumentSourceCredentialResolutionExecution).count() == 0

    missing = _resolve(
        profile_id,
        activation_execution_id,
        requester_id,
        key="credential-resolution-missing-resolver",
    )
    assert missing.status_code == 409, missing.text
    assert "resolver is unavailable" in missing.text
    assert _RESOLUTION_SENTINEL not in missing.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceCredentialResolutionExecution).count() == 0
        assert db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt).count() == 0

    negative_resolver = _ResolutionResolver(failure_code="reference_not_found")
    register_external_document_source_credential_resolution_resolver("azure_key_vault", negative_resolver)
    negative = _resolve(
        profile_id,
        activation_execution_id,
        requester_id,
        key="credential-resolution-not-found",
    )
    assert negative.status_code == 409, negative.text
    assert "reference_not_found" in negative.text
    assert _RESOLUTION_SENTINEL not in negative.text
    assert negative_resolver.calls == 1
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceCredentialResolutionExecution).count() == 0
        assert db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt).count() == 0

    raising_resolver = _ResolutionResolver(raise_with_secret=True)
    register_external_document_source_credential_resolution_resolver("azure_key_vault", raising_resolver)
    caplog.clear()
    raised = _resolve(
        profile_id,
        activation_execution_id,
        requester_id,
        key="credential-resolution-exception",
    )
    assert raised.status_code == 409, raised.text
    assert raised.json()["detail"] == "Credential reference resolution failed"
    assert _RESOLUTION_SENTINEL not in raised.text
    assert _RESOLUTION_SENTINEL not in caplog.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceCredentialResolutionExecution).count() == 0
        assert db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt).count() == 0

    success_resolver = _ResolutionResolver()
    register_external_document_source_credential_resolution_resolver("azure_key_vault", success_resolver)

    forbidden = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{activation_execution_id}/credential-resolution-executions",
        headers=_headers(requester_id),
        json={
            "request_key": "credential-resolution-forbidden-secret",
            "reason": _RESOLUTION_REASON,
            "client_secret": "caller-supplied-extra-field-is-not-accepted",
        },
    )
    assert forbidden.status_code == 422, forbidden.text

    _, other_requester, _ = _seed_tenant("credential-resolution-execution-other-tenant")
    wrong_tenant = _resolve(
        profile_id,
        activation_execution_id,
        other_requester,
        key="credential-resolution-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert success_resolver.calls == 0

    resolved = _resolve(
        profile_id,
        activation_execution_id,
        requester_id,
        key="credential-resolution-execution-001",
    )
    assert resolved.status_code == 201, resolved.text
    body = resolved.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["credential_reference_stored"] is True
    assert body["credential_reference_resolution_performed"] is True
    assert body["activation_authorization_consumed"] is True
    assert body["resolution_resolver_kind"] == "deterministic_resolution_v1"
    assert len(body["locator_hash"]) == 64
    assert len(body["completion_hash"]) == 64
    assert success_resolver.calls == 1
    assert success_resolver.last_locator.backend == "azure_key_vault"
    assert _RESOLUTION_SENTINEL not in resolved.text
    for forbidden_locator_field in ("namespace", "reference_namespace", "reference_name", "reference_version"):
        assert forbidden_locator_field not in body
    for field in (
        "credential_stored",
        "oauth_authorization_code_stored",
        "oauth_token_exchanged",
        "access_token_stored",
        "refresh_token_stored",
        "client_secret_stored",
        "private_key_stored",
        "provider_client_activation_authorized",
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

    replay = _resolve(
        profile_id,
        activation_execution_id,
        requester_id,
        key="credential-resolution-execution-001",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert success_resolver.calls == 1, "Exact replay must not resolve the credential again"

    changed_replay = _resolve(
        profile_id,
        activation_execution_id,
        requester_id,
        key="credential-resolution-execution-001",
        reason="Attempt to change a completed Phase I resolution request after its governed execution.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    assert success_resolver.calls == 1

    second_key = _resolve(
        profile_id,
        activation_execution_id,
        requester_id,
        key="credential-resolution-execution-002",
    )
    assert second_key.status_code == 409, second_key.text
    assert success_resolver.calls == 1

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["credential_reference_resolution_performed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert _RESOLUTION_SENTINEL not in receipts.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceCredentialResolutionExecution, UUID(execution_id))
        assert execution is not None
        persisted_values = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        persisted_receipts = (
            db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt)
            .filter(ExternalDocumentSourceCredentialResolutionExecutionReceipt.execution_id == UUID(execution_id))
            .all()
        )
        for receipt in persisted_receipts:
            persisted_values.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        assert _RESOLUTION_SENTINEL not in "\n".join(persisted_values)

        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "external_document_source_credential_resolution_execution",
                AuditLog.entity_id == UUID(execution_id),
            )
            .one()
        )
        audit_payload = json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert _RESOLUTION_SENTINEL not in audit_payload
        assert "reference_namespace" not in audit_payload
        assert "reference_name" not in audit_payload

    with TestingSessionLocal() as db:
        completed_receipt = (
            db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt)
            .filter(
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.execution_id == UUID(execution_id),
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.sequence_number == 2,
            )
            .one()
        )
        db.delete(completed_receipt)
        db.flush()
        execution = db.get(ExternalDocumentSourceCredentialResolutionExecution, UUID(execution_id))
        assert execution is not None
        with pytest.raises(ExternalDocumentSourceConflictError):
            get_external_document_source_credential_resolution_execution(
                db,
                organization_id=execution.organization_id,
                profile_id=execution.profile_id,
                execution_id=execution.id,
            )
        db.rollback()

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt)
            .filter(
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.execution_id == UUID(execution_id),
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.sequence_number == 1,
            )
            .one()
        )
        original_reason = receipt.reason
        receipt.reason = "Tampered Phase I receipt reason."
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt)
            .filter(
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.execution_id == UUID(execution_id),
                ExternalDocumentSourceCredentialResolutionExecutionReceipt.sequence_number == 1,
            )
            .one()
        )
        receipt.reason = original_reason
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase I lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text

    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceCredentialResolutionExecution).count() == 1
        assert db.query(ExternalDocumentSourceCredentialResolutionExecutionReceipt).count() == 2
