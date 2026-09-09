from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.documents.models import Document
from app.modules.documents.recovery_promotion_models import EvidenceRecoveryPromotionAttestation
from app.modules.documents.recovery_restore_models import EvidenceRecoveryRestoreRehearsal
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _patch_settings,
    _replicate,
    _restore,
    _seed_tenant,
    _settings,
)


def setup_function() -> None:
    reset_database()


def _second_admin(organization_id: UUID, *, slug: str) -> UUID:
    with TestingSessionLocal() as db:
        admin = User(
            organization_id=organization_id,
            email=f"second-admin-{slug}@example.com",
            full_name=f"Second Admin {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin.id


def _request_attestation(claim_id: UUID, document_id: UUID, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations",
        headers=headers,
        json={"reason": "Request a governed non-cutover recovery promotion dry-run review."},
    )


def _approve_attestation(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/approve",
        headers=headers,
        json={"reason": "Second Admin confirms the exact recovery promotion dry-run lineage."},
    )


def _prepare_recovery(monkeypatch, tmp_path: Path, *, slug: str):
    org_id, admin_id, manager_id, claim_id, document_id, storage_key, local_path = _seed_tenant(
        slug=slug,
        storage_root=tmp_path,
    )
    settings = _settings(endpoint=_prepare_recovery.endpoint, storage_root=tmp_path)
    _patch_settings(monkeypatch, settings)
    admin_headers = _headers(admin_id)
    replicated = _replicate(claim_id, document_id, admin_headers)
    assert replicated.status_code == 201, replicated.text
    restored = _restore(claim_id, document_id, admin_headers)
    assert restored.status_code == 201, restored.text
    return (
        org_id,
        admin_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        restored,
        admin_headers,
    )


_prepare_recovery.endpoint = ""  # type: ignore[attr-defined]


def test_promotion_attestation_four_eyes_approval_is_non_cutover(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        _prepare_recovery.endpoint = endpoint  # type: ignore[attr-defined]
        (
            org_id,
            admin_id,
            manager_id,
            claim_id,
            document_id,
            storage_key,
            local_path,
            replicated,
            _restored,
            admin_headers,
        ) = _prepare_recovery(monkeypatch, tmp_path, slug="promotion-happy")
        second_admin_id = _second_admin(org_id, slug="promotion-happy")
        second_headers = _headers(second_admin_id)
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        remote_before = _RecoveryRestoreS3Handler.objects[remote_key]

        requested = _request_attestation(claim_id, document_id, admin_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["status"] == "pending_second_approval"
        assert body["cutover_performed"] is False
        assert body["authoritative_storage_changed"] is False
        assert all(action["execute"] is False for action in body["promotion_plan"]["actions"])
        assert storage_key not in str(body)

        with TestingSessionLocal() as db:
            rehearsal = db.query(EvidenceRecoveryRestoreRehearsal).one()
            assert rehearsal.staging_storage_key not in str(body)

        same_admin = _approve_attestation(
            claim_id,
            document_id,
            body["id"],
            admin_headers,
        )
        assert same_admin.status_code == 409

        approved = _approve_attestation(
            claim_id,
            document_id,
            body["id"],
            second_headers,
        )
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["status"] == "approved"
        assert approved_body["approved_by_id"] == str(second_admin_id)
        assert approved_body["cutover_performed"] is False
        assert approved_body["authoritative_storage_changed"] is False

        manager_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{body['id']}",
            headers=_headers(manager_id),
        )
        assert manager_read.status_code == 200

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            attestation = db.get(EvidenceRecoveryPromotionAttestation, UUID(body["id"]))
            rehearsal = db.query(EvidenceRecoveryRestoreRehearsal).one()
            assert document is not None
            assert attestation is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
            assert attestation.cutover_performed is False
            assert attestation.authoritative_storage_changed is False
            assert local_path.exists()
            assert (tmp_path / rehearsal.staging_storage_key).exists()
            audits = db.query(AuditLog).filter(
                AuditLog.action == "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_APPROVED"
            ).all()
            assert audits
            rendered = str(audits[-1].new_values)
            assert storage_key not in rendered
            assert rehearsal.staging_storage_key not in rendered
            assert audits[-1].new_values["cutover_performed"] is False
            assert audits[-1].new_values["authoritative_storage_changed"] is False

        assert _RecoveryRestoreS3Handler.objects[remote_key] == remote_before


def test_promotion_attestation_staging_drift_invalidates_before_approval(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        _prepare_recovery.endpoint = endpoint  # type: ignore[attr-defined]
        (
            org_id,
            admin_id,
            _manager_id,
            claim_id,
            document_id,
            storage_key,
            local_path,
            replicated,
            _restored,
            admin_headers,
        ) = _prepare_recovery(monkeypatch, tmp_path, slug="promotion-stage-drift")
        second_admin_id = _second_admin(org_id, slug="promotion-stage-drift")
        requested = _request_attestation(claim_id, document_id, admin_headers)
        assert requested.status_code == 201, requested.text

        with TestingSessionLocal() as db:
            rehearsal = db.query(EvidenceRecoveryRestoreRehearsal).one()
            staging_path = tmp_path / rehearsal.staging_storage_key
        staging_path.write_bytes(b"tampered restore staging after request")

        approved = _approve_attestation(
            claim_id,
            document_id,
            requested.json()["id"],
            _headers(second_admin_id),
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "invalidated"
        assert approved.json()["approved_by_id"] is None
        assert approved.json()["cutover_performed"] is False

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
        assert local_path.exists()
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        assert remote_key in _RecoveryRestoreS3Handler.objects


def test_new_restore_verification_after_request_invalidates_attestation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        _prepare_recovery.endpoint = endpoint  # type: ignore[attr-defined]
        (
            org_id,
            _admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            _restored,
            admin_headers,
        ) = _prepare_recovery(monkeypatch, tmp_path, slug="promotion-verification-drift")
        second_admin_id = _second_admin(org_id, slug="promotion-verification-drift")
        requested = _request_attestation(claim_id, document_id, admin_headers)
        assert requested.status_code == 201, requested.text
        pinned_verification_id = requested.json()["restore_verification_id"]

        reverified = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-restore-rehearsal/verify",
            headers=admin_headers,
            json={"reason": "Create a newer recovery restore verification after promotion request."},
        )
        assert reverified.status_code == 200, reverified.text
        assert reverified.json()["id"] != pinned_verification_id

        approved = _approve_attestation(
            claim_id,
            document_id,
            requested.json()["id"],
            _headers(second_admin_id),
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "invalidated"
        assert approved.json()["decision_reason"] is not None


def test_promotion_attestation_expiry_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        _prepare_recovery.endpoint = endpoint  # type: ignore[attr-defined]
        (
            org_id,
            _admin_id,
            _manager_id,
            claim_id,
            document_id,
            storage_key,
            _local_path,
            _replicated,
            _restored,
            admin_headers,
        ) = _prepare_recovery(monkeypatch, tmp_path, slug="promotion-expiry")
        second_admin_id = _second_admin(org_id, slug="promotion-expiry")
        requested = _request_attestation(claim_id, document_id, admin_headers)
        assert requested.status_code == 201, requested.text
        attestation_id = UUID(requested.json()["id"])

        with TestingSessionLocal() as db:
            attestation = db.get(EvidenceRecoveryPromotionAttestation, attestation_id)
            assert attestation is not None
            attestation.attestation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        approved = _approve_attestation(
            claim_id,
            document_id,
            str(attestation_id),
            _headers(second_admin_id),
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "expired"
        assert approved.json()["cutover_performed"] is False

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key


def test_promotion_attestation_rbac_cross_tenant_and_mfa(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        _prepare_recovery.endpoint = endpoint  # type: ignore[attr-defined]
        (
            org_a,
            admin_a,
            manager_a,
            claim_a,
            document_a,
            _key_a,
            _path_a,
            _replicated,
            _restored,
            admin_headers,
        ) = _prepare_recovery(monkeypatch, tmp_path / "a", slug="promotion-tenant-a")
        _org_b, _admin_b, manager_b, _claim_b, _document_b, _key_b, _path_b = _seed_tenant(
            slug="promotion-tenant-b",
            storage_root=tmp_path / "b",
        )

        manager_mutation = _request_attestation(claim_a, document_a, _headers(manager_a))
        assert manager_mutation.status_code == 403

        requested = _request_attestation(claim_a, document_a, admin_headers)
        assert requested.status_code == 201, requested.text

        cross_tenant = client.get(
            f"/api/v1/claims/{claim_a}/documents/{document_a}/recovery-promotion-attestations/{requested.json()['id']}",
            headers=_headers(manager_b),
        )
        assert cross_tenant.status_code == 404

        with TestingSessionLocal() as db:
            db.add(
                MfaPolicy(
                    organization_id=org_a,
                    is_enabled=True,
                    required_roles=[UserRole.ADMIN.value],
                    updated_by_id=admin_a,
                )
            )
            db.commit()

        blocked = client.post(
            f"/api/v1/claims/{claim_a}/documents/{document_a}/recovery-promotion-attestations/{requested.json()['id']}/reject",
            headers=_headers(admin_a),
            json={"reason": "MFA policy must gate recovery promotion attestation mutations."},
        )
        assert blocked.status_code == 403
