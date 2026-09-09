import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.legal_hold_proposals import ingest_legal_hold_proposal
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_models import ClaimLegalHold, LegalHoldProposal
from app.modules.claims.retention_service import create_retention_policy
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_tenant(*, slug: str, claim_age_days: int = 120) -> tuple[UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Proposal {slug}", slug=slug)
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email=f"admin-{slug}@example.com",
            full_name=f"Admin {slug}",
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
        db.add_all([admin, manager, vessel])
        db.flush()
        anchor = datetime.now(timezone.utc) - timedelta(days=claim_age_days)
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=manager.id,
            claim_reference=f"HOLD-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Closed claim used for legal-hold proposal governance tests.",
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
            created_by_id=admin.id,
        )
        db.commit()
        return org.id, admin.id, manager.id, claim.id


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


def _proposal(
    *,
    organization_id: UUID,
    claim_id: UUID,
    source_reference: str = "outside-counsel-notice-001",
    payload: dict | None = None,
    source_kind: str = "external_notice",
    hold_source: str = "litigation",
) -> UUID:
    with TestingSessionLocal() as db:
        proposal, _created = ingest_legal_hold_proposal(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            source_kind=source_kind,
            source_reference=source_reference,
            source_payload=payload or {"notice": "preserve records", "matter": "alpha"},
            recommended_hold_source=hold_source,
            reason="Outside counsel notice requires preservation review.",
        )
        db.commit()
        return proposal.id


def test_signal_ingestion_is_idempotent_non_authorizing_and_does_not_store_raw_transport() -> None:
    org_id, _admin_id, _manager_id, claim_id = _seed_tenant(slug="idempotent")
    source_ref = "counsel@example.com/message/secret-991"
    payload = {"subject": "litigation hold", "private": "raw-secret-payload"}

    with TestingSessionLocal() as db:
        first, created = ingest_legal_hold_proposal(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            source_kind="webhook",
            source_reference=source_ref,
            source_payload=payload,
            recommended_hold_source="litigation",
            reason="Counsel preservation notice requires human activation review.",
        )
        assert created is True
        first_id = first.id
        db.commit()

    with TestingSessionLocal() as db:
        replay, created = ingest_legal_hold_proposal(
            db,
            organization_id=org_id,
            claim_id=claim_id,
            source_kind="webhook",
            source_reference=source_ref,
            source_payload=payload,
            recommended_hold_source="litigation",
            reason="Counsel preservation notice requires human activation review.",
        )
        assert created is False
        assert replay.id == first_id
        assert db.query(ClaimLegalHold).filter(ClaimLegalHold.claim_id == claim_id).count() == 0
        assert "source_reference" not in LegalHoldProposal.__table__.columns
        assert "source_payload" not in LegalHoldProposal.__table__.columns
        audit_text = json.dumps(
            [row.new_values for row in db.query(AuditLog).filter(AuditLog.organization_id == org_id).all()],
            sort_keys=True,
        )
        assert source_ref not in audit_text
        assert "raw-secret-payload" not in audit_text

        with pytest.raises(ValueError, match="different payload"):
            ingest_legal_hold_proposal(
                db,
                organization_id=org_id,
                claim_id=claim_id,
                source_kind="webhook",
                source_reference=source_ref,
                source_payload={"subject": "changed"},
                recommended_hold_source="litigation",
                reason="Counsel preservation notice requires human activation review.",
            )


