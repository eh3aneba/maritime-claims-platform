import json
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_credential_health_models import (
    ExternalDocumentSourceSftpCredentialHealthQualification,
    ExternalDocumentSourceSftpCredentialHealthReceipt,
)
from app.modules.external_document_sources.sftp_credential_health_service import (
    SftpCredentialHealthProbeResult,
    clear_external_document_source_sftp_credential_health_resolvers,
    register_external_document_source_sftp_credential_health_resolver,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_credential_reference import (
    _active_sftp_profile,
    _request_binding,
)

_EPHEMERAL_MARKER = "ephemeral-material-never-persist"
_DEFAULT_REASON = (
    "Qualify only the approved SFTP credential reference without opening an "
    "SSH or SFTP session."
)


class _DeterministicResolver:
    resolver_kind = "deterministic_sftp_health_resolver"

    def __init__(
        self,
        *,
        resolved: bool,
        material_kind: str | None = None,
        failure_code: str | None = None,
        raise_error: bool = False,
    ):
        self.resolved = resolved
        self.material_kind = material_kind
        self.failure_code = failure_code
        self.raise_error = raise_error
        self.calls = 0
        self._ephemeral_material = _EPHEMERAL_MARKER

    def check(self, locator):
        self.calls += 1
        assert locator.backend == "hashicorp_vault"
        assert locator.namespace == "mcri-prod"
        assert locator.name in {
            "sftp-claims-reader",
            "sftp-password-reference",
        }
        assert locator.version == "v1"
        assert locator.authentication_kind in {"password", "private_key"}
        assert self._ephemeral_material == _EPHEMERAL_MARKER
        if self.raise_error:
            raise RuntimeError("bounded resolver failure")
        return SftpCredentialHealthProbeResult(
            resolved=self.resolved,
            material_kind=self.material_kind,
            failure_code=self.failure_code,
        )


def setup_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_sftp_credential_health_resolvers()


def _active_binding(
    seed: str,
    *,
    authentication_kind: str = "private_key",
):
    (
        _org_id,
        requester_id,
        approver_id,
        _manager_id,
        profile_id,
    ) = _active_sftp_profile(seed)
    requested = _request_binding(
        profile_id,
        requester_id,
        key=f"{seed}-binding",
        authentication_kind=authentication_kind,
        name=(
            "sftp-password-reference"
            if authentication_kind == "password"
            else "sftp-claims-reader"
        ),
    )
    assert requested.status_code == 201, requested.text
    binding_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve the non-secret SFTP credential reference "
                "before health qualification."
            )
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    return requester_id, approver_id, profile_id, binding_id


