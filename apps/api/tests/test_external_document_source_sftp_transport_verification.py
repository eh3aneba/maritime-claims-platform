import json
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from app.modules.external_document_sources.sftp_credential_health_service import (
    SftpCredentialHealthProbeResult,
    clear_external_document_source_sftp_credential_health_resolvers,
    register_external_document_source_sftp_credential_health_resolver,
)
from app.modules.external_document_sources.sftp_handshake_execution_models import (
    ExternalDocumentSourceSftpHandshakeExecution,
)
from app.modules.external_document_sources.sftp_transport_verification_models import (
    ExternalDocumentSourceSftpTransportVerification,
    ExternalDocumentSourceSftpTransportVerificationReceipt,
)
from app.modules.external_document_sources.sftp_transport_verification_service import (
    SftpTransportHostKeyProbeResult,
    _literal_destination_denied,
    _validated_probe_outcome,
    clear_external_document_source_sftp_transport_adapter,
    register_external_document_source_sftp_transport_adapter,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_credential_health import (
    _DeterministicResolver,
    _qualify,
)
from tests.test_external_document_source_sftp_credential_reference import (
    _request_binding,
)
from tests.test_external_document_source_sftp_handshake_authorization import (
    _APPROVAL_REASON,
    _request_authorization,
)
from tests.test_external_document_source_sftp_handshake_execution import (
    _execute,
)
from tests.test_external_document_source_sftp_profiles import (
    _FINGERPRINT,
    _request_sftp,
)


_REASON = (
    "Verify exactly one bounded SSH transport and pinned host key without "
    "credential resolution, user authentication or SFTP file access."
)
_SECRET_MARKER = "provider-secret-exception-text-must-never-persist"


class _DeterministicTransportAdapter:
    adapter_kind = "deterministic_sftp_transport_adapter"

    def __init__(
        self,
        result: SftpTransportHostKeyProbeResult,
        *,
        raise_error: bool = False,
    ):
        self.result = result
        self.raise_error = raise_error
        self.calls = []

    def probe(self, request):
        self.calls.append(request)
        assert request.connect_timeout_seconds == 5
        assert request.handshake_timeout_seconds == 5
        assert request.max_connection_attempts == 1
        assert request.allow_private_destinations is False
        assert request.allow_redirects is False
        assert request.allow_proxy_retargeting is False
        assert request.pin_policy_checked_address is True
        if self.raise_error:
            raise RuntimeError(_SECRET_MARKER)
        return self.result


def setup_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()
    clear_external_document_source_sftp_transport_adapter()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()
    clear_external_document_source_sftp_transport_adapter()


def _completed_execution(seed: str, *, hostname: str = "sftp.claims.example.com"):
    org_id, requester_id, approver_id, _manager_id = _seed_tenant(seed)
    requested_profile = _request_sftp(
        _headers(requester_id),
        config={"hostname": hostname},
    )
    assert requested_profile.status_code == 201, requested_profile.text
    profile_body = requested_profile.json()
    profile_id = profile_body["id"]

    approved_profile = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve only the pinned read-only SFTP source "
                "before bounded transport verification."
            )
        },
    )
    assert approved_profile.status_code == 200, approved_profile.text

    requested_binding = _request_binding(
        profile_id,
        requester_id,
        key=f"{seed}-binding",
    )
    assert requested_binding.status_code == 201, requested_binding.text
    binding_id = requested_binding.json()["id"]
    approved_binding = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-credential-reference-bindings/{binding_id}/approve"
        ),
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve the non-secret SFTP credential reference "
                "before the bounded health qualification."
            )
        },
    )
    assert approved_binding.status_code == 200, approved_binding.text

    resolver = _DeterministicResolver(
        resolved=True,
        material_kind="private_key",
    )
    register_external_document_source_sftp_credential_health_resolver(
        "hashicorp_vault",
        resolver,
    )
    qualified = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key=f"{seed}-health",
    )
    assert qualified.status_code == 201, qualified.text
    qualification_id = qualified.json()["id"]
    assert qualified.json()["result_status"] == "qualified"
    assert resolver.calls == 1

    authorization = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key=f"{seed}-authorization",
    )
    assert authorization.status_code == 201, authorization.text
    authorization_id = authorization.json()["id"]
    approved_authorization = client.post(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}/"
            f"sftp-handshake-authorizations/{authorization_id}/approve"
        ),
        headers=_headers(approver_id),
        json={"reason": _APPROVAL_REASON},
    )
    assert approved_authorization.status_code == 200, approved_authorization.text

    execution = _execute(
        profile_id,
        authorization_id,
        requester_id,
        key=f"{seed}-execution",
    )
    assert execution.status_code == 201, execution.text
    execution_id = execution.json()["id"]
    assert execution.json()["status"] == "completed"
    assert execution.json()["provider_network_performed"] is False

    return {
        "org_id": org_id,
        "requester_id": requester_id,
        "approver_id": approver_id,
        "profile_id": profile_id,
        "execution_id": execution_id,
        "hostname": profile_body["normalized_config"]["hostname"],
        "port": profile_body["normalized_config"]["port"],
        "fingerprint": profile_body["normalized_config"][
            "host_key_fingerprint"
        ],
        "resolver": resolver,
    }


