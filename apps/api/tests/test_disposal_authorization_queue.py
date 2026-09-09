from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.legal_hold_proposals import ingest_legal_hold_proposal
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_disposal_models import DisposalAuthorization
from app.modules.claims.retention_service import create_retention_policy
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_tenant(*, slug: str, claim_age_days: int = 120) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Disposal {slug}", slug=slug)
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
            claim_reference=f"DISP-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Closed claim for governed disposal authorization tests.",
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


def _request(claim_id: UUID, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations",
        headers=headers,
        json={"reason": "Retention window expired and records are eligible for governed review."},
    )


def _approve(claim_id: UUID, authorization_id: str, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": "Independent Admin review confirms the pinned eligibility state."},
    )


def _add_document(
    *,
    organization_id: UUID,
    claim_id: UUID,
    uploaded_by_id: UUID,
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
            file_size_bytes=1024,
            file_hash="a" * 64,
            storage_key=f"org/{organization_id}/claim/{claim_id}/survey.pdf",
            processing_status=DocumentProcessingStatus.PROCESSED,
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(document)
        db.commit()
        return document.id


def test_request_pins_snapshot_four_eyes_approval_is_non_destructive() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="approve")
    document_id = _add_document(
        organization_id=org_id,
        claim_id=claim_id,
        uploaded_by_id=requester_id,
        age_days=90,
    )
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)

    requested = _request(claim_id, requester_headers)
    assert requested.status_code == 201, requested.text
    body = requested.json()
    authorization_id = body["id"]
    assert body["status"] == "pending_second_approval"
    assert body["active_hold_ids"] == []
    assert body["pending_proposal_ids"] == []
    assert len(body["eligibility_snapshot_hash"]) == 64
    assert len(body["state_fingerprint"]) == 64
    assert body["retention_policy_number"] == 1
    assert body["claim_retention_anchor_at"] is not None
    assert body["evidence_retention_anchor_at"] is not None

    self_approval = _approve(claim_id, authorization_id, requester_headers)
    assert self_approval.status_code == 409
    assert "different Admin" in self_approval.json()["detail"]

    approved = _approve(claim_id, authorization_id, approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by_id"] == str(approver_id)

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        authorization = db.get(DisposalAuthorization, UUID(authorization_id))
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == f"org/{org_id}/claim/{claim_id}/survey.pdf"
        assert authorization is not None and authorization.status == "approved"


def test_active_hold_and_pending_proposal_block_new_authorization() -> None:
    org_id, requester_id, _approver_id, _manager_id, claim_id = _seed_tenant(slug="blockers")
    headers = _headers(requester_id)

    hold = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds",
        headers=headers,
        json={"source": "litigation", "reason": "Litigation preservation duty remains active."},
    )
    assert hold.status_code == 201, hold.text
    blocked_hold = _request(claim_id, headers)
    assert blocked_hold.status_code == 409
    assert "active_legal_hold" in blocked_hold.json()["detail"]["blocking_reasons"]

    released = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds/{hold.json()['id']}/release",
        headers=headers,
        json={"reason": "Counsel formally released the litigation preservation duty."},
    )
    assert released.status_code == 200

    with TestingSessionLocal() as db:
        ingest_legal_hold_proposal(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            source_kind="external_notice",
            source_reference="pending-proposal-blocker-001",
            source_payload={"matter": "preserve"},
            recommended_hold_source="investigation",
            reason="Investigation signal requires human preservation review.",
        )
        db.commit()

    blocked_proposal = _request(claim_id, headers)
    assert blocked_proposal.status_code == 409
    assert "pending_legal_hold_proposal" in blocked_proposal.json()["detail"]["blocking_reasons"]


def test_new_legal_hold_after_request_invalidates_second_approval() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="hold-drift")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = _request(claim_id, requester_headers)
    assert requested.status_code == 201

    hold = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds",
        headers=requester_headers,
        json={"source": "regulatory", "reason": "Regulator requested preservation after disposal review began."},
    )
    assert hold.status_code == 201

    decision = _approve(claim_id, requested.json()["id"], approver_headers)
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "invalidated"
    assert "active_legal_hold" in decision.json()["decision_reason"]


def test_pending_proposal_after_request_invalidates_second_approval() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="proposal-drift")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = _request(claim_id, requester_headers)
    assert requested.status_code == 201

    with TestingSessionLocal() as db:
        ingest_legal_hold_proposal(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            source_kind="rule",
            source_reference="proposal-after-request-001",
            source_payload={"preserve": True},
            recommended_hold_source="investigation",
            reason="New investigation preservation signal arrived after authorization request.",
        )
        db.commit()

    decision = _approve(claim_id, requested.json()["id"], approver_headers)
    assert decision.status_code == 200
    assert decision.json()["status"] == "invalidated"
    assert "pending_legal_hold_proposal" in decision.json()["decision_reason"]


