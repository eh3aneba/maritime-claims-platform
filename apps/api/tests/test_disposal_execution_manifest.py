import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.legal_hold_proposals import ingest_legal_hold_proposal
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest
from app.modules.claims.retention_disposal_manifest_service import (
    create_disposal_execution_manifest,
    revalidate_disposal_execution_manifest,
)
from app.modules.claims.retention_disposal_models import DisposalAuthorization
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
        org = Organization(name=f"Manifest {slug}", slug=slug)
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
            claim_reference=f"MAN-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Closed claim for disposal execution manifest tests.",
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


def _request_authorization(claim_id: UUID, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations",
        headers=headers,
        json={
            "reason": "Retention window expired and records are eligible for governed review."
        },
    )


def _approve_authorization(
    claim_id: UUID,
    authorization_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": "Independent Admin confirms the pinned retention and evidence state."},
    )


def _approved_authorization(
    claim_id: UUID,
    requester_id: UUID,
    approver_id: UUID,
) -> tuple[str, dict[str, str], dict[str, str]]:
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = _request_authorization(claim_id, requester_headers)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]
    approved = _approve_authorization(claim_id, authorization_id, approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    return authorization_id, requester_headers, approver_headers


def _create_manifest(
    claim_id: UUID,
    authorization_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/execution-manifest",
        headers=headers,
    )


def _add_document(
    *,
    organization_id: UUID,
    claim_id: UUID,
    uploaded_by_id: UUID,
    storage_key: str,
    age_days: int = 90,
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
            file_size_bytes=2048,
            file_hash="a" * 64,
            storage_key=storage_key,
            processing_status=DocumentProcessingStatus.PROCESSED,
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(document)
        db.commit()
        return document.id


def test_ready_manifest_pins_hashed_inventory_without_destructive_side_effects() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(
        slug="ready"
    )
    raw_storage_key = f"secret-bucket/{org_id}/{claim_id}/survey.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=raw_storage_key,
    )
    authorization_id, _requester_headers, approver_headers = _approved_authorization(
        claim_id, requester_id, approver_id
    )

    created = _create_manifest(claim_id, authorization_id, approver_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "ready"
    assert body["document_count"] == 1
    assert body["total_file_size_bytes"] == 2048
    assert len(body["authorization_lineage_hash"]) == 64
    assert len(body["inventory_hash"]) == 64
    assert len(body["manifest_hash"]) == 64
    assert body["active_hold_ids"] == []
    assert body["pending_proposal_ids"] == []

    rendered_inventory = json.dumps(body["inventory"], sort_keys=True)
    assert raw_storage_key not in rendered_inventory
    assert "storage_key_fingerprint" in rendered_inventory
    assert "secret-bucket" not in rendered_inventory

    claim_rows = [row for row in body["inventory"] if row["object_kind"] == "claim"]
    document_rows = [
        row for row in body["inventory"] if row["object_kind"] == "document"
    ]
    assert len(claim_rows) == 1
    assert len(document_rows) == 1
    assert document_rows[0]["object_id"] == str(document_id)
    assert document_rows[0]["file_hash"] == "a" * 64

    revalidated = client.post(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{body['id']}/revalidate",
        headers=approver_headers,
    )
    assert revalidated.status_code == 200, revalidated.text
    assert revalidated.json()["status"] == "ready"

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        manifest = db.get(DisposalExecutionManifest, UUID(body["id"]))
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == raw_storage_key
        assert manifest is not None and manifest.status == "ready"
        audit_text = json.dumps(
            [
                row.new_values
                for row in db.query(AuditLog)
                .filter(AuditLog.organization_id == org_id)
                .all()
            ],
            sort_keys=True,
        )
        assert raw_storage_key not in audit_text
        assert '"destructive_action_performed": false' in audit_text.lower()


def test_manifest_cannot_be_created_from_nonapproved_authorization_states() -> None:
    _org1, requester1, approver1, _manager1, claim1 = _seed_tenant(slug="pending")
    pending = _request_authorization(claim1, _headers(requester1))
    assert pending.status_code == 201
    denied_pending = _create_manifest(claim1, pending.json()["id"], _headers(approver1))
    assert denied_pending.status_code == 409
    assert "authorization_status_pending_second_approval" in denied_pending.text

    _org2, requester2, _approver2, _manager2, claim2 = _seed_tenant(slug="rejected")
    requester2_headers = _headers(requester2)
    requested2 = _request_authorization(claim2, requester2_headers)
    assert requested2.status_code == 201
    rejected = client.post(
        f"/api/v1/claims/{claim2}/disposal-authorizations/{requested2.json()['id']}/reject",
        headers=requester2_headers,
        json={"reason": "Internal governance review requires longer retention."},
    )
    assert rejected.status_code == 200
    denied_rejected = _create_manifest(
        claim2, requested2.json()["id"], requester2_headers
    )
    assert denied_rejected.status_code == 409
    assert "authorization_status_rejected" in denied_rejected.text

    _org3, requester3, approver3, _manager3, claim3 = _seed_tenant(slug="invalidated")
    requester3_headers = _headers(requester3)
    approver3_headers = _headers(approver3)
    requested3 = _request_authorization(claim3, requester3_headers)
    assert requested3.status_code == 201
    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim3)
        assert claim is not None
        claim.updated_at = datetime.now(timezone.utc)
        db.commit()
    invalidated = _approve_authorization(
        claim3, requested3.json()["id"], approver3_headers
    )
    assert invalidated.status_code == 200
    assert invalidated.json()["status"] == "invalidated"
    denied_invalidated = _create_manifest(
        claim3, requested3.json()["id"], approver3_headers
    )
    assert denied_invalidated.status_code == 409
    assert "authorization_status_invalidated" in denied_invalidated.text

    _org4, requester4, approver4, _manager4, claim4 = _seed_tenant(slug="expired")
    authorization4, _req4, approver4_headers = _approved_authorization(
        claim4, requester4, approver4
    )
    with TestingSessionLocal() as db:
        auth = db.get(DisposalAuthorization, UUID(authorization4))
        assert auth is not None
        auth.authorization_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    denied_expired = _create_manifest(claim4, authorization4, approver4_headers)
    assert denied_expired.status_code == 409
    assert denied_expired.json()["detail"]["outcome"] == "expired"


def test_preservation_signals_after_approval_block_manifest_creation() -> None:
    _org1, requester1, approver1, _manager1, claim1 = _seed_tenant(slug="hold")
    auth1, requester1_headers, approver1_headers = _approved_authorization(
        claim1, requester1, approver1
    )
    hold = client.post(
        f"/api/v1/claims/{claim1}/legal-holds",
        headers=requester1_headers,
        json={
            "source": "litigation",
            "reason": "Counsel issued a preservation instruction after approval.",
        },
    )
    assert hold.status_code == 201
    blocked_hold = _create_manifest(claim1, auth1, approver1_headers)
    assert blocked_hold.status_code == 409
    assert blocked_hold.json()["detail"]["outcome"] == "blocked"
    assert "active_legal_hold" in blocked_hold.json()["detail"]["blocking_reasons"]

    org2, requester2, approver2, _manager2, claim2 = _seed_tenant(slug="proposal")
    auth2, _requester2_headers, approver2_headers = _approved_authorization(
        claim2, requester2, approver2
    )
    with TestingSessionLocal() as db:
        ingest_legal_hold_proposal(
            db,
            organization_id=org2,
            claim_id=claim2,
            source_kind="external_notice",
            source_reference="manifest-proposal-001",
            source_payload={"preserve": True},
            recommended_hold_source="investigation",
            reason="Investigation preservation signal requires human review.",
        )
        db.commit()
    blocked_proposal = _create_manifest(claim2, auth2, approver2_headers)
    assert blocked_proposal.status_code == 409
    assert blocked_proposal.json()["detail"]["outcome"] == "blocked"
    assert (
        "pending_legal_hold_proposal"
        in blocked_proposal.json()["detail"]["blocking_reasons"]
    )


def test_storage_inventory_drift_invalidates_ready_manifest() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(
        slug="storage-drift"
    )
    original_key = f"bucket/{org_id}/{claim_id}/original.pdf"
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        storage_key=original_key,
    )
    authorization_id, _requester_headers, approver_headers = _approved_authorization(
        claim_id, requester_id, approver_id
    )
    created = _create_manifest(claim_id, authorization_id, approver_headers)
    assert created.status_code == 201
    manifest_id = created.json()["id"]

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        original_updated_at = document.updated_at
        document.storage_key = f"bucket/{org_id}/{claim_id}/moved.pdf"
        document.updated_at = original_updated_at
        db.commit()

    invalidated = client.post(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}/revalidate",
        headers=approver_headers,
    )
    assert invalidated.status_code == 200, invalidated.text
    assert invalidated.json()["status"] == "invalidated"
    terminal_reason = invalidated.json()["terminal_reason"].lower()
    assert (
        "inventory drift" in terminal_reason
        or "authorization_snapshot_drift" in terminal_reason
    )

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        claim = db.get(Claim, claim_id)
        assert document is not None and document.deleted_at is None
        assert claim is not None and claim.deleted_at is None