def _verify(
    chain: dict,
    *,
    key: str,
    reason: str = _REASON,
    actor_id=None,
):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-handshake-executions/{chain['execution_id']}/"
            "transport-verifications"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json={"request_key": key, "reason": reason},
    )


def _success_result(fingerprint: str) -> SftpTransportHostKeyProbeResult:
    return SftpTransportHostKeyProbeResult(
        observed_host_key_fingerprint=fingerprint,
        host_key_algorithm="ssh-ed25519",
        latency_class="fast",
        destination_policy_enforced=True,
        dns_resolution_performed=True,
        provider_network_performed=True,
        ssh_transport_performed=True,
    )


def test_sftp_transport_verification_matches_pin_once_without_auth_or_sftp() -> None:
    chain = _completed_execution("sftp-transport-verified")
    adapter = _DeterministicTransportAdapter(
        _success_result(chain["fingerprint"])
    )
    register_external_document_source_sftp_transport_adapter(adapter)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    response = _verify(
        chain,
        key="sftp-transport-verified-001",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    verification_id = body["id"]

    assert body["result_status"] == "verified"
    assert body["failure_code"] is None
    assert body["destination_hostname"] == chain["hostname"]
    assert body["destination_port"] == chain["port"]
    assert body["host_key_algorithm"] == "ssh-ed25519"
    assert body["latency_class"] == "fast"
    assert body["provider_network_performed"] is True
    assert body["ssh_transport_performed"] is True
    assert body["host_key_verification_performed"] is True
    assert body["host_key_verified"] is True
    assert body["verification_limit"] == 1
    assert chain["fingerprint"] not in response.text

    for field in (
        "secret_resolution_performed",
        "credential_stored",
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

    assert chain["resolver"].calls == 1
    assert len(adapter.calls) == 1
    probe_request = adapter.calls[0]
    assert probe_request.hostname == chain["hostname"]
    assert probe_request.port == chain["port"]
    assert not hasattr(probe_request, "username")
    assert not hasattr(probe_request, "password")
    assert not hasattr(probe_request, "private_key")

    replay = _verify(
        chain,
        key="sftp-transport-verified-001",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == verification_id
    assert len(adapter.calls) == 1

    changed = _verify(
        chain,
        key="sftp-transport-verified-001",
        reason=(
            "Attempt a materially changed replay after the exact Phase 17.6-F "
            "network verification already completed."
        ),
    )
    assert changed.status_code == 409, changed.text
    assert len(adapter.calls) == 1

    second = _verify(
        chain,
        key="sftp-transport-verified-002",
    )
    assert second.status_code == 409, second.text
    assert len(adapter.calls) == 1

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-transport-verifications/{verification_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert rows[0]["provider_network_performed"] is False
    assert rows[0]["ssh_transport_performed"] is False
    assert rows[0]["host_key_verification_performed"] is False
    assert rows[1]["provider_network_performed"] is True
    assert rows[1]["ssh_transport_performed"] is True
    assert rows[1]["host_key_verification_performed"] is True
    assert rows[1]["host_key_verified"] is True

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert (
            db.query(ExternalDocumentSourceSftpTransportVerification).count()
            == 1
        )
        verification = db.get(
            ExternalDocumentSourceSftpTransportVerification,
            UUID(verification_id),
        )
        assert verification is not None
        assert not hasattr(verification, "observed_host_key_fingerprint")
        assert (
            db.query(
                ExternalDocumentSourceSftpTransportVerificationReceipt
            ).count()
            == 2
        )
        execution = db.get(
            ExternalDocumentSourceSftpHandshakeExecution,
            UUID(chain["execution_id"]),
        )
        assert execution is not None
        assert execution.status == "completed"
        assert execution.provider_network_performed is False


def test_sftp_transport_verification_fails_closed_on_missing_adapter_mismatch_and_exception() -> None:
    missing = _completed_execution("sftp-transport-missing-adapter")
    unavailable = _verify(
        missing,
        key="sftp-transport-missing-adapter",
    )
    assert unavailable.status_code == 409, unavailable.text
    with TestingSessionLocal() as db:
        assert (
            db.query(ExternalDocumentSourceSftpTransportVerification).count()
            == 0
        )

    mismatch = _completed_execution("sftp-transport-mismatch")
    mismatch_adapter = _DeterministicTransportAdapter(
        _success_result("SHA256:" + ("B" * 43))
    )
    register_external_document_source_sftp_transport_adapter(mismatch_adapter)
    mismatch_response = _verify(
        mismatch,
        key="sftp-transport-mismatch",
    )
    assert mismatch_response.status_code == 201, mismatch_response.text
    mismatch_body = mismatch_response.json()
    assert mismatch_body["result_status"] == "failed"
    assert mismatch_body["failure_code"] == "host_key_mismatch"
    assert mismatch_body["host_key_verification_performed"] is True
    assert mismatch_body["host_key_verified"] is False
    assert mismatch_body["authentication_performed"] is False
    assert mismatch_body["sftp_session_opened"] is False

    clear_external_document_source_sftp_transport_adapter()
    failed = _completed_execution("sftp-transport-adapter-error")
    exception_adapter = _DeterministicTransportAdapter(
        _success_result(failed["fingerprint"]),
        raise_error=True,
    )
    register_external_document_source_sftp_transport_adapter(exception_adapter)
    failed_response = _verify(
        failed,
        key="sftp-transport-adapter-error",
    )
    assert failed_response.status_code == 201, failed_response.text
    failed_body = failed_response.json()
    assert failed_body["result_status"] == "failed"
    assert failed_body["failure_code"] == "adapter_error"
    assert failed_body["provider_network_performed"] is True
    assert failed_body["ssh_transport_performed"] is False
    assert _SECRET_MARKER not in failed_response.text

    with TestingSessionLocal() as db:
        audit_rows = db.query(AuditLog).all()
        serialized = json.dumps(
            [
                {
                    "new_values": row.new_values,
                    "details": row.details,
                }
                for row in audit_rows
            ],
            default=str,
        )
        assert _SECRET_MARKER not in serialized


def test_sftp_transport_verification_tenant_and_adapter_boundary_fail_closed() -> None:
    chain = _completed_execution("sftp-transport-boundaries")
    adapter = _DeterministicTransportAdapter(
        _success_result(chain["fingerprint"])
    )
    register_external_document_source_sftp_transport_adapter(adapter)

    _, other_requester_id, _, _ = _seed_tenant(
        "sftp-transport-other-tenant"
    )
    wrong_tenant = _verify(
        chain,
        key="sftp-transport-wrong-tenant",
        actor_id=other_requester_id,
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert adapter.calls == []

    violating_adapter = _DeterministicTransportAdapter(
        SftpTransportHostKeyProbeResult(
            observed_host_key_fingerprint=chain["fingerprint"],
            host_key_algorithm="ssh-ed25519",
            latency_class="fast",
            destination_policy_enforced=True,
            dns_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=True,
            authentication_performed=True,
        )
    )
    register_external_document_source_sftp_transport_adapter(
        violating_adapter
    )
    violated = _verify(
        chain,
        key="sftp-transport-auth-boundary",
    )
    assert violated.status_code == 409, violated.text
    with TestingSessionLocal() as db:
        assert (
            db.query(ExternalDocumentSourceSftpTransportVerification).count()
            == 0
        )


@pytest.mark.parametrize(
    "hostname",
    [
        "127.0.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "169.254.10.20",
        "10.20.30.40",
    ],
)
def test_sftp_transport_destination_policy_denies_unsafe_literal_addresses(
    hostname: str,
) -> None:
    assert _literal_destination_denied(hostname) is True


def test_sftp_transport_private_literal_fails_before_adapter_call() -> None:
    chain = _completed_execution(
        "sftp-transport-private",
        hostname="127.0.0.1",
    )
    adapter = _DeterministicTransportAdapter(
        _success_result(chain["fingerprint"])
    )
    register_external_document_source_sftp_transport_adapter(adapter)

    response = _verify(
        chain,
        key="sftp-transport-private",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["result_status"] == "failed"
    assert body["failure_code"] == "destination_policy_violation"
    assert body["provider_network_performed"] is False
    assert body["ssh_transport_performed"] is False
    assert body["host_key_verification_performed"] is False
    assert body["host_key_verified"] is False
    assert adapter.calls == []


def test_sftp_transport_verification_detects_upstream_execution_tamper() -> None:
    chain = _completed_execution("sftp-transport-tamper")
    adapter = _DeterministicTransportAdapter(
        _success_result(chain["fingerprint"])
    )
    register_external_document_source_sftp_transport_adapter(adapter)
    response = _verify(
        chain,
        key="sftp-transport-tamper",
    )
    assert response.status_code == 201, response.text
    verification_id = response.json()["id"]

    with TestingSessionLocal() as db:
        execution = db.get(
            ExternalDocumentSourceSftpHandshakeExecution,
            UUID(chain["execution_id"]),
        )
        assert execution is not None
        execution.completion_hash = "f" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-transport-verifications/{verification_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text


def test_sftp_transport_adapter_failure_result_is_bounded_and_sanitized() -> None:
    chain = _completed_execution("sftp-transport-policy-failure")
    adapter = _DeterministicTransportAdapter(
        SftpTransportHostKeyProbeResult(
            failure_code="dns_resolution_failed",
            destination_policy_enforced=True,
            dns_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=False,
            latency_class="slow",
        )
    )
    register_external_document_source_sftp_transport_adapter(adapter)

    response = _verify(
        chain,
        key="sftp-transport-dns-failure",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["result_status"] == "failed"
    assert body["failure_code"] == "dns_resolution_failed"
    assert body["latency_class"] == "slow"
    assert body["provider_network_performed"] is True
    assert body["authentication_performed"] is False
    assert body["sftp_session_opened"] is False
    assert body["remote_read_performed"] is False


def test_sftp_transport_rejects_legacy_host_key_algorithm() -> None:
    outcome = _validated_probe_outcome(
        SftpTransportHostKeyProbeResult(
            observed_host_key_fingerprint=_FINGERPRINT,
            host_key_algorithm="ssh-rsa",
            latency_class="fast",
            destination_policy_enforced=True,
            dns_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=True,
        ),
        pinned_host_key_fingerprint=_FINGERPRINT,
        destination_is_literal_ip=False,
    )
    assert outcome["result_status"] == "failed"
    assert outcome["failure_code"] == "unsupported_host_key_algorithm"
    assert outcome["host_key_verified"] is False
    assert outcome["host_key_verification_performed"] is False
