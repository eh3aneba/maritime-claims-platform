from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_cutover_execution_models import (
    EvidenceRecoveryCutoverExecutionLease,
    EvidenceRecoveryCutoverExecutionReceipt,
)
from app.modules.documents.recovery_shadow_models import EvidenceRecoveryShadowPromotion
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_cutover_admission import _approve, _request, _rolled_back_chain
from tests.test_evidence_recovery_promotion_attestation import _second_admin
from tests.test_evidence_recovery_restore_rehearsal import _RecoveryRestoreS3Handler, _fake_s3, _headers


def setup_function() -> None:
    reset_database()


def _approved_admission(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    (
        org_id,
        admin_id,
        approver_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        admin_headers,
        approver_headers,
        shadow_id,
        rehearsal_id,
    ) = _rolled_back_chain(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request(claim_id, document_id, rehearsal_id, admin_headers)
    assert requested.status_code == 201, requested.text
    admission_id = requested.json()["admission"]["id"]
    approved = _approve(claim_id, document_id, admission_id, approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    third_admin_id = _second_admin(org_id, slug=f"{slug}-third-admin")
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
        _headers(third_admin_id),
        shadow_id,
        admission_id,
    )


def _prepare(claim_id: UUID, document_id: UUID, admission_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}/execution-lease",
        headers=headers,
        json={"reason": "Prepare the bounded non-routable recovery cutover execution lease."},
    )


def _activate(claim_id: UUID, document_id: UUID, lease_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}/activate",
        headers=headers,
        json={"reason": "Independently activate the bounded execution control-plane lease."},
    )


def _rollback(claim_id: UUID, document_id: UUID, lease_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}/rollback",
        headers=headers,
        json={"reason": "Roll back the non-routable execution lease to its safe terminal state."},
    )


def test_execution_lease_requires_independent_activation_and_rolls_back_without_authority_mutation(monkeypatch, tmp_path: Path) -> None:
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
            admission_id,
        ) = _approved_admission(monkeypatch, tmp_path, endpoint, slug="cutover-exec-happy")
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        remote_before = _RecoveryRestoreS3Handler.objects[remote_key]

        prepared = _prepare(claim_id, document_id, admission_id, admin_headers)
        assert prepared.status_code == 201, prepared.text
        assert prepared.json()["outcome"] == "prepared"
        lease = prepared.json()["lease"]
        lease_id = lease["id"]
        for field in (
            "read_path_switched",
            "document_storage_key_mutated",
            "active_backend_changed",
            "authoritative_storage_changed",
            "destructive_action_performed",
            "s3_delete_performed",
            "local_delete_performed",
        ):
            assert lease[field] is False

        replay = _prepare(claim_id, document_id, admission_id, admin_headers)
        assert replay.status_code == 201
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id

        same_preparer = _activate(claim_id, document_id, lease_id, admin_headers)
        assert same_preparer.status_code == 409
        admission_approver = _activate(claim_id, document_id, lease_id, approver_headers)
        assert admission_approver.status_code == 409

        activated = _activate(claim_id, document_id, lease_id, third_headers)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        assert activated.json()["lease"]["read_path_switched"] is False

        rolled_back = _rollback(claim_id, document_id, lease_id, admin_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["lease"]["status"] == "rolled_back"

        manager_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}",
            headers=_headers(manager_id),
        )
        assert manager_read.status_code == 200
        receipts = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}/receipts",
            headers=_headers(manager_id),
        )
        assert receipts.status_code == 200
        assert [item["phase"] for item in receipts.json()] == ["prepared", "activated", "rolled_back"]
        assert all(item["read_path_switched"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            stored_lease = db.get(EvidenceRecoveryCutoverExecutionLease, UUID(lease_id))
            assert document is not None and shadow is not None and stored_lease is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
            assert local_path.exists()
            assert (tmp_path / shadow.shadow_storage_key).exists()
            assert db.query(EvidenceRecoveryCutoverExecutionReceipt).count() == 3
            audit = db.query(AuditLog).filter(AuditLog.action == "EVIDENCE_RECOVERY_CUTOVER_EXECUTION_ACTIVATED").one()
            rendered = str(audit.new_values)
            assert storage_key not in rendered
            assert shadow.shadow_storage_key not in rendered
            assert audit.new_values["read_path_switched"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            assert audit.new_values["destructive_action_performed"] is False
        assert _RecoveryRestoreS3Handler.objects[remote_key] == remote_before


def test_execution_lease_expiry_fails_closed(monkeypatch, tmp_path: Path) -> None:
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
            third_headers,
            _shadow_id,
            admission_id,
        ) = _approved_admission(monkeypatch, tmp_path, endpoint, slug="cutover-exec-expiry")
        prepared = _prepare(claim_id, document_id, admission_id, admin_headers)
        assert prepared.status_code == 201
        lease_id = UUID(prepared.json()["lease"]["id"])
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryCutoverExecutionLease, lease_id)
            assert lease is not None
            lease.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired = _activate(claim_id, document_id, str(lease_id), third_headers)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["lease"]["status"] == "expired"


def test_execution_rollback_remains_available_after_lease_expiry(monkeypatch, tmp_path: Path) -> None:
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
            third_headers,
            _shadow_id,
            admission_id,
        ) = _approved_admission(monkeypatch, tmp_path, endpoint, slug="cutover-exec-late-rollback")
        prepared = _prepare(claim_id, document_id, admission_id, admin_headers)
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate(claim_id, document_id, lease_id, third_headers)
        assert activated.status_code == 200 and activated.json()["outcome"] == "activated"
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryCutoverExecutionLease, UUID(lease_id))
            assert lease is not None
            lease.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
            db.commit()
        rolled_back = _rollback(claim_id, document_id, lease_id, admin_headers)
        assert rolled_back.status_code == 200
        assert rolled_back.json()["outcome"] == "rolled_back"


def test_shadow_drift_invalidates_prepared_execution_lease(monkeypatch, tmp_path: Path) -> None:
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
            _approver_headers,
            third_headers,
            shadow_id,
            admission_id,
        ) = _approved_admission(monkeypatch, tmp_path, endpoint, slug="cutover-exec-drift")
        prepared = _prepare(claim_id, document_id, admission_id, admin_headers)
        assert prepared.status_code == 201
        lease_id = prepared.json()["lease"]["id"]
        with TestingSessionLocal() as db:
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            assert shadow is not None
            shadow_path = tmp_path / shadow.shadow_storage_key
        shadow_path.write_bytes(b"tampered after execution lease preparation")
        invalidated = _activate(claim_id, document_id, lease_id, third_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key


def test_claims_manager_can_read_but_cannot_mutate_execution_lease(monkeypatch, tmp_path: Path) -> None:
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
            admission_id,
        ) = _approved_admission(monkeypatch, tmp_path, endpoint, slug="cutover-exec-rbac")
        prepared = _prepare(claim_id, document_id, admission_id, admin_headers)
        assert prepared.status_code == 201
        lease_id = prepared.json()["lease"]["id"]
        manager_headers = _headers(manager_id)
        readable = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{lease_id}",
            headers=manager_headers,
        )
        assert readable.status_code == 200
        forbidden = _activate(claim_id, document_id, lease_id, manager_headers)
        assert forbidden.status_code == 403
