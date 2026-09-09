import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest
from app.modules.claims.retention_disposal_quarantine_models import DisposalQuarantineStage
from app.modules.claims.retention_disposal_quarantine_service import (
    revalidate_disposal_quarantine_stage,
)
from app.modules.claims.retention_service import create_retention_policy
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_tenant(
    *,
    slug: str,
    claim_age_days: int = 120,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Quarantine {slug}", slug=slug)
        db.add(org)
        db.flush()
        requester = User(
            organization_id=org.id,
            email=f"requester-{slug}@example.com",
            full_name=f"Requester {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        approver = User(
            organization_id=org.id,
            email=f"approver-{slug}@example.com",
            full_name=f"Approver {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        manager = User(
            organization_id=org.id,
            email=f"manager-{slug}@example.com",
            full_name=f"Manager {slug}",
            password_hash="local",
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        vessel = Vessel(organization_id=org.id, name=f"MT {slug.upper()}")
        db.add_all([requester, approver, manager, vessel])
        db.flush()
        anchor = datetime.now(timezone.utc) - timedelta(days=claim_age_days)
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=manager.id,
            claim_reference=f"QUAR-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Closed claim for logical quarantine governance tests.",
            currency="USD",
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(claim)
        db.flush()
        create_retention_policy(
            db,
            organization_id=org.id,
            closed_claim_retention_days=30,
            evidence_retention_days=30,
            enabled=True,
            disposal_enabled=True,
            created_by_id=requester.id,
        )
        db.commit()
        return org.id, requester.id, approver.id, manager.id, claim.id


def _headers(user_id: UUID) -> dict[str, str]:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        session = create_auth_session(db, user=user)
        db.commit()
        token = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
            session_id=session.id,
            identity_source=session.identity_source,
            auth_method=session.auth_method,
        )
    return {"Authorization": f"Bearer {token}"}


def _add_document(
    *,
    organization_id: UUID,
    claim_id: UUID,
    uploaded_by_id: UUID,
    storage_key: str,
    age_days: int = 90,
    file_hash: str = "c" * 64,
) -> UUID:
    with TestingSessionLocal() as db:
        anchor = datetime.now(timezone.utc) - timedelta(days=age_days)
        document = Document(
            organization_id=organization_id,
            claim_id=claim_id,
            uploaded_by_id=uploaded_by_id,
            filename="survey.pdf",
            original_filename="survey.pdf",
            mime_type="application/pdf",
            file_size_bytes=8192,
            file_hash=file_hash,
            storage_key=storage_key,
            processing_status=DocumentProcessingStatus.PROCESSED,
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(document)
        db.commit()
        return document.id


def _manifest_and_ceremony(
    claim_id: UUID,
    requester_id: UUID,
    approver_id: UUID,
    *,
    attest: bool = True,
) -> tuple[str, str, dict[str, str], dict[str, str]]:
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations",
        headers=requester_headers,
        json={"reason": "Retention window expired and requires governed disposal review."},
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/approve",
        headers=approver_headers,
        json={"reason": "Independent Admin confirms the exact retention snapshot."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    manifest = client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/execution-manifest",
        headers=approver_headers,
    )
    assert manifest.status_code == 201, manifest.text
    manifest_id = manifest.json()["id"]
    ceremony = client.post(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}/dry-run-ceremony",
        headers=requester_headers,
        json={"reason": "Open a non-destructive rehearsal before logical quarantine staging."},
    )
    assert ceremony.status_code == 201, ceremony.text
    ceremony_id = ceremony.json()["id"]
    if attest:
        attested = client.post(
            f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/attest",
            headers=approver_headers,
            json={"reason": "Independent Admin attests the exact non-destructive rehearsal."},
        )
        assert attested.status_code == 200, attested.text
        assert attested.json()["status"] == "attested"
    return manifest_id, ceremony_id, requester_headers, approver_headers


def _create_stage(
    claim_id: UUID,
    ceremony_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/quarantine-stage",
        headers=headers,
        json={"reason": "Create a reversible logical quarantine overlay for governed review."},
    )


def test_stage_and_restore_are_logical_only_and_preserve_source_content() -> None:
    org_id, requester_id, approver_id, manager_id, claim_id = _seed_tenant(slug="restore")
    raw_storage_key = f"private-bucket/{org_id}/{claim_id}/survey.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=raw_storage_key,
    )
    _manifest_id, ceremony_id, requester_headers, approver_headers = _manifest_and_ceremony(
        claim_id, requester_id, approver_id
    )

    created = _create_stage(claim_id, ceremony_id, approver_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "staged"
    assert body["document_count"] == 1
    assert body["total_file_size_bytes"] == 8192
    assert len(body["overlay_hash"]) == 64
    assert len(body["stage_hash"]) == 64
    assert body["restored_by_id"] is None

    rendered_overlay = json.dumps(body["overlay_plan"], sort_keys=True)
    assert raw_storage_key not in rendered_overlay
    assert "private-bucket" not in rendered_overlay
    assert "storage_key_fingerprint" in rendered_overlay
    assert "logical_quarantine_overlay" in rendered_overlay
    assert "governance_quarantine_marker_only" in rendered_overlay
    assert '"physical_mutation_performed": false' in rendered_overlay.lower()

    manager_list = client.get(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages",
        headers=_headers(manager_id),
    )
    assert manager_list.status_code == 200
    assert manager_list.json()[0]["id"] == body["id"]

    restored = client.post(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages/{body['id']}/restore",
        headers=requester_headers,
        json={"reason": "Preservation-first review requests immediate logical restoration."},
    )
    assert restored.status_code == 200, restored.text
    restored_body = restored.json()
    assert restored_body["status"] == "restored"
    assert restored_body["restored_by_id"] == str(requester_id)

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        stage = db.get(DisposalQuarantineStage, UUID(body["id"]))
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == raw_storage_key
        assert stage is not None and stage.status == "restored"
        audit_text = json.dumps(
            [
                row.new_values
                for row in db.query(AuditLog)
                .filter(AuditLog.organization_id == org_id)
                .all()
            ],
            sort_keys=True,
        ).lower()
        assert raw_storage_key.lower() not in audit_text
        assert '"logical_overlay_only": true' in audit_text
        assert '"physical_quarantine_performed": false' in audit_text
        assert '"destructive_action_performed": false' in audit_text


def test_stage_requires_attested_live_ceremony() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="pending")
    _manifest_id, ceremony_id, _requester_headers, approver_headers = _manifest_and_ceremony(
        claim_id, requester_id, approver_id, attest=False
    )

    blocked = _create_stage(claim_id, ceremony_id, approver_headers)
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "disposal_quarantine_preflight_failed"
    assert "dry_run_ceremony_status_pending_attestation" in detail["blocking_reasons"]


