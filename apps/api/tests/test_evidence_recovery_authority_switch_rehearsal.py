from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.documents.models import Document
from app.modules.documents.recovery_authority_switch_models import (
    EvidenceRecoveryAuthoritySwitchReceipt,
    EvidenceRecoveryAuthoritySwitchRehearsal,
)
from app.modules.documents.recovery_promotion_models import EvidenceRecoveryPromotionAttestation
from app.modules.documents.recovery_shadow_models import EvidenceRecoveryShadowPromotion
from app.modules.users.models import UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_promotion_attestation import _second_admin
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)
from tests.test_evidence_recovery_shadow_promotion import (
    _approve_ready_attestation,
    _shadow,
)


def setup_function() -> None:
    reset_database()


def _ready_shadow(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
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
        attestation_id,
    ) = _approve_ready_attestation(monkeypatch, tmp_path, endpoint, slug=slug)
    shadow_response = _shadow(claim_id, document_id, attestation_id, admin_headers)
    assert shadow_response.status_code == 201, shadow_response.text
    shadow_id = shadow_response.json()["rehearsal"]["id"]
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
        attestation_id,
        shadow_id,
    )


def _prepare_switch(claim_id: UUID, document_id: UUID, shadow_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-shadow-promotions/{shadow_id}/authority-switch-rehearsal",
        headers=headers,
        json={"reason": "Prepare a governed virtual authority transition with no production cutover."},
    )


def _activate_switch(claim_id: UUID, document_id: UUID, rehearsal_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/activate",
        headers=headers,
        json={"reason": "Independently approve the virtual candidate-authority activation rehearsal."},
    )


def _rollback_switch(claim_id: UUID, document_id: UUID, rehearsal_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/rollback",
        headers=headers,
        json={"reason": "Roll the virtual authority rehearsal back to the pinned authoritative source."},
    )


def test_authority_switch_prepare_activate_rollback_is_virtual_and_four_eyes(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        (
            org_id,
            _admin_id,
            manager_id,
            claim_id,
            document_id,
            storage_key,
            local_path,
            replicated,
            admin_headers,
            _attestation_id,
            shadow_id,
        ) = _ready_shadow(monkeypatch, tmp_path, endpoint, slug="authority-switch-happy")
        activation_admin_id = _second_admin(org_id, slug="authority-switch-activation")
        activation_headers = _headers(activation_admin_id)
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        remote_before = _RecoveryRestoreS3Handler.objects[remote_key]

        prepared = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
        assert prepared.status_code == 201, prepared.text
        prepared_body = prepared.json()
        assert prepared_body["outcome"] == "prepared"
        assert prepared_body["rehearsal"]["status"] == "prepared"
        assert prepared_body["rehearsal"]["virtual_authority_class"] == "authoritative_source"
        assert prepared_body["rehearsal"]["cutover_performed"] is False
        assert prepared_body["rehearsal"]["authoritative_storage_changed"] is False
        assert prepared_body["rehearsal"]["document_storage_key_mutated"] is False
        assert prepared_body["rehearsal"]["active_backend_changed"] is False
        rehearsal_id = prepared_body["rehearsal"]["id"]

        replay = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["rehearsal"]["id"] == rehearsal_id
        assert replay.json()["receipt"] is None

        same_admin = _activate_switch(claim_id, document_id, rehearsal_id, admin_headers)
        assert same_admin.status_code == 409

        activated = _activate_switch(claim_id, document_id, rehearsal_id, activation_headers)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        assert activated.json()["rehearsal"]["status"] == "activated"
        assert activated.json()["rehearsal"]["virtual_authority_class"] == "recovery_shadow_candidate"
        assert activated.json()["rehearsal"]["activated_by_id"] == str(activation_admin_id)
        assert activated.json()["rehearsal"]["cutover_performed"] is False

        manager_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}",
            headers=_headers(manager_id),
        )
        assert manager_read.status_code == 200
        assert manager_read.json()["status"] == "activated"

        rolled_back = _rollback_switch(claim_id, document_id, rehearsal_id, admin_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["rehearsal"]["status"] == "rolled_back"
        assert rolled_back.json()["rehearsal"]["virtual_authority_class"] == "authoritative_source"
        assert (
            rolled_back.json()["rehearsal"]["virtual_authority_fingerprint"]
            == rolled_back.json()["rehearsal"]["source_authority_fingerprint"]
        )

        receipts = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/receipts",
            headers=_headers(manager_id),
        )
        assert receipts.status_code == 200
        assert [item["phase"] for item in receipts.json()] == ["prepared", "activated", "rolled_back"]
        assert all(item["cutover_performed"] is False for item in receipts.json())
        assert all(item["authoritative_storage_changed"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            rehearsal = db.get(EvidenceRecoveryAuthoritySwitchRehearsal, UUID(rehearsal_id))
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            assert document is not None
            assert rehearsal is not None
            assert shadow is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
            assert local_path.exists()
            assert (tmp_path / shadow.shadow_storage_key).exists()
            assert db.query(EvidenceRecoveryAuthoritySwitchReceipt).count() == 3
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.action == "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_VIRTUALLY_ACTIVATED")
                .one()
            )
            rendered = str(audit.new_values)
            assert storage_key not in rendered
            assert shadow.shadow_storage_key not in rendered
            assert audit.new_values["cutover_performed"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            assert audit.new_values["document_storage_key_mutated"] is False
            assert audit.new_values["active_backend_changed"] is False

        assert _RecoveryRestoreS3Handler.objects[remote_key] == remote_before


def test_prepared_activation_lease_expiry_fails_closed(monkeypatch, tmp_path: Path) -> None:
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
            _attestation_id,
            shadow_id,
        ) = _ready_shadow(monkeypatch, tmp_path, endpoint, slug="authority-switch-expiry")
        activation_admin_id = _second_admin(org_id, slug="authority-switch-expiry-activation")
        prepared = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
        assert prepared.status_code == 201, prepared.text
        rehearsal_id = UUID(prepared.json()["rehearsal"]["id"])

        with TestingSessionLocal() as db:
            rehearsal = db.get(EvidenceRecoveryAuthoritySwitchRehearsal, rehearsal_id)
            assert rehearsal is not None
            rehearsal.activation_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        expired = _activate_switch(
            claim_id,
            document_id,
            str(rehearsal_id),
            _headers(activation_admin_id),
        )
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["rehearsal"]["status"] == "expired"
        assert expired.json()["rehearsal"]["virtual_authority_class"] == "authoritative_source"

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key


