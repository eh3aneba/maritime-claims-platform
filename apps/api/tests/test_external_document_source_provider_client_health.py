import json
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.credential_reference_health_service import clear_external_document_source_credential_reference_health_resolvers
from app.modules.external_document_sources.credential_resolution_execution_service import clear_external_document_source_credential_resolution_resolvers
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_health_models import (
    ExternalDocumentSourceProviderClientHealthExecution,
    ExternalDocumentSourceProviderClientHealthReceipt,
)
from app.modules.external_document_sources.provider_client_health_service import (
    ProviderClientHealthResult,
    clear_external_document_source_provider_client_health_adapters,
    get_external_document_source_provider_client_health,
    register_external_document_source_provider_client_health_adapter,
)
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers, register_external_document_source_token_acquirer
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_token_acquisition_execution import (
    _TOKEN_REASON,
    _TokenAcquirer,
    _acquire,
    _completed_phase_i,
)

_HEALTH_REASON = "Construct one transient provider client and perform one bounded non-document authorization health qualification."
_CLIENT_SECRET = "phase-k-client-secret-marker"
_ACCESS_TOKEN = "phase-k-access-token-marker"
_CLIENT_OBJECT = "phase-k-provider-client-marker"
_RESPONSE_BODY = "phase-k-provider-response-marker"


class _HealthAdapter:
    adapter_kind = "deterministic_provider_health_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    health_operation_kind = "graph_organization_health"
    provider_origin = "https://graph.microsoft.com"

    def __init__(self, *, failure_code: str | None = None, raise_with_secrets: bool = False):
        self.failure_code = failure_code
        self.raise_with_secrets = raise_with_secrets
        self.calls = 0
        self.last_locator = None

    def qualify(self, locator, policy):
        self.calls += 1
        self.last_locator = locator
        client_secret = _CLIENT_SECRET
        access_token = _ACCESS_TOKEN
        transient_client = _CLIENT_OBJECT
        provider_response = _RESPONSE_BODY
        assert client_secret and access_token and transient_client and provider_response
        assert policy.provider_origin == "https://graph.microsoft.com"
        assert policy.health_endpoint_url == "https://graph.microsoft.com/v1.0/organization?$select=id"
        assert policy.health_operation_kind == "graph_organization_health"
        assert policy.client_kind == "microsoft_graph_transient_v1"
        assert policy.allow_redirects is False
        if self.raise_with_secrets:
            raise RuntimeError(f"provider health failed {client_secret} {access_token} {transient_client} {provider_response}")
        if self.failure_code is not None:
            return ProviderClientHealthResult(healthy=False, failure_code=self.failure_code)
        return ProviderClientHealthResult(healthy=True, latency_class="normal")


class _WrongOriginAdapter(_HealthAdapter):
    provider_origin = "https://evil.example.test"


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()


def _health(profile_id: str, token_execution_id: str, actor_id: UUID, *, key: str, reason: str = _HEALTH_REASON):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/token-acquisition-executions/{token_execution_id}/provider-client-health-executions",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def _completed_phase_j():
    requester_id, profile_id, binding_id, resolution_id = _completed_phase_i()
    register_external_document_source_token_acquirer("sharepoint", "client_credentials", _TokenAcquirer())
    acquired = _acquire(profile_id, resolution_id, requester_id, key="provider-client-health-phase-j", reason=_TOKEN_REASON)
    assert acquired.status_code == 201, acquired.text
    return requester_id, profile_id, binding_id, acquired.json()["id"]


