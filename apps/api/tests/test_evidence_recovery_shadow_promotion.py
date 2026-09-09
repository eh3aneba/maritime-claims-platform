from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.documents import recovery_shadow_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_promotion_models import EvidenceRecoveryPromotionAttestation
from app.modules.documents.recovery_restore_models import EvidenceRecoveryRestoreRehearsal
from app.modules.documents.recovery_shadow_models import (
    EvidenceRecoveryShadowPromotion,
    EvidenceRecoveryShadowVerification,
)
from app.modules.users.models import UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_promotion_attestation import (
    _approve_attestation,
    _prepare_recovery,
    _request_attestation,
    _second_admin,
)
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
    _settings,
)


def setup_function() -> None:
    reset_database()


def _shadow_headers_settings(monkeypatch, endpoint: str, storage_root: Path) -> None:
    settings = _settings(endpoint=endpoint, storage_root=storage_root)
    monkeypatch.setattr(recovery_shadow_service, "get_settings", lambda: settings)


def _approve_ready_attestation(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    _prepare_recovery.endpoint = endpoint  # type: ignore[attr-defined]
    prepared = _prepare_recovery(monkeypatch, tmp_path, slug=slug)
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
    ) = prepared
    _shadow_headers_settings(monkeypatch, endpoint, tmp_path)
    second_admin_id = _second_admin(org_id, slug=slug)
    requested = _request_attestation(claim_id, document_id, admin_headers)
    assert requested.status_code == 201, requested.text
    approved = _approve_attestation(
        claim_id,
        document_id,
        requested.json()["id"],
        _headers(second_admin_id),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    return (
        org_id,
        admin_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        admin_headers,
        requested.json()["id"],
    )


def _shadow(claim_id: UUID, document_id: UUID, attestation_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal",
        headers=headers,
        json={"reason": "Materialize and verify the approved candidate only in isolated shadow storage."},
    )


def test_shadow_promotion_is_verified_idempotent_and_non_authoritative(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            manager_id,
            claim_id,
            document_id,
            storage_key,
            local_path,
            replicated,
            admin_headers,
            attestation_id,
        ) = _approve_ready_attestation(monkeypatch, tmp_path, endpoint, slug="shadow-happy")
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        remote_before = _RecoveryRestoreS3Handler.objects[remote_key]

        first = _shadow(claim_id, document_id, attestation_id, admin_headers)
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["created"] is True
        assert "shadow_storage_key" not in body["rehearsal"]
        shadow_id = body["rehearsal"]["id"]

        with TestingSessionLocal() as db:
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            rehearsal = db.query(EvidenceRecoveryRestoreRehearsal).one()
            document = db.get(Document, document_id)
            assert shadow is not None
            assert document is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
            shadow_path = tmp_path / shadow.shadow_storage_key
            assert shadow_path.read_bytes() == local_path.read_bytes()
            assert (tmp_path / rehearsal.staging_storage_key).exists()
            assert db.query(EvidenceRecoveryShadowPromotion).count() == 1
            assert db.query(EvidenceRecoveryShadowVerification).count() == 1
            audits = db.query(AuditLog).filter(
                AuditLog.action == "EVIDENCE_RECOVERY_SHADOW_PROMOTION_CREATED"
            ).all()
            assert audits
            rendered = str(audits[-1].new_values)
            assert storage_key not in rendered
            assert rehearsal.staging_storage_key not in rendered
            assert shadow.shadow_storage_key not in rendered
            assert audits[-1].new_values["cutover_performed"] is False
            assert audits[-1].new_values["authoritative_storage_changed"] is False

        second = _shadow(claim_id, document_id, attestation_id, admin_headers)
        assert second.status_code == 201, second.text
        assert second.json()["created"] is False
        assert second.json()["rehearsal"]["id"] == shadow_id
        assert second.json()["verification"]["id"] != body["verification"]["id"]

        manager_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal",
            headers=_headers(manager_id),
        )
        assert manager_read.status_code == 200
        verifications = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal/verifications",
            headers=_headers(manager_id),
        )
        assert verifications.status_code == 200
        assert len(verifications.json()) == 2
        assert local_path.exists()
        assert _RecoveryRestoreS3Handler.objects[remote_key] == remote_before