def test_pending_proposal_blocks_disposal_until_final_rejection() -> None:
    org_id, admin_id, _manager_id, claim_id = _seed_tenant(slug="reject")
    headers = _headers(admin_id)

    baseline = client.get(f"/api/v1/claims/{claim_id}/disposal-eligibility", headers=headers)
    assert baseline.status_code == 200
    assert baseline.json()["eligible"] is True

    proposal_id = _proposal(organization_id=org_id, claim_id=claim_id)
    pending = client.get(f"/api/v1/claims/{claim_id}/disposal-eligibility", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["eligible"] is False
    assert pending.json()["pending_proposal_ids"] == [str(proposal_id)]
    assert "pending_legal_hold_proposal" in pending.json()["blocking_reasons"]

    rejected = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/reject",
        headers=headers,
        json={"reason": "Counsel confirmed that this notice does not apply to this claim."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    first_reason = rejected.json()["decision_reason"]

    replay = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/reject",
        headers=headers,
        json={"reason": "Replay must not rewrite the first decision."},
    )
    assert replay.status_code == 200
    assert replay.json()["decision_reason"] == first_reason

    eligible = client.get(f"/api/v1/claims/{claim_id}/disposal-eligibility", headers=headers)
    assert eligible.status_code == 200
    assert eligible.json()["eligible"] is True
    assert eligible.json()["pending_proposal_ids"] == []

    forbidden_activation = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/activate",
        headers=headers,
        json={"reason": "Rejected proposal must remain terminal."},
    )
    assert forbidden_activation.status_code == 409


def test_admin_activation_creates_exactly_one_hold_and_is_tenant_scoped() -> None:
    org_id, admin_id, manager_id, claim_id = _seed_tenant(slug="activate")
    _beta_org_id, beta_admin_id, _beta_manager_id, _beta_claim_id = _seed_tenant(slug="beta")
    admin_headers = _headers(admin_id)
    manager_headers = _headers(manager_id)
    beta_headers = _headers(beta_admin_id)
    proposal_id = _proposal(organization_id=org_id, claim_id=claim_id)

    manager_denied = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/activate",
        headers=manager_headers,
        json={"reason": "Manager must not activate formal preservation authority."},
    )
    assert manager_denied.status_code == 403

    cross_tenant = client.get(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}",
        headers=beta_headers,
    )
    assert cross_tenant.status_code == 404

    activated = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/activate",
        headers=admin_headers,
        json={"reason": "Admin reviewed the notice and confirms preservation is required."},
    )
    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert body["status"] == "activated"
    assert body["hold_id"] is not None
    hold_id = UUID(body["hold_id"])

    replay = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/activate",
        headers=admin_headers,
        json={"reason": "Replay must resolve to the existing linked hold."},
    )
    assert replay.status_code == 200
    assert replay.json()["hold_id"] == str(hold_id)

    with TestingSessionLocal() as db:
        holds = db.query(ClaimLegalHold).filter(ClaimLegalHold.claim_id == claim_id).all()
        assert len(holds) == 1
        assert holds[0].id == hold_id
        assert holds[0].source == "litigation"
        proposal = db.get(LegalHoldProposal, proposal_id)
        assert proposal is not None
        assert proposal.hold_id == hold_id

    preview = client.get(f"/api/v1/claims/{claim_id}/disposal-eligibility", headers=admin_headers)
    assert preview.status_code == 200
    assert preview.json()["eligible"] is False
    assert preview.json()["pending_proposal_ids"] == []
    assert preview.json()["active_hold_ids"] == [str(hold_id)]
    assert "active_legal_hold" in preview.json()["blocking_reasons"]

    reject_activated = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/reject",
        headers=admin_headers,
        json={"reason": "Activated proposal cannot be reversed by proposal rejection."},
    )
    assert reject_activated.status_code == 409


def test_tenant_mfa_policy_is_enforced_for_proposal_decisions() -> None:
    org_id, admin_id, _manager_id, claim_id = _seed_tenant(slug="mfa")
    proposal_id = _proposal(organization_id=org_id, claim_id=claim_id)
    headers = _headers(admin_id)

    with TestingSessionLocal() as db:
        db.add(
            MfaPolicy(
                organization_id=org_id,
                is_enabled=True,
                required_roles=[UserRole.ADMIN.value],
                updated_by_id=admin_id,
            )
        )
        db.commit()

    blocked = client.post(
        f"/api/v1/claims/{claim_id}/legal-hold-proposals/{proposal_id}/activate",
        headers=headers,
        json={"reason": "MFA-sensitive activation must fail without an enrolled factor."},
    )
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert detail["code"] == "mfa_enrollment_required"

    with TestingSessionLocal() as db:
        assert db.query(ClaimLegalHold).filter(ClaimLegalHold.claim_id == claim_id).count() == 0
        proposal = db.get(LegalHoldProposal, proposal_id)
        assert proposal is not None and proposal.status == "pending"
