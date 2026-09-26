import json
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_credential_health_service import (
    clear_external_document_source_sftp_credential_health_resolvers,
)
from app.modules.external_document_sources.sftp_session_activation_models import (
    ExternalDocumentSourceSftpSessionActivation,
    ExternalDocumentSourceSftpSessionActivationReceipt,
)
from app.modules.external_document_sources.sftp_session_activation_service import (
    SftpSessionActivationResult,
    clear_external_document_source_sftp_session_activation_adapter,
    register_external_document_source_sftp_session_activation_adapter,
)
from app.modules.external_document_sources.sftp_transport_verification_service import (
    SftpTransportHostKeyProbeResult,
    clear_external_document_source_sftp_transport_adapter,
    register_external_document_source_sftp_transport_adapter,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_transport_verification import (
    _DeterministicTransportAdapter,
    _completed_execution,
    _success_result,
    _verify,
)


_REASON = (
    "Resolve exactly one approved SFTP credential transiently, authenticate the "
    "verified server identity and prove subsystem activation without remote file access."
)
_SECRET_MARKER = "raw-provider-secret-must-never-persist"


class _DeterministicSessionActivationAdapter:
    adapter_kind = "deterministic_sftp_session_activation"

    def __init__(self, result: SftpSessionActivationResult, *, raise_error: bool = False):
        self.result = result
        self.raise_error = raise_error
        self.calls = []

    def activate(self, request):
        self.calls.append(request)
        assert request.connect_timeout_seconds == 5
        assert request.authentication_timeout_seconds == 5
        assert request.subsystem_timeout_seconds == 5
        assert request.max_connection_attempts == 1
        assert request.max_authentication_attempts == 1
        assert request.allow_private_destinations is False
        assert request.allow_redirects is False
        assert request.allow_proxy_retargeting is False
        assert request.read_only_intent is True
        assert request.authentication_kind in {"password", "private_key"}
        if self.raise_error:
            raise RuntimeError(_SECRET_MARKER)
        return self.result


def setup_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()
    clear_external_document_source_sftp_transport_adapter()
    clear_external_document_source_sftp_session_activation_adapter()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()
    clear_external_document_source_sftp_transport_adapter()
    clear_external_document_source_sftp_session_activation_adapter()


def _verified_transport(seed: str):
    chain = _completed_execution(seed)
    transport = _DeterministicTransportAdapter(_success_result(chain["fingerprint"]))
    register_external_document_source_sftp_transport_adapter(transport)
    response = _verify(chain, key=f"{seed}-transport")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "verified"
    chain["verification_id"] = response.json()["id"]
    chain["transport_adapter"] = transport
    return chain


def _activate(chain: dict, *, key: str, reason: str = _REASON, actor_id=None):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-transport-verifications/{chain['verification_id']}/session-activations"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json={"request_key": key, "reason": reason},
    )


def _success_activation_result() -> SftpSessionActivationResult:
    return SftpSessionActivationResult(
        authentication_method="public_key",
        latency_class="fast",
        secret_resolution_performed=True,
        provider_network_performed=True,
        ssh_transport_performed=True,
        host_key_verification_performed=True,
        host_key_verified=True,
        authentication_performed=True,
        authentication_succeeded=True,
        sftp_session_opened=True,
        sftp_session_closed=True,
    )


