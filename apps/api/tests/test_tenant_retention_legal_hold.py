from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_models import ClaimLegalHold, TenantRetentionPolicy
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
    role: UserRole = UserRole.ADMIN,
    claim_status: ClaimStatus = ClaimStatus.CLOSED,
    claim_age_days: int = 90,
) -> tuple[UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Retention {slug}", slug=slug)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email=f"{slug}@example.com",
            full_name=f"Retention {slug}",
            password_hash="local",
            role=role,
            is_active=True,
        )
        vessel = Vessel(
            organization_id=org.id,
            name=f"MT {slug.upper()}",
            imo_number=f"8{abs(hash(slug)) % 1000000:06d}",
        )
        db.add_all([user, vessel])
        db.flush()
        anchor = datetime.now(timezone.utc) - timedelta(days=claim_age_days)
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=user.id,
            claim_reference=f"RET-{slug.upper()}-001",
            status=claim_status,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Retention governance test claim",
            currency="USD",
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(claim)
        db.commit()
        return org.id, user.id, claim.id


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


def _create_policy(
    headers: dict[str, str],
    *,
    claim_days: int = 30,
    evidence_days: int = 30,
    enabled: bool = True,
    disposal_enabled: bool = True,
):
    return client.post(
        "/api/v1/claims/retention/policies",
        headers=headers,
        json={
            "closed_claim_retention_days": claim_days,
            "evidence_retention_days": evidence_days,
            "enabled": enabled,
            "disposal_enabled": disposal_enabled,
        },
    )


def test_preview_fails_closed_without_policy_and_for_nonfinal_claim() -> None:
    _, admin_id, closed_claim_id = _seed_tenant(slug="missing-policy")
    headers = _headers(admin_id)

    missing = client.get(
        f"/api/v1/claims/{closed_claim_id}/disposal-eligibility",
        headers=headers,
    )
    assert missing.status_code == 200, missing.text
    assert missing.json()["eligible"] is False
    assert "retention_policy_missing" in missing.json()["blocking_reasons"]

    _, open_admin_id, open_claim_id = _seed_tenant(
        slug="open-claim",
        claim_status=ClaimStatus.INVESTIGATION,
    )
    open_headers = _headers(open_admin_id)
    policy = _create_policy(open_headers)
    assert policy.status_code == 201, policy.text
    preview = client.get(
        f"/api/v1/claims/{open_claim_id}/disposal-eligibility",
        headers=open_headers,
    )
    assert preview.status_code == 200
    assert preview.json()["eligible"] is False
    assert "claim_not_final" in preview.json()["blocking_reasons"]