def test_shadow_promotion_requires_approved_unexpired_attestation(monkeypatch, tmp_path: Path) -> None:
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
        ) = _prepare_recovery(monkeypatch, tmp_path, slug="shadow-attestation-gate")
        _shadow_headers_settings(monkeypatch, endpoint, tmp_path)
        requested = _request_attestation(claim_id, document_id, admin_headers)
        assert requested.status_code == 201, requested.text
        blocked = _shadow(claim_id, document_id, requested.json()["id"], admin_headers)
        assert blocked.status_code == 409

        second_admin_id = _second_admin(org_id, slug="shadow-attestation-gate")
        approved = _approve_attestation(
            claim_id,
            document_id,
            requested.json()["id"],
            _headers(second_admin_id),
        )
        assert approved.status_code == 200
        with TestingSessionLocal() as db:
            attestation = db.get(EvidenceRecoveryPromotionAttestation, UUID(requested.json()["id"]))
            assert attestation is not None
            attestation.attestation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired = _shadow(claim_id, document_id, requested.json()["id"], admin_headers)
        assert expired.status_code == 409
        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key
            assert db.query(EvidenceRecoveryShadowPromotion).count() == 0


def test_new_restore_verification_after_approval_blocks_shadow_promotion(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _manager_id,
            claim_id,
            document_id,
            storage_key,
            _local_path,
            _replicated,
            admin_headers,
            attestation_id,
        ) = _approve_ready_attestation(monkeypatch, tmp_path, endpoint, slug="shadow-lineage-drift")
        reverified = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-restore-rehearsal/verify",
            headers=admin_headers,
            json={"reason": "Create a newer restore verification after cutover attestation approval."},
        )
        assert reverified.status_code == 200, reverified.text
        blocked = _shadow(claim_id, document_id, attestation_id, admin_headers)
        assert blocked.status_code == 409
        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key
            assert db.query(EvidenceRecoveryShadowPromotion).count() == 0


def test_unknown_preexisting_shadow_target_is_not_adopted_or_overwritten(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            org_id,
            _admin_id,
            _manager_id,
            claim_id,
            document_id,
            storage_key,
            _local_path,
            _replicated,
            admin_headers,
            attestation_id,
        ) = _approve_ready_attestation(monkeypatch, tmp_path, endpoint, slug="shadow-preexisting")
        shadow_key = (
            f"recovery-shadow-promotion/{org_id}/{claim_id}/{document_id}/{attestation_id}.candidate"
        )
        shadow_path = tmp_path / shadow_key
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        unknown_payload = b"preexisting ungoverned shadow artifact"
        shadow_path.write_bytes(unknown_payload)

        blocked = _shadow(claim_id, document_id, attestation_id, admin_headers)
        assert blocked.status_code == 409
        assert shadow_path.read_bytes() == unknown_payload
        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key
            assert db.query(EvidenceRecoveryShadowPromotion).count() == 0


def test_shadow_tamper_fails_reverification_without_authority_change(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _manager_id,
            claim_id,
            document_id,
            storage_key,
            _local_path,
            _replicated,
            admin_headers,
            attestation_id,
        ) = _approve_ready_attestation(monkeypatch, tmp_path, endpoint, slug="shadow-tamper")
        created = _shadow(claim_id, document_id, attestation_id, admin_headers)
        assert created.status_code == 201, created.text
        with TestingSessionLocal() as db:
            shadow = db.query(EvidenceRecoveryShadowPromotion).one()
            shadow_path = tmp_path / shadow.shadow_storage_key
        shadow_path.write_bytes(b"tampered shadow bytes")

        verification = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal/verify",
            headers=admin_headers,
            json={"reason": "Detect tampered shadow candidate before any authority transition."},
        )
        assert verification.status_code == 409
        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None


def test_shadow_promotion_rbac_cross_tenant_and_mfa(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            org_a,
            admin_a,
            manager_a,
            claim_a,
            document_a,
            _key_a,
            _path_a,
            _replicated,
            admin_headers,
            attestation_id,
        ) = _approve_ready_attestation(monkeypatch, tmp_path / "a", endpoint, slug="shadow-tenant-a")
        _org_b, _admin_b, manager_b, _claim_b, _document_b, _key_b, _path_b = _seed_tenant(
            slug="shadow-tenant-b",
            storage_root=tmp_path / "b",
        )

        manager_mutation = _shadow(claim_a, document_a, attestation_id, _headers(manager_a))
        assert manager_mutation.status_code == 403
        created = _shadow(claim_a, document_a, attestation_id, admin_headers)
        assert created.status_code == 201, created.text

        cross_tenant = client.get(
            f"/api/v1/claims/{claim_a}/documents/{document_a}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal",
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
            f"/api/v1/claims/{claim_a}/documents/{document_a}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal/verify",
            headers=_headers(admin_a),
            json={"reason": "Tenant MFA policy must gate shadow promotion verification."},
        )
        assert blocked.status_code == 403
