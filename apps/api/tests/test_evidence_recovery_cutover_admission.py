from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_cutover_admission_models import (
    EvidenceRecoveryCutoverAdmission,
    EvidenceRecoveryCutoverAdmissionReceipt,
)
from app.modules.documents.recovery_shadow_models import EvidenceRecoveryShadowPromotion
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_authority_switch_rehearsal import (
    _activate_switch,
    _prepare_switch,
    _ready_shadow,
    _rollback_switch,
)
from tests.test_evidence_recovery_promotion_attestation import _second_admin
from tests.test_evidence_recovery_restore_rehearsal import _RecoveryRestoreS3Handler, _fake_s3, _headers


def setup_function() -> None:
    reset_database()


def _rolled_back_chain(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    (
        org_id,
        admin_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        admin_headers,
        _attestation_id,
        shadow_id,
    ) = _ready_shadow(monkeypatch, tmp_path, endpoint, slug=slug)
    approver_id = _second_admin(org_id, slug=f"{slug}-second-admin")
    approver_headers = _headers(approver_id)
    prepared = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
    assert prepared.status_code == 201, prepared.text
    rehearsal_id = prepared.json()["rehearsal"]["id"]
    activated = _activate_switch(claim_id, document_id, rehearsal_id, approver_headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["outcome"] == "activated"
    rolled_back = _rollback_switch(claim_id, document_id, rehearsal_id, admin_headers)
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"
    return (
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
    )


def _request(claim_id: UUID, document_id: UUID, rehearsal_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/cutover-admission",
        headers=headers,
        json={"reason": "Request governed reversible cutover admission after a successful rollback rehearsal."},
    )


def _approve(claim_id: UUID, document_id: UUID, admission_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}/approve",
        headers=headers,
        json={"reason": "Independently approve the bounded cutover admission envelope without execution authority."},
    )


def test_cutover_admission_requires_rollback_and_second_admin_without_authority_mutation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
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
        ) = _rolled_back_chain(monkeypatch, tmp_path, endpoint, slug="cutover-admission-happy")
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        remote_before = _RecoveryRestoreS3Handler.objects[remote_key]

        requested = _request(claim_id, document_id, rehearsal_id, admin_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "requested"
        assert body["admission"]["status"] == "pending_second_approval"
        assert body["admission"]["cutover_performed"] is False
        assert body["admission"]["authoritative_storage_changed"] is False
        assert body["admission"]["document_storage_key_mutated"] is False
        assert body["admission"]["active_backend_changed"] is False
        assert body["admission"]["production_execution_token_created"] is False
        assert body["admission"]["execution_authority_created"] is False
        admission_id = body["admission"]["id"]

        replay = _request(claim_id, document_id, rehearsal_id, admin_headers)
        assert replay.status_code == 201
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["admission"]["id"] == admission_id
        assert replay.json()["receipt"] is None

        same_admin = _approve(claim_id, document_id, admission_id, admin_headers)
        assert same_admin.status_code == 409

        approved = _approve(claim_id, document_id, admission_id, approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        assert approved.json()["admission"]["status"] == "approved"
        assert approved.json()["admission"]["production_execution_token_created"] is False
        assert approved.json()["admission"]["execution_authority_created"] is False

        manager_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}",
            headers=_headers(manager_id),
        )
        assert manager_read.status_code == 200
        assert manager_read.json()["status"] == "approved"

        receipts = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}/receipts",
            headers=_headers(manager_id),
        )
        assert receipts.status_code == 200
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        assert all(item["execution_authority_created"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            admission = db.get(EvidenceRecoveryCutoverAdmission, UUID(admission_id))
            assert document is not None and shadow is not None and admission is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
            assert local_path.exists()
            assert (tmp_path / shadow.shadow_storage_key).exists()
            assert db.query(EvidenceRecoveryCutoverAdmissionReceipt).count() == 2
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.action == "EVIDENCE_RECOVERY_CUTOVER_ADMISSION_APPROVED")
                .one()
            )
            rendered = str(audit.new_values)
            assert storage_key not in rendered
            assert shadow.shadow_storage_key not in rendered
            assert audit.new_values["cutover_performed"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            assert audit.new_values["production_execution_token_created"] is False
            assert audit.new_values["execution_authority_created"] is False
        assert _RecoveryRestoreS3Handler.objects[remote_key] == remote_before


def test_cutover_admission_rejects_non_rolled_back_rehearsal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            org_id,
            _admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            _attestation_id,
            shadow_id,
        ) = _ready_shadow(monkeypatch, tmp_path, endpoint, slug="cutover-admission-not-rolled-back")
        approver_id = _second_admin(org_id, slug="cutover-admission-not-rolled-back-second")
        prepared = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
        assert prepared.status_code == 201
        rehearsal_id = prepared.json()["rehearsal"]["id"]
        activated = _activate_switch(claim_id, document_id, rehearsal_id, _headers(approver_id))
        assert activated.status_code == 200
        blocked = _request(claim_id, document_id, rehearsal_id, admin_headers)
        assert blocked.status_code == 409


def test_cutover_admission_expiry_fails_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            approver_headers,
            _shadow_id,
            rehearsal_id,
        ) = _rolled_back_chain(monkeypatch, tmp_path, endpoint, slug="cutover-admission-expiry")
        requested = _request(claim_id, document_id, rehearsal_id, admin_headers)
        assert requested.status_code == 201
        admission_id = UUID(requested.json()["admission"]["id"])
        with TestingSessionLocal() as db:
            admission = db.get(EvidenceRecoveryCutoverAdmission, admission_id)
            assert admission is not None
            admission.admission_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired = _approve(claim_id, document_id, str(admission_id), approver_headers)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["admission"]["status"] == "expired"
        assert expired.json()["admission"]["execution_authority_created"] is False


def test_shadow_drift_invalidates_pending_cutover_admission(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _manager_id,
            claim_id,
            document_id,
            storage_key,
            _local_path,
            _replicated,
            admin_headers,
            approver_headers,
            shadow_id,
            rehearsal_id,
        ) = _rolled_back_chain(monkeypatch, tmp_path, endpoint, slug="cutover-admission-drift")
        requested = _request(claim_id, document_id, rehearsal_id, admin_headers)
        assert requested.status_code == 201
        admission_id = requested.json()["admission"]["id"]
        with TestingSessionLocal() as db:
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            assert shadow is not None
            shadow_path = tmp_path / shadow.shadow_storage_key
        shadow_path.write_bytes(b"tampered after cutover admission request")
        invalidated = _approve(claim_id, document_id, admission_id, approver_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["admission"]["status"] == "invalidated"
        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key


def test_claims_manager_can_read_but_cannot_mutate_cutover_admission(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            _approver_headers,
            _shadow_id,
            rehearsal_id,
        ) = _rolled_back_chain(monkeypatch, tmp_path, endpoint, slug="cutover-admission-rbac")
        requested = _request(claim_id, document_id, rehearsal_id, admin_headers)
        assert requested.status_code == 201
        admission_id = requested.json()["admission"]["id"]
        manager_headers = _headers(manager_id)
        readable = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-cutover-admissions/{admission_id}",
            headers=manager_headers,
        )
        assert readable.status_code == 200
        forbidden = _approve(claim_id, document_id, admission_id, manager_headers)
        assert forbidden.status_code == 403