def test_policy_is_versioned_and_latest_disabled_version_fails_closed() -> None:
    org_id, admin_id, claim_id = _seed_tenant(slug="versioned")
    headers = _headers(admin_id)

    first = _create_policy(headers, claim_days=30, evidence_days=45)
    assert first.status_code == 201, first.text
    second = _create_policy(
        headers,
        claim_days=60,
        evidence_days=60,
        enabled=False,
        disposal_enabled=False,
    )
    assert second.status_code == 201, second.text
    assert second.json()["policy_number"] == 2
    assert second.json()["previous_policy_hash"] == first.json()["policy_hash"]

    current = client.get("/api/v1/claims/retention/policy", headers=headers)
    assert current.status_code == 404
    history = client.get("/api/v1/claims/retention/policies", headers=headers)
    assert history.status_code == 200
    assert [item["policy_number"] for item in history.json()] == [2, 1]

    preview = client.get(
        f"/api/v1/claims/{claim_id}/disposal-eligibility",
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["eligible"] is False
    assert "retention_policy_disabled" in preview.json()["blocking_reasons"]

    with TestingSessionLocal() as db:
        policies = (
            db.query(TenantRetentionPolicy)
            .filter(TenantRetentionPolicy.organization_id == org_id)
            .order_by(TenantRetentionPolicy.policy_number)
            .all()
        )
        assert len(policies) == 2
        assert policies[0].policy_hash != policies[1].policy_hash


def test_active_hold_overrides_expired_retention_and_release_is_auditable() -> None:
    org_id, admin_id, claim_id = _seed_tenant(slug="hold-precedence", claim_age_days=120)
    headers = _headers(admin_id)
    policy = _create_policy(headers, claim_days=30, evidence_days=30)
    assert policy.status_code == 201, policy.text

    before_hold = client.get(
        f"/api/v1/claims/{claim_id}/disposal-eligibility",
        headers=headers,
    )
    assert before_hold.status_code == 200
    assert before_hold.json()["eligible"] is True

    hold = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds",
        headers=headers,
        json={"source": "litigation", "reason": "Pending litigation preservation duty"},
    )
    assert hold.status_code == 201, hold.text
    hold_id = hold.json()["id"]
    assert hold.json()["is_active"] is True

    blocked = client.get(
        f"/api/v1/claims/{claim_id}/disposal-eligibility",
        headers=headers,
    )
    assert blocked.status_code == 200
    assert blocked.json()["eligible"] is False
    assert blocked.json()["active_hold_ids"] == [hold_id]
    assert "active_legal_hold" in blocked.json()["blocking_reasons"]

    released = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds/{hold_id}/release",
        headers=headers,
        json={"reason": "Written release confirmed by claims counsel"},
    )
    assert released.status_code == 200, released.text
    assert released.json()["is_active"] is False
    assert released.json()["released_at"] is not None

    eligible_again = client.get(
        f"/api/v1/claims/{claim_id}/disposal-eligibility",
        headers=headers,
    )
    assert eligible_again.status_code == 200
    assert eligible_again.json()["eligible"] is True

    replay_release = client.post(
        f"/api/v1/claims/{claim_id}/legal-holds/{hold_id}/release",
        headers=headers,
        json={"reason": "Replay should not rewrite release history"},
    )
    assert replay_release.status_code == 200
    assert replay_release.json()["release_reason"] == "Written release confirmed by claims counsel"

    with TestingSessionLocal() as db:
        hold_row = db.get(ClaimLegalHold, UUID(hold_id))
        assert hold_row is not None
        assert hold_row.organization_id == org_id
        assert hold_row.released_at is not None


def test_evidence_age_extends_window_and_preview_has_no_destructive_side_effects() -> None:
    org_id, admin_id, claim_id = _seed_tenant(slug="evidence-window", claim_age_days=120)
    headers = _headers(admin_id)
    assert _create_policy(headers, claim_days=30, evidence_days=60).status_code == 201

    with TestingSessionLocal() as db:
        recent = datetime.now(timezone.utc) - timedelta(days=10)
        document = Document(
            organization_id=org_id,
            claim_id=claim_id,
            uploaded_by_id=admin_id,
            filename="survey.pdf",
            original_filename="survey.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            file_hash="a" * 64,
            storage_key="org/evidence/survey.pdf",
            processing_status=DocumentProcessingStatus.PROCESSED,
            created_at=recent,
            updated_at=recent,
        )
        db.add(document)
        db.commit()
        document_id = document.id

    preview = client.get(
        f"/api/v1/claims/{claim_id}/disposal-eligibility",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["eligible"] is False
    assert "retention_window_active" in preview.json()["blocking_reasons"]

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        assert claim is not None and claim.deleted_at is None
        assert document is not None and document.deleted_at is None
        assert document.storage_key == "org/evidence/survey.pdf"


def test_tenant_isolation_and_admin_only_mutations() -> None:
    _, alpha_admin_id, alpha_claim_id = _seed_tenant(slug="tenant-alpha")
    _, beta_admin_id, _ = _seed_tenant(slug="tenant-beta")
    _, manager_id, _ = _seed_tenant(slug="manager-only", role=UserRole.CLAIMS_MANAGER)

    alpha_headers = _headers(alpha_admin_id)
    beta_headers = _headers(beta_admin_id)
    manager_headers = _headers(manager_id)

    assert _create_policy(alpha_headers).status_code == 201
    denied_manager = _create_policy(manager_headers)
    assert denied_manager.status_code == 403

    cross_hold = client.post(
        f"/api/v1/claims/{alpha_claim_id}/legal-holds",
        headers=beta_headers,
        json={"source": "manual", "reason": "Cross tenant attempt"},
    )
    assert cross_hold.status_code == 404

    cross_preview = client.get(
        f"/api/v1/claims/{alpha_claim_id}/disposal-eligibility",
        headers=beta_headers,
    )
    assert cross_preview.status_code == 404