def _qualify(
    profile_id: str,
    binding_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _DEFAULT_REASON,
):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/health-qualifications",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def test_sftp_credential_health_qualifies_without_persisting_secret_material() -> None:
    requester_id, _approver_id, profile_id, binding_id = _active_binding(
        "sftp-health-success"
    )
    _, other_requester_id, _, _ = _seed_tenant("sftp-health-other-tenant")

    resolver = _DeterministicResolver(
        resolved=True,
        material_kind="private_key",
    )
    register_external_document_source_sftp_credential_health_resolver(
        "hashicorp_vault",
        resolver,
    )

    wrong_tenant = _qualify(
        profile_id,
        binding_id,
        other_requester_id,
        key="sftp-health-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert resolver.calls == 0

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    qualified = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="sftp-health-success-check",
    )
    assert qualified.status_code == 201, qualified.text
    body = qualified.json()
    qualification_id = body["id"]
    assert body["result_status"] == "qualified"
    assert body["failure_code"] is None
    assert body["authentication_kind"] == "private_key"
    assert body["resolved_material_kind"] == "private_key"
    assert body["credential_reference_stored"] is True
    assert body["secret_resolution_performed"] is True
    assert len(body["scope_hash"]) == 64
    assert len(body["request_hash"]) == 64
    assert len(body["result_hash"]) == 64
    assert _EPHEMERAL_MARKER not in qualified.text

    for field in (
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
    assert resolver.calls == 1

    replay = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="sftp-health-success-check",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == qualification_id
    assert resolver.calls == 1

    changed_replay = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="sftp-health-success-check",
        reason=(
            "Attempt a changed replay that must not cause a second secret "
            "resolution."
        ),
    )
    assert changed_replay.status_code == 409, changed_replay.text
    assert resolver.calls == 1

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == [
        "requested",
        "completed",
    ]
    assert [row["status_after"] for row in receipt_rows] == [
        "requested",
        "qualified",
    ]
    assert receipt_rows[0]["secret_resolution_performed"] is False
    assert receipt_rows[1]["secret_resolution_performed"] is True
    assert (
        receipt_rows[1]["prior_receipt_hash"]
        == receipt_rows[0]["receipt_hash"]
    )
    assert _EPHEMERAL_MARKER not in receipts.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before

        row = db.query(
            ExternalDocumentSourceSftpCredentialHealthQualification
        ).one()
        stored_receipts = db.query(
            ExternalDocumentSourceSftpCredentialHealthReceipt
        ).all()
        audit_rows = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type
                == "external_document_source_sftp_credential_health_qualification"
            )
            .all()
        )
        persisted = json.dumps(
            {
                "qualification": {
                    key: str(value)
                    for key, value in row.__dict__.items()
                    if not key.startswith("_")
                },
                "receipts": [
                    {
                        key: str(value)
                        for key, value in receipt.__dict__.items()
                        if not key.startswith("_")
                    }
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
        assert _EPHEMERAL_MARKER not in persisted
        assert len(stored_receipts) == 2
        assert len(audit_rows) == 1

        stored_receipts[0].reason = (
            "Tampered SFTP health receipt reason that must invalidate the chain."
        )
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text


def test_sftp_credential_health_fails_closed_on_kind_mismatch_and_disabled_binding() -> None:
    requester_id, _approver_id, profile_id, binding_id = _active_binding(
        "sftp-health-kind-mismatch",
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

    mismatch = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="sftp-health-kind-mismatch-check",
    )
    assert mismatch.status_code == 201, mismatch.text
    body = mismatch.json()
    qualification_id = body["id"]
    assert body["result_status"] == "unqualified"
    assert body["failure_code"] == "authentication_kind_mismatch"
    assert body["authentication_kind"] == "password"
    assert body["resolved_material_kind"] == "private_key"
    assert body["authentication_performed"] is False
    assert body["sftp_session_opened"] is False
    assert resolver.calls == 1

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={
            "reason": (
                "Disable the upstream SFTP credential reference so health "
                "qualification must fail closed."
            )
        },
    )
    assert disabled.status_code == 200, disabled.text

    read = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/sftp-credential-health-qualifications/{qualification_id}",
        headers=_headers(requester_id),
    )
    assert read.status_code == 409, read.text


def test_sftp_credential_health_records_bounded_resolution_failures() -> None:
    requester_id, _approver_id, profile_id, binding_id = _active_binding(
        "sftp-health-resolution-failure"
    )

    unavailable = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="sftp-health-no-resolver",
    )
    assert unavailable.status_code == 409, unavailable.text
    with TestingSessionLocal() as db:
        assert (
            db.query(
                ExternalDocumentSourceSftpCredentialHealthQualification
            ).count()
            == 0
        )

    resolver = _DeterministicResolver(
        resolved=False,
        failure_code="reference_not_found",
    )
    register_external_document_source_sftp_credential_health_resolver(
        "hashicorp_vault",
        resolver,
    )
    unqualified = _qualify(
        profile_id,
        binding_id,
        requester_id,
        key="sftp-health-reference-missing",
    )
    assert unqualified.status_code == 201, unqualified.text
    body = unqualified.json()
    assert body["result_status"] == "unqualified"
    assert body["failure_code"] == "reference_not_found"
    assert body["resolved_material_kind"] is None
    assert body["secret_resolution_performed"] is True
    assert body["provider_network_performed"] is False

    clear_external_document_source_sftp_credential_health_resolvers()

    requester2, _approver2, profile2, binding2 = _active_binding(
        "sftp-health-resolver-exception"
    )
    broken_resolver = _DeterministicResolver(
        resolved=True,
        material_kind="private_key",
        raise_error=True,
    )
    register_external_document_source_sftp_credential_health_resolver(
        "hashicorp_vault",
        broken_resolver,
    )
    bounded = _qualify(
        profile2,
        binding2,
        requester2,
        key="sftp-health-resolver-rejected",
    )
    assert bounded.status_code == 201, bounded.text
    bounded_body = bounded.json()
    assert bounded_body["result_status"] == "unqualified"
    assert bounded_body["failure_code"] == "resolver_rejected"
    assert bounded_body["resolved_material_kind"] is None
    assert "bounded resolver failure" not in bounded.text