def test_claim_and_evidence_drift_invalidate_stale_authorizations() -> None:
    org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="claim-drift")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = _request(claim_id, requester_headers)
    assert requested.status_code == 201

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        assert claim is not None
        claim.updated_at = datetime.now(timezone.utc)
        db.commit()

    invalidated = _approve(claim_id, requested.json()["id"], approver_headers)
    assert invalidated.status_code == 200
    assert invalidated.json()["status"] == "invalidated"

    org2, requester2, approver2, _manager2, claim2 = _seed_tenant(slug="evidence-drift")
    document_id = _add_document(
        organization_id=org2,
        claim_id=claim2,
        uploaded_by_id=requester2,
        age_days=90,
    )
    requester2_headers = _headers(requester2)
    approver2_headers = _headers(approver2)
    requested2 = _request(claim2, requester2_headers)
    assert requested2.status_code == 201

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        document.file_hash = "b" * 64
        document.updated_at = datetime.now(timezone.utc)
        db.commit()

    invalidated2 = _approve(claim2, requested2.json()["id"], approver2_headers)
    assert invalidated2.status_code == 200
    assert invalidated2.json()["status"] == "invalidated"


def test_policy_version_drift_invalidates_even_when_new_policy_is_eligible() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="policy-drift")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = _request(claim_id, requester_headers)
    assert requested.status_code == 201

    newer_policy = client.post(
        "/api/v1/claims/retention/policies",
        headers=requester_headers,
        json={
            "closed_claim_retention_days": 30,
            "evidence_retention_days": 30,
            "enabled": True,
            "disposal_enabled": True,
        },
    )
    assert newer_policy.status_code == 201, newer_policy.text
    assert newer_policy.json()["policy_number"] == 2

    decision = _approve(claim_id, requested.json()["id"], approver_headers)
    assert decision.status_code == 200
    assert decision.json()["status"] == "invalidated"
    assert "state changed" in decision.json()["decision_reason"]


def test_expiry_and_rejection_are_terminal_fail_closed_states() -> None:
    _org_id, requester_id, approver_id, _manager_id, claim_id = _seed_tenant(slug="expiry")
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = _request(claim_id, requester_headers)
    assert requested.status_code == 201

    with TestingSessionLocal() as db:
        authorization = db.get(DisposalAuthorization, UUID(requested.json()["id"]))
        assert authorization is not None
        authorization.authorization_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    expired = _approve(claim_id, requested.json()["id"], approver_headers)
    assert expired.status_code == 200
    assert expired.json()["status"] == "expired"

    _org2, requester2, approver2, _manager2, claim2 = _seed_tenant(slug="reject")
    requester2_headers = _headers(requester2)
    approver2_headers = _headers(approver2)
    requested2 = _request(claim2, requester2_headers)
    assert requested2.status_code == 201
    rejected = client.post(
        f"/api/v1/claims/{claim2}/disposal-authorizations/{requested2.json()['id']}/reject",
        headers=requester2_headers,
        json={"reason": "Records should be retained longer for internal governance review."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    later_approval = _approve(claim2, requested2.json()["id"], approver2_headers)
    assert later_approval.status_code == 409


def test_reader_rbac_tenant_isolation_and_mfa_fail_closed() -> None:
    org_id, requester_id, _approver_id, manager_id, claim_id = _seed_tenant(slug="rbac")
    _other_org, other_admin_id, _other_approver, _other_manager, _other_claim = _seed_tenant(
        slug="other"
    )
    requester_headers = _headers(requester_id)
    manager_headers = _headers(manager_id)
    other_headers = _headers(other_admin_id)

    requested = _request(claim_id, requester_headers)
    assert requested.status_code == 201
    authorization_id = requested.json()["id"]

    manager_list = client.get(
        f"/api/v1/claims/{claim_id}/disposal-authorizations",
        headers=manager_headers,
    )
    assert manager_list.status_code == 200
    assert manager_list.json()[0]["id"] == authorization_id
    manager_mutation = _request(claim_id, manager_headers)
    assert manager_mutation.status_code == 403

    cross_tenant = client.get(
        f"/api/v1/claims/{claim_id}/disposal-authorizations/{authorization_id}",
        headers=other_headers,
    )
    assert cross_tenant.status_code == 404

    org2, requester2, _approver2, _manager2, claim2 = _seed_tenant(slug="mfa")
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
    blocked = _request(claim2, _headers(requester2))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_enrollment_required"