def test_sftp_session_activation_proves_auth_and_subsystem_without_remote_access() -> None:
    chain = _verified_transport("sftp-session-activated")
    adapter = _DeterministicSessionActivationAdapter(_success_activation_result())
    register_external_document_source_sftp_session_activation_adapter(adapter)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    response = _activate(chain, key="sftp-session-activated-001")
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["result_status"] == "activated"
    assert body["failure_code"] is None
    assert body["authentication_kind"] == "private_key"
    assert body["authentication_method"] == "public_key"
    assert body["secret_resolution_performed"] is True
    assert body["provider_network_performed"] is True
    assert body["ssh_transport_performed"] is True
    assert body["host_key_verification_performed"] is True
    assert body["host_key_verified"] is True
    assert body["authentication_performed"] is True
    assert body["authentication_succeeded"] is True
    assert body["sftp_session_opened"] is True
    assert body["sftp_session_closed"] is True
    for field in (
        "credential_stored",
        "remote_list_performed",
        "remote_stat_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_rename_performed",
        "remote_delete_performed",
        "command_executed",
        "evidence_admitted",
        "document_created",
        "processing_enqueued",
        "ai_executed",
        "claim_mutated",
    ):
        assert body[field] is False

    assert len(adapter.calls) == 1
    request = adapter.calls[0]
    assert request.hostname == chain["hostname"]
    assert request.port == chain["port"]
    assert request.pinned_host_key_fingerprint == chain["fingerprint"]
    assert request.reference_backend == "hashicorp_vault"
    assert not hasattr(request, "password")
    assert not hasattr(request, "private_key")
    assert not hasattr(request, "passphrase")

    activation_id = body["id"]
    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-session-activations/{activation_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert rows[0]["authentication_performed"] is False
    assert rows[0]["sftp_session_opened"] is False
    assert rows[1]["authentication_performed"] is True
    assert rows[1]["sftp_session_opened"] is True
    assert rows[1]["sftp_session_closed"] is True

    replay = _activate(chain, key="sftp-session-activated-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == activation_id
    assert len(adapter.calls) == 1

    changed = _activate(
        chain,
        key="sftp-session-activated-001",
        reason="Changed replay must fail closed rather than authenticate a second time.",
    )
    assert changed.status_code == 409, changed.text
    second = _activate(chain, key="sftp-session-second-attempt")
    assert second.status_code == 409, second.text
    assert len(adapter.calls) == 1

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpSessionActivation).count() == 1
        assert db.query(ExternalDocumentSourceSftpSessionActivationReceipt).count() == 2
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before


def test_sftp_session_activation_requires_verified_f_and_registered_adapter() -> None:
    chain = _verified_transport("sftp-session-missing-adapter")
    missing = _activate(chain, key="sftp-session-missing-adapter")
    assert missing.status_code == 409, missing.text

    failed_chain = _completed_execution("sftp-session-unverified-f")
    register_external_document_source_sftp_transport_adapter(
        _DeterministicTransportAdapter(
            SftpTransportHostKeyProbeResult(
                observed_host_key_fingerprint="SHA256:" + ("B" * 43),
                host_key_algorithm="ssh-ed25519",
                latency_class="fast",
                destination_policy_enforced=True,
                dns_resolution_performed=True,
                provider_network_performed=True,
                ssh_transport_performed=True,
            )
        )
    )
    failed_f = _verify(failed_chain, key="sftp-session-unverified-f-transport")
    assert failed_f.status_code == 201, failed_f.text
    assert failed_f.json()["result_status"] == "failed"
    failed_chain["verification_id"] = failed_f.json()["id"]

    register_external_document_source_sftp_session_activation_adapter(
        _DeterministicSessionActivationAdapter(_success_activation_result())
    )
    rejected = _activate(failed_chain, key="sftp-session-reject-unverified")
    assert rejected.status_code == 409, rejected.text


def test_sftp_session_activation_failure_is_bounded_and_secret_safe() -> None:
    chain = _verified_transport("sftp-session-adapter-error")
    adapter = _DeterministicSessionActivationAdapter(
        _success_activation_result(),
        raise_error=True,
    )
    register_external_document_source_sftp_session_activation_adapter(adapter)
    response = _activate(chain, key="sftp-session-adapter-error")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["result_status"] == "failed"
    assert body["failure_code"] == "adapter_error"
    assert _SECRET_MARKER not in response.text

    with TestingSessionLocal() as db:
        serialized = json.dumps(
            [
                {"new_values": row.new_values, "details": row.details}
                for row in db.query(AuditLog).all()
            ],
            default=str,
        )
        assert _SECRET_MARKER not in serialized


def test_sftp_session_activation_adapter_boundary_violation_fails_closed() -> None:
    chain = _verified_transport("sftp-session-boundary")
    violating = _DeterministicSessionActivationAdapter(
        SftpSessionActivationResult(
            authentication_method="public_key",
            latency_class="fast",
            secret_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=True,
            host_key_verification_performed=True,
            host_key_verified=True,
            authentication_performed=True,
            authentication_succeeded=True,
            sftp_session_opened=True,
            sftp_session_closed=True,
            remote_operation_performed=True,
        )
    )
    register_external_document_source_sftp_session_activation_adapter(violating)
    response = _activate(chain, key="sftp-session-boundary")
    assert response.status_code == 409, response.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpSessionActivation).count() == 0


def test_sftp_session_activation_tenant_isolation() -> None:
    chain = _verified_transport("sftp-session-tenant")
    adapter = _DeterministicSessionActivationAdapter(_success_activation_result())
    register_external_document_source_sftp_session_activation_adapter(adapter)
    _, other_user, _, _ = _seed_tenant("sftp-session-other-tenant")
    response = _activate(chain, key="sftp-session-wrong-tenant", actor_id=other_user)
    assert response.status_code == 404, response.text
    assert adapter.calls == []