def test_new_legal_hold_blocks_ready_manifest_on_revalidation() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(
        slug="hold-after-manifest"
    )
    authorization_id, requester_headers, approver_headers = _approved_authorization(
        claim_id, requester_id, approver_id
    )
    created = _create_manifest(claim_id, authorization_id, approver_headers)
    assert created.status_code == 201

    hold = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds",
        headers=requester_headers,
        json={
            "source": "regulatory",
            "reason": "Regulator requested preservation before any destructive action.",
        },
    )
    assert hold.status_code == 201

    blocked = client.post(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{created.json()['id']}/revalidate",
        headers=approver_headers,
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert "active_legal_hold" in blocked.json()["terminal_reason"]


def test_manifest_expiry_is_fail_closed_without_execution() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(
        slug="manifest-expiry"
    )
    authorization_id, _requester_headers, _approver_headers = _approved_authorization(
        claim_id, requester_id, approver_id
    )
    with TestingSessionLocal() as db:
        manifest = create_disposal_execution_manifest(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            authorization_id=UUID(authorization_id),
            created_by_id=approver_id,
        )
        db.commit()
        manifest_id = manifest.id
        expiry = manifest.manifest_expires_at

    with TestingSessionLocal() as db:
        manifest, outcome = revalidate_disposal_execution_manifest(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            manifest_id=manifest_id,
            actor_id=approver_id,
            now=expiry + timedelta(seconds=1),
        )
        db.commit()
        assert outcome == "expired"
        assert manifest.status == "expired"

        claim = db.get(Claim, claim_id)
        assert claim is not None and claim.deleted_at is None
        assert db.query(Document).filter(Document.claim_id == claim_id).count() == 0


def test_reader_rbac_tenant_isolation_and_mfa_fail_closed() -> None:
    _org_id, requester_id, approver_id, manager_id, claim_id = _seed_tenant(
        slug="rbac-mfa"
    )
    _other_org, other_admin_id, _other_approver, _other_manager, _other_claim = (
        _seed_tenant(slug="other-tenant")
    )
    authorization_id, _requester_headers, approver_headers = _approved_authorization(
        claim_id, requester_id, approver_id
    )
    created = _create_manifest(claim_id, authorization_id, approver_headers)
    assert created.status_code == 201
    manifest_id = created.json()["id"]

    manager_headers = _headers(manager_id)
    manager_list = client.get(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests",
        headers=manager_headers,
    )
    assert manager_list.status_code == 200
    assert manager_list.json()[0]["id"] == manifest_id

    manager_mutation = client.post(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}/revalidate",
        headers=manager_headers,
    )
    assert manager_mutation.status_code == 403

    cross_tenant = client.get(
        f"/api/v1/claims/{claim_id}/disposal-execution-manifests/{manifest_id}",
        headers=_headers(other_admin_id),
    )
    assert cross_tenant.status_code == 404

    org2, requester2, approver2, _manager2, claim2 = _seed_tenant(slug="mfa-only")
    authorization2, _requester2_headers, approver2_headers = _approved_authorization(
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

    blocked_mfa = _create_manifest(claim2, authorization2, approver2_headers)
    assert blocked_mfa.status_code == 403
    detail = blocked_mfa.json()["detail"]
    assert detail["code"] == "mfa_enrollment_required"