def test_new_legal_hold_after_attestation_blocks_stage_and_preserves_manifest_state() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="hold")
    manifest_id, ceremony_id, requester_headers, approver_headers = _manifest_and_ceremony(
        claim_id, requester_id, approver_id
    )
    hold = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds",
        headers=requester_headers,
        json={
            "source": "litigation",
            "reason": "Counsel issued a preservation instruction before quarantine staging.",
        },
    )
    assert hold.status_code == 201

    blocked = _create_stage(claim_id, ceremony_id, approver_headers)
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["outcome"] == "blocked"
    assert any("active_legal_hold" in reason for reason in detail["blocking_reasons"])

    with TestingSessionLocal() as db:
        manifest = db.get(DisposalExecutionManifest, UUID(manifest_id))
        assert manifest is not None and manifest.status == "blocked"
        assert db.query(DisposalQuarantineStage).filter(
            DisposalQuarantineStage.claim_id == claim_id
        ).count() == 0


def test_evidence_drift_after_stage_invalidates_overlay_without_mutation() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="drift")
    original_key = f"bucket/{org_id}/{claim_id}/original.pdf"
    original_document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=original_key,
    )
    _manifest_id, ceremony_id, _requester_headers, approver_headers = _manifest_and_ceremony(
        claim_id, requester_id, approver_id
    )
    created = _create_stage(claim_id, ceremony_id, approver_headers)
    assert created.status_code == 201
    stage_id = created.json()["id"]

    new_key = f"bucket/{org_id}/{claim_id}/new-evidence.pdf"
    new_document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=new_key,
        age_days=90,
        file_hash="d" * 64,
    )

    revalidated = client.post(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages/{stage_id}/revalidate",
        headers=approver_headers,
    )
    assert revalidated.status_code == 200, revalidated.text
    assert revalidated.json()["status"] == "invalidated"

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        original_document = db.get(Document, original_document_id)
        new_document = db.get(Document, new_document_id)
        assert claim is not None and claim.deleted_at is None
        assert original_document is not None and original_document.deleted_at is None
        assert new_document is not None and new_document.deleted_at is None
        assert original_document.storage_key == original_key
        assert new_document.storage_key == new_key