def test_phase_k_transient_provider_client_health(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, token_execution_id = _completed_phase_j()
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    missing = _health(profile_id, token_execution_id, requester_id, key="provider-health-missing")
    assert missing.status_code == 409, missing.text
    assert "adapter is unavailable" in missing.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceProviderClientHealthExecution).count() == 0
        assert db.query(ExternalDocumentSourceProviderClientHealthReceipt).count() == 0

    wrong_origin = _WrongOriginAdapter()
    with pytest.raises(ValueError, match="origin"):
        register_external_document_source_provider_client_health_adapter("sharepoint", "graph_organization_health", wrong_origin)
    assert wrong_origin.calls == 0

    for failure_code in ("provider_rejected", "timeout", "malformed_response", "oversized_response"):
        negative = _HealthAdapter(failure_code=failure_code)
        register_external_document_source_provider_client_health_adapter("sharepoint", "graph_organization_health", negative)
        response = _health(profile_id, token_execution_id, requester_id, key=f"provider-health-{failure_code}")
        assert response.status_code == 409, response.text
        assert failure_code in response.text
        assert negative.calls == 1
        with TestingSessionLocal() as db:
            assert db.query(ExternalDocumentSourceProviderClientHealthExecution).count() == 0
            assert db.query(ExternalDocumentSourceProviderClientHealthReceipt).count() == 0

    raising = _HealthAdapter(raise_with_secrets=True)
    register_external_document_source_provider_client_health_adapter("sharepoint", "graph_organization_health", raising)
    caplog.clear()
    raised = _health(profile_id, token_execution_id, requester_id, key="provider-health-exception")
    assert raised.status_code == 409, raised.text
    assert raised.json()["detail"] == "Provider client health qualification failed"
    for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RESPONSE_BODY):
        assert marker not in raised.text
        assert marker not in caplog.text

    success = _HealthAdapter()
    register_external_document_source_provider_client_health_adapter("sharepoint", "graph_organization_health", success)
    forbidden = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/token-acquisition-executions/{token_execution_id}/provider-client-health-executions",
        headers=_headers(requester_id),
        json={"request_key": "provider-health-forbidden", "reason": _HEALTH_REASON, "access_token": "reject-me"},
    )
    assert forbidden.status_code == 422, forbidden.text

    _, other_requester, _ = _seed_tenant("provider-client-health-other-tenant")
    wrong_tenant = _health(profile_id, token_execution_id, other_requester, key="provider-health-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert success.calls == 0

    healthy = _health(profile_id, token_execution_id, requester_id, key="provider-health-001")
    assert healthy.status_code == 201, healthy.text
    body = healthy.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "healthy"
    assert body["latency_class"] == "normal"
    assert body["provider_client_constructed"] is True
    assert body["provider_network_health_performed"] is True
    assert body["provider_client_stored"] is False
    assert body["provider_response_body_stored"] is False
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["sync_executed"] is False
    assert body["evidence_admitted"] is False
    assert body["document_created"] is False
    assert body["claim_mutated"] is False
    assert success.calls == 1
    assert success.last_locator.backend == "azure_key_vault"
    for forbidden_field in ("health_endpoint_url", "provider_origin", "reference_namespace", "reference_name", "reference_version", "token_value", "client"):
        assert forbidden_field not in body
    for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RESPONSE_BODY):
        assert marker not in healthy.text

    replay = _health(profile_id, token_execution_id, requester_id, key="provider-health-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert success.calls == 1
    changed = _health(
        profile_id,
        token_execution_id,
        requester_id,
        key="provider-health-001",
        reason="Attempt to change a completed governed Phase K provider health request.",
    )
    assert changed.status_code == 409, changed.text
    second = _health(profile_id, token_execution_id, requester_id, key="provider-health-002")
    assert second.status_code == 409, second.text
    assert success.calls == 1

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-health-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["provider_client_constructed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceProviderClientHealthExecution, UUID(execution_id))
        assert execution is not None
        persisted = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        receipt_rows = db.query(ExternalDocumentSourceProviderClientHealthReceipt).filter(
            ExternalDocumentSourceProviderClientHealthReceipt.execution_id == UUID(execution_id)
        ).all()
        for receipt in receipt_rows:
            persisted.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_provider_client_health_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RESPONSE_BODY):
            assert marker not in payload
        assert "health_endpoint_url" not in payload
        assert "reference_namespace" not in payload

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceProviderClientHealthReceipt).filter(
            ExternalDocumentSourceProviderClientHealthReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceProviderClientHealthReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "Tampered Phase K receipt reason."
        db.commit()
    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-health-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceProviderClientHealthReceipt).filter(
            ExternalDocumentSourceProviderClientHealthReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceProviderClientHealthReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase K lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-health-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceProviderClientHealthExecution).count() == 1
        assert db.query(ExternalDocumentSourceProviderClientHealthReceipt).count() == 2