def test_shadow_tamper_invalidates_before_virtual_activation(monkeypatch, tmp_path: Path) -> None:
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
            _attestation_id,
            shadow_id,
        ) = _ready_shadow(monkeypatch, tmp_path, endpoint, slug="authority-switch-shadow-drift")
        activation_admin_id = _second_admin(org_id, slug="authority-switch-shadow-drift-activation")
        prepared = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
        assert prepared.status_code == 201
        rehearsal_id = prepared.json()["rehearsal"]["id"]

        with TestingSessionLocal() as db:
            shadow = db.get(EvidenceRecoveryShadowPromotion, UUID(shadow_id))
            assert shadow is not None
            shadow_path = tmp_path / shadow.shadow_storage_key
        shadow_path.write_bytes(b"tampered shadow after switch preparation")

        invalidated = _activate_switch(
            claim_id,
            document_id,
            rehearsal_id,
            _headers(activation_admin_id),
        )
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["rehearsal"]["status"] == "invalidated"
        assert invalidated.json()["rehearsal"]["virtual_authority_class"] == "authoritative_source"

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None


def test_new_shadow_verification_after_prepare_invalidates_activation(monkeypatch, tmp_path: Path) -> None:
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
            shadow_id,
        ) = _ready_shadow(monkeypatch, tmp_path, endpoint, slug="authority-switch-verification-drift")
        activation_admin_id = _second_admin(org_id, slug="authority-switch-verification-drift-activation")
        prepared = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
        assert prepared.status_code == 201
        rehearsal_id = prepared.json()["rehearsal"]["id"]
        pinned_shadow_verification_id = prepared.json()["rehearsal"]["shadow_verification_id"]

        reverified = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal/verify",
            headers=admin_headers,
            json={"reason": "Create a newer shadow verification after authority-switch preparation."},
        )
        assert reverified.status_code == 200, reverified.text
        assert reverified.json()["id"] != pinned_shadow_verification_id

        invalidated = _activate_switch(
            claim_id,
            document_id,
            rehearsal_id,
            _headers(activation_admin_id),
        )
        assert invalidated.status_code == 200
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["rehearsal"]["status"] == "invalidated"

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key


def test_rollback_remains_available_after_parent_attestation_time_window(monkeypatch, tmp_path: Path) -> None:
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
            shadow_id,
        ) = _ready_shadow(monkeypatch, tmp_path, endpoint, slug="authority-switch-late-rollback")
        activation_admin_id = _second_admin(org_id, slug="authority-switch-late-rollback-activation")
        prepared = _prepare_switch(claim_id, document_id, shadow_id, admin_headers)
        assert prepared.status_code == 201
        rehearsal_id = prepared.json()["rehearsal"]["id"]
        activated = _activate_switch(
            claim_id,
            document_id,
            rehearsal_id,
            _headers(activation_admin_id),
        )
        assert activated.status_code == 200
        assert activated.json()["rehearsal"]["status"] == "activated"

        with TestingSessionLocal() as db:
            attestation = db.get(EvidenceRecoveryPromotionAttestation, UUID(attestation_id))
            assert attestation is not None
            attestation.attestation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        rolled_back = _rollback_switch(claim_id, document_id, rehearsal_id, admin_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["rehearsal"]["status"] == "rolled_back"
        assert rolled_back.json()["rehearsal"]["virtual_authority_class"] == "authoritative_source"

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.storage_key == storage_key


def test_authority_switch_rbac_cross_tenant_and_mfa(monkeypatch, tmp_path: Path) -> None:
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
            _attestation_id,
            shadow_id,
        ) = _ready_shadow(monkeypatch, tmp_path / "a", endpoint, slug="authority-switch-tenant-a")
        _org_b, _admin_b, manager_b, _claim_b, _document_b, _key_b, _path_b = _seed_tenant(
            slug="authority-switch-tenant-b",
            storage_root=tmp_path / "b",
        )

        manager_prepare = _prepare_switch(claim_a, document_a, shadow_id, _headers(manager_a))
        assert manager_prepare.status_code == 403
        prepared = _prepare_switch(claim_a, document_a, shadow_id, admin_headers)
        assert prepared.status_code == 201, prepared.text
        rehearsal_id = prepared.json()["rehearsal"]["id"]

        cross_tenant = client.get(
            f"/api/v1/claims/{claim_a}/documents/{document_a}/recovery-authority-switch-rehearsals/{rehearsal_id}",
            headers=_headers(manager_b),
        )
        assert cross_tenant.status_code == 404

        activation_admin_id = _second_admin(org_a, slug="authority-switch-mfa-activation")
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

        blocked = _activate_switch(
            claim_a,
            document_a,
            rehearsal_id,
            _headers(activation_admin_id),
        )
        assert blocked.status_code == 403
