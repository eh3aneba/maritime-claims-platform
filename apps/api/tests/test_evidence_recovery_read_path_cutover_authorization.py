from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_read_path_cutover_models import (
    EvidenceRecoveryReadPathCutoverAuthorization,
    EvidenceRecoveryReadPathCutoverAuthorizationReceipt,
)
from app.modules.documents.recovery_shadow_models import EvidenceRecoveryShadowPromotion
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_cutover_execution_lease import (
    _activate,
    _approved_admission,
    _prepare,
    _rollback,
)
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
)


def setup_function() -> None:
    reset_database()


def _rolled_back_execution_chain(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    (
        org_id,
        admin_id,
        approver_id,
        third_admin_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        admin_headers,
        approver_headers,
        third_headers,
        shadow_id,
        admission_id,
    ) = _approved_admission(monkeypatch, tmp_path, endpoint, slug=slug)

    prepared = _prepare(claim_id, document_id, admission_id, admin_headers)
    assert prepared.status_code == 201, prepared.text
    lease_id = prepared.json()["lease"]["id"]
    activated = _activate(claim_id, document_id, lease_id, third_headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["outcome"] == "activated"
    rolled_back = _rollback(claim_id, document_id, lease_id, admin_headers)
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"

    return (
        org_id,
        admin_id,
        approver_id,
        third_admin_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        admin_headers,
        approver_headers,
        third_headers,
        shadow_id,
        lease_id,
    )


def _request_authorization(
    claim_id: UUID,
    document_id: UUID,
    lease_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}/read-path-cutover-authorization",
        headers=headers,
        json={"reason": "Request governed approval for a future reversible production read-path cutover."},
    )


def _approve_authorization(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": "Independently approve only the bounded future read-path cutover envelope."},
    )


def test_read_path_cutover_authorization_requires_rolled_back_execution_and_independent_approval(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            manager_id,
            claim_id,
            document_id,
            storage_key,
            local_path,
            replicated,
            admin_headers,
            approver_headers,
            third_headers,
            shadow_id,
            lease_id,
        ) = _rolled_back_execution_chain(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-cutover-auth-happy",
        )
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        remote_before = _RecoveryRestoreS3Handler.objects[remote_key]

        requested = _request_authorization(claim_id, document_id, lease_id, admin_headers)
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "requested"
        authorization = requested.json()["authorization"]
        authorization_id = authorization["id"]
        for field in (
            "routable_authority_created",
            "read_path_switched",
            "document_storage_key_mutated",
            "active_backend_changed",
            "authoritative_storage_changed",
            "destructive_action_performed",
            "s3_delete_performed",
            "local_delete_performed",
        ):
            assert authorization[field] is False

        replay = _request_authorization(claim_id, document_id, lease_id, admin_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        same_requester = _approve_authorization(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        assert same_requester.status_code == 409

        execution_activator = _approve_authorization(
            claim_id,
            document_id,
            authorization_id,
            third_headers,
        )
        assert execution_activator.status_code == 409

        approved = _approve_authorization(
            claim_id,
            document_id,
            authorization_id,
            approver_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        assert approved.json()["authorization"]["status"] == "approved"
        assert approved.json()["authorization"]["read_path_switched"] is False
        assert approved.json()["authorization"]["routable_authority_created"] is False

        manager_headers = _headers(manager_id)
        readable = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}",
            headers=manager_headers,
        )
        assert readable.status_code == 200
        receipts = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}/receipts",
            headers=manager_headers,
        )
        assert receipts.status_code == 200
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        assert all(item["read_path_switched"] is False for item in receipts.json())
        assert all(item["routable_authority_created"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            stored = db.get(
                EvidenceRecoveryReadPathCutoverAuthorization,
                UUID(authorization_id),
            )
            assert document is not None and shadow is not None and stored is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
            assert local_path.exists()
            assert (tmp_path / shadow.shadow_storage_key).exists()
            assert db.query(EvidenceRecoveryReadPathCutoverAuthorizationReceipt).count() == 2
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.action == "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_APPROVED")
                .one()
            )
            rendered = str(audit.new_values)
            assert storage_key not in rendered
            assert shadow.shadow_storage_key not in rendered
            assert audit.new_values["routable_authority_created"] is False
            assert audit.new_values["read_path_switched"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            assert audit.new_values["destructive_action_performed"] is False
        assert _RecoveryRestoreS3Handler.objects[remote_key] == remote_before


def test_prepared_execution_lease_cannot_request_read_path_cutover_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            _approver_headers,
            _third_headers,
            _shadow_id,
            admission_id,
        ) = _approved_admission(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-cutover-auth-prepared",
        )
        prepared = _prepare(claim_id, document_id, admission_id, admin_headers)
        assert prepared.status_code == 201
        lease_id = prepared.json()["lease"]["id"]
        blocked = _request_authorization(claim_id, document_id, lease_id, admin_headers)
        assert blocked.status_code == 409


def test_read_path_cutover_authorization_expiry_fails_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            approver_headers,
            _third_headers,
            _shadow_id,
            lease_id,
        ) = _rolled_back_execution_chain(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-cutover-auth-expiry",
        )
        requested = _request_authorization(claim_id, document_id, lease_id, admin_headers)
        assert requested.status_code == 201
        authorization_id = UUID(requested.json()["authorization"]["id"])
        with TestingSessionLocal() as db:
            authorization = db.get(
                EvidenceRecoveryReadPathCutoverAuthorization,
                authorization_id,
            )
            assert authorization is not None
            authorization.authorization_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired = _approve_authorization(
            claim_id,
            document_id,
            str(authorization_id),
            approver_headers,
        )
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["authorization"]["status"] == "expired"


def test_shadow_drift_invalidates_pending_read_path_cutover_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            storage_key,
            _local_path,
            _replicated,
            admin_headers,
            approver_headers,
            _third_headers,
            shadow_id,
            lease_id,
        ) = _rolled_back_execution_chain(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-cutover-auth-drift",
        )
        requested = _request_authorization(claim_id, document_id, lease_id, admin_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        with TestingSessionLocal() as db:
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            assert shadow is not None
            shadow_path = tmp_path / shadow.shadow_storage_key
        shadow_path.write_bytes(b"tampered after read-path cutover authorization request")

        invalidated = _approve_authorization(
            claim_id,
            document_id,
            authorization_id,
            approver_headers,
        )
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["authorization"]["status"] == "invalidated"
        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key


def test_claims_manager_can_read_but_cannot_mutate_read_path_cutover_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            _approver_headers,
            _third_headers,
            _shadow_id,
            lease_id,
        ) = _rolled_back_execution_chain(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-cutover-auth-rbac",
        )
        requested = _request_authorization(claim_id, document_id, lease_id, admin_headers)
        assert requested.status_code == 201
        authorization_id = requested.json()["authorization"]["id"]
        manager_headers = _headers(manager_id)
        readable = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}",
            headers=manager_headers,
        )
        assert readable.status_code == 200
        forbidden = _approve_authorization(
            claim_id,
            document_id,
            authorization_id,
            manager_headers,
        )
        assert forbidden.status_code == 403
