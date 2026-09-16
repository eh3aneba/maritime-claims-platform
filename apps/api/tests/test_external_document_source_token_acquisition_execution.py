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
from app.modules.external_document_sources.credential_resolution_execution_service import (
    clear_external_document_source_credential_resolution_resolvers,
    register_external_document_source_credential_resolution_resolver,
)
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from app.modules.external_document_sources.token_acquisition_execution_models import (
    ExternalDocumentSourceTokenAcquisitionExecution,
    ExternalDocumentSourceTokenAcquisitionExecutionReceipt,
)
from app.modules.external_document_sources.token_acquisition_execution_service import (
    TokenAcquisitionResult,
    clear_external_document_source_token_acquirers,
    get_external_document_source_token_acquisition_execution,
    register_external_document_source_token_acquirer,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_credential_reference_health import (
    _DEFAULT_REASON as HEALTH_REASON,
    _DeterministicResolver,
    _active_binding,
    _qualify,
)
from tests.test_external_document_source_credential_resolution_execution import (
    _RESOLUTION_REASON,
    _ResolutionResolver,
    _resolve,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_provider_client_activation_authorization import (
    _approve as _approve_activation_authorization,
    _request as _request_activation_authorization,
)
from tests.test_external_document_source_provider_client_activation_execution import _execute as _execute_activation

_TOKEN_REASON = "Perform one bounded approved identity token exchange without retaining tokens or creating provider data authority."
_CREDENTIAL_SECRET = "phase-j-credential-secret-marker"
_ASSERTION_SECRET = "phase-j-assertion-secret-marker"
_ACCESS_TOKEN_SECRET = "phase-j-access-token-secret-marker"


class _TokenAcquirer:
    acquirer_kind = "deterministic_token_acquirer_v1"
    provider_kind = "sharepoint"
    token_flow_kind = "client_credentials"
    token_endpoint_origin = "https://login.microsoftonline.com"

    def __init__(self, *, failure_code: str | None = None, raise_with_secrets: bool = False):
        self.failure_code = failure_code
        self.raise_with_secrets = raise_with_secrets
        self.calls = 0
        self.last_locator = None

    def acquire(self, locator, policy):
        self.calls += 1
        self.last_locator = locator
        credential_material = _CREDENTIAL_SECRET
        signed_assertion = _ASSERTION_SECRET
        access_token = _ACCESS_TOKEN_SECRET
        assert credential_material and signed_assertion and access_token
        assert policy.token_endpoint_url == "https://login.microsoftonline.com/example.onmicrosoft.com/oauth2/v2.0/token"
        assert policy.audience_kind == "microsoft_graph_default"
        assert policy.allow_redirects is False
        assert policy.connect_timeout_seconds == 3.0
        assert policy.read_timeout_seconds == 5.0
        assert policy.total_timeout_seconds == 8.0
        assert policy.max_response_bytes == 65536
        if self.raise_with_secrets:
            raise RuntimeError(f"provider failure {credential_material} {signed_assertion} {access_token}")
        if self.failure_code is not None:
            return TokenAcquisitionResult(acquired=False, failure_code=self.failure_code)
        return TokenAcquisitionResult(acquired=True, expiry_class="standard")


class _WrongEndpointAcquirer(_TokenAcquirer):
    token_endpoint_origin = "https://evil.example.test"


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()


def _acquire(profile_id: str, resolution_id: str, actor_id: UUID, *, key: str, reason: str = _TOKEN_REASON):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{resolution_id}/token-acquisition-executions",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def _completed_phase_i():
    requester_id, approver_id, profile_id, _, binding_id = _active_binding("token-acquisition-execution")
    register_external_document_source_credential_reference_health_resolver("azure_key_vault", _DeterministicResolver(resolvable=True))
    qualified = _qualify(profile_id, binding_id, requester_id, key="token-acquisition-health", reason=HEALTH_REASON)
    assert qualified.status_code == 201, qualified.text
    authorization = _request_activation_authorization(
        profile_id,
        qualified.json()["id"],
        requester_id,
        key="token-acquisition-authorization",
    )
    assert authorization.status_code == 201, authorization.text
    authorization_id = authorization.json()["id"]
    approved = _approve_activation_authorization(profile_id, authorization_id, approver_id)
    assert approved.status_code == 200, approved.text
    activated = _execute_activation(profile_id, authorization_id, requester_id, key="token-acquisition-phase-h")
    assert activated.status_code == 201, activated.text
    register_external_document_source_credential_resolution_resolver("azure_key_vault", _ResolutionResolver())
    resolved = _resolve(
        profile_id,
        activated.json()["id"],
        requester_id,
        key="token-acquisition-phase-i",
        reason=_RESOLUTION_REASON,
    )
    assert resolved.status_code == 201, resolved.text
    return requester_id, profile_id, binding_id, resolved.json()["id"]


def test_phase_j_bounded_token_acquisition(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, resolution_id = _completed_phase_i()
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    missing = _acquire(profile_id, resolution_id, requester_id, key="token-acquisition-missing")
    assert missing.status_code == 409, missing.text
    assert "Token acquirer is unavailable" in missing.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceTokenAcquisitionExecution).count() == 0
        assert db.query(ExternalDocumentSourceTokenAcquisitionExecutionReceipt).count() == 0

    wrong_endpoint = _WrongEndpointAcquirer()
    with pytest.raises(ValueError, match="endpoint origin"):
        register_external_document_source_token_acquirer("sharepoint", "client_credentials", wrong_endpoint)
    assert wrong_endpoint.calls == 0

    for failure_code in ("provider_rejected", "timeout", "malformed_response", "oversized_response"):
        negative = _TokenAcquirer(failure_code=failure_code)
        register_external_document_source_token_acquirer("sharepoint", "client_credentials", negative)
        response = _acquire(profile_id, resolution_id, requester_id, key=f"token-acquisition-{failure_code}")
        assert response.status_code == 409, response.text
        assert failure_code in response.text
        assert negative.calls == 1
        with TestingSessionLocal() as db:
            assert db.query(ExternalDocumentSourceTokenAcquisitionExecution).count() == 0
            assert db.query(ExternalDocumentSourceTokenAcquisitionExecutionReceipt).count() == 0

    raising = _TokenAcquirer(raise_with_secrets=True)
    register_external_document_source_token_acquirer("sharepoint", "client_credentials", raising)
    caplog.clear()
    raised = _acquire(profile_id, resolution_id, requester_id, key="token-acquisition-exception")
    assert raised.status_code == 409, raised.text
    assert raised.json()["detail"] == "Token acquisition failed"
    for marker in (_CREDENTIAL_SECRET, _ASSERTION_SECRET, _ACCESS_TOKEN_SECRET):
        assert marker not in raised.text
        assert marker not in caplog.text

    success = _TokenAcquirer()
    register_external_document_source_token_acquirer("sharepoint", "client_credentials", success)
    forbidden = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{resolution_id}/token-acquisition-executions",
        headers=_headers(requester_id),
        json={"request_key": "token-acquisition-forbidden", "reason": _TOKEN_REASON, "client_secret": "reject-me"},
    )
    assert forbidden.status_code == 422, forbidden.text

    _, other_requester, _ = _seed_tenant("token-acquisition-other-tenant")
    wrong_tenant = _acquire(profile_id, resolution_id, other_requester, key="token-acquisition-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert success.calls == 0

    acquired = _acquire(profile_id, resolution_id, requester_id, key="token-acquisition-001")
    assert acquired.status_code == 201, acquired.text
    body = acquired.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "acquired"
    assert body["expiry_class"] == "standard"
    assert body["token_flow_kind"] == "client_credentials"
    assert body["token_acquisition_performed"] is True
    assert body["oauth_token_exchanged"] is True
    assert body["token_endpoint_network_performed"] is True
    assert body["provider_client_constructed"] is False
    assert body["provider_data_api_performed"] is False
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["sync_executed"] is False
    assert body["evidence_admitted"] is False
    assert body["document_created"] is False
    assert body["claim_mutated"] is False
    assert success.calls == 1
    assert success.last_locator.backend == "azure_key_vault"
    for forbidden_field in ("token_endpoint_url", "tenant_hint", "reference_namespace", "reference_name", "reference_version", "token_value", "assertion"):
        assert forbidden_field not in body
    for marker in (_CREDENTIAL_SECRET, _ASSERTION_SECRET, _ACCESS_TOKEN_SECRET):
        assert marker not in acquired.text

    replay = _acquire(profile_id, resolution_id, requester_id, key="token-acquisition-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert success.calls == 1
    changed = _acquire(
        profile_id,
        resolution_id,
        requester_id,
        key="token-acquisition-001",
        reason="Attempt to change the completed governed Phase J request after the exchange.",
    )
    assert changed.status_code == 409, changed.text
    second = _acquire(profile_id, resolution_id, requester_id, key="token-acquisition-002")
    assert second.status_code == 409, second.text
    assert success.calls == 1

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/token-acquisition-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["token_acquisition_performed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceTokenAcquisitionExecution, UUID(execution_id))
        assert execution is not None
        persisted = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        persisted_receipts = db.query(ExternalDocumentSourceTokenAcquisitionExecutionReceipt).filter(
            ExternalDocumentSourceTokenAcquisitionExecutionReceipt.execution_id == UUID(execution_id)
        ).all()
        for receipt in persisted_receipts:
            persisted.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_token_acquisition_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        for marker in (_CREDENTIAL_SECRET, _ASSERTION_SECRET, _ACCESS_TOKEN_SECRET):
            assert marker not in payload
        assert "token_endpoint_url" not in payload
        assert "reference_namespace" not in payload

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceTokenAcquisitionExecutionReceipt).filter(
            ExternalDocumentSourceTokenAcquisitionExecutionReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceTokenAcquisitionExecutionReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "Tampered Phase J receipt reason."
        db.commit()
    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/token-acquisition-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceTokenAcquisitionExecutionReceipt).filter(
            ExternalDocumentSourceTokenAcquisitionExecutionReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceTokenAcquisitionExecutionReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase J lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/token-acquisition-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceTokenAcquisitionExecution).count() == 1
        assert db.query(ExternalDocumentSourceTokenAcquisitionExecutionReceipt).count() == 2