def test_stage_expiry_is_fail_closed_and_source_content_remains_intact() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="expiry")
    raw_key = f"bucket/{org_id}/{claim_id}/survey.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=raw_key,
    )
    _manifest_id, ceremony_id, _requester_headers, approver_headers = _manifest_and_ceremony(
        claim_id, requester_id, approver_id
    )
    created = _create_stage(claim_id, ceremony_id, approver_headers)
    assert created.status_code == 201
    stage_id = UUID(created.json()["id"])

    with TestingSessionLocal() as db:
        stage = db.get(DisposalQuarantineStage, stage_id)
        assert stage is not None
        expiry = stage.stage_expires_at

    with TestingSessionLocal() as db:
        stage, outcome = revalidate_disposal_quarantine_stage(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            stage_id=stage_id,
            actor_id=approver_id,
            now=expiry + timedelta(seconds=1),
        )
        db.commit()
        assert outcome == "expired"
        assert stage.status == "expired"

        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == raw_key


def test_cancel_is_reversible_metadata_only() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="cancel")
    raw_key = f"bucket/{org_id}/{claim_id}/survey.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=raw_key,
    )
    _manifest_id, ceremony_id, requester_headers, approver_headers = _manifest_and_ceremony(
        claim_id, requester_id, approver_id
    )
    created = _create_stage(claim_id, ceremony_id, approver_headers)
    assert created.status_code == 201

    cancelled = client.post(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages/{created.json()['id']}/cancel",
        headers=requester_headers,
        json={"reason": "Governance review cancels the logical quarantine overlay."},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == raw_key


def test_reader_rbac_cross_tenant_and_mfa_fail_closed() -> None:
    org_id, requester_id, approver_id, manager_id, claim_id = _seed_tenant(slug="rbac")
    _other_org, other_admin_id, _other_approver, _other_manager, _other_claim = _seed_tenant(
        slug="other"
    )
    _manifest_id, ceremony_id, _requester_headers, approver_headers = _manifest_and_ceremony(
        claim_id, requester_id, approver_id
    )
    created = _create_stage(claim_id, ceremony_id, approver_headers)
    assert created.status_code == 201
    stage_id = created.json()["id"]

    manager_headers = _headers(manager_id)
    manager_get = client.get(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages/{stage_id}",
        headers=manager_headers,
    )
    assert manager_get.status_code == 200
    manager_mutation = client.post(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages/{stage_id}/revalidate",
        headers=manager_headers,
    )
    assert manager_mutation.status_code == 403

    cross_tenant = client.get(
        f"/api/v1/claims/{claim_id}/disposal-quarantine-stages/{stage_id}",
        headers=_headers(other_admin_id),
    )
    assert cross_tenant.status_code == 404

    org2, requester2, approver2, _manager2, claim2 = _seed_tenant(slug="mfa")
    _manifest2, ceremony2, _requester2_headers, approver2_headers = _manifest_and_ceremony(
        claim2, requester2, approver2
    )
    with TestingSessionLocal() as db:
        db.add(
            MfaPolicy(
                organization_id=org2,
                is_enabled=True,
                required_roles=[UserRole.ADMIN.value],
                updated_by_id=requester2,
            )
        )
        db.commit()

    blocked_mfa = _create_stage(claim2, ceremony2, approver2_headers)
    assert blocked_mfa.status_code == 403
    assert blocked_mfa.json()["detail"]["code"] == "mfa_enrollment_required"
