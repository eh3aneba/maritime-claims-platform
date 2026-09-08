from datetime import datetime, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth import mfa
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.mfa_recovery import regenerate_recovery_codes
from app.modules.auth.mfa_recovery_models import MfaRecoveryCode
from app.modules.auth.mfa_reset_models import MfaFactorResetRequest
from app.modules.auth.models import AuthSession, TotpMfaFactor
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_org(slug: str) -> tuple[UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Org {slug}", slug=slug)
        db.add(org)
        db.flush()
        admin_a = User(
            organization_id=org.id,
            email=f"admin-a-{slug}@example.com",
            full_name="Admin A",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        admin_b = User(
            organization_id=org.id,
            email=f"admin-b-{slug}@example.com",
            full_name="Admin B",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        target = User(
            organization_id=org.id,
            email=f"target-{slug}@example.com",
            full_name="Target Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add_all([admin_a, admin_b, target])
        db.commit()
        return org.id, admin_a.id, admin_b.id, target.id


def _headers(user_id: UUID) -> tuple[dict[str, str], UUID]:
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
        return {"Authorization": f"Bearer {token}"}, session.id


def _confirmed_factor_with_recovery_codes(
    *,
    target_user_id: UUID,
    target_session_id: UUID,
) -> UUID:
    with TestingSessionLocal() as db:
        user = db.get(User, target_user_id)
        session = db.get(AuthSession, target_session_id)
        assert user is not None and session is not None
        factor, secret, _ = mfa.start_totp_enrollment(db, user=user)
        step = mfa._current_time_step()
        mfa.confirm_totp_enrollment(
            factor=factor,
            code=mfa._totp_code(secret, step),
        )
        session.mfa_verified_at = datetime.now(timezone.utc)
        session.mfa_method = "totp"
        session.mfa_factor_id = factor.id
        regenerate_recovery_codes(
            db,
            user=user,
            factor=factor,
            auth_session=session,
        )
        db.commit()
        return factor.id


def test_reset_requires_four_eyes_and_revokes_factor_recovery_codes_and_target_sessions() -> None:
    org_id, admin_a_id, admin_b_id, target_id = _seed_org("reset-primary")
    admin_a_headers, _ = _headers(admin_a_id)
    admin_b_headers, _ = _headers(admin_b_id)
    target_headers, target_session_id = _headers(target_id)
    _, second_target_session_id = _headers(target_id)
    factor_id = _confirmed_factor_with_recovery_codes(
        target_user_id=target_id,
        target_session_id=target_session_id,
    )

    created = client.post(
        "/api/v1/auth/mfa-resets",
        headers=admin_a_headers,
        json={
            "user_id": str(target_id),
            "factor_id": str(factor_id),
            "reason": "Target user reported loss of the enrolled authenticator device",
        },
    )
    assert created.status_code == 201, created.text
    request_id = UUID(created.json()["id"])
    assert created.json()["status"] == "pending"

    duplicate = client.post(
        "/api/v1/auth/mfa-resets",
        headers=admin_a_headers,
        json={
            "user_id": str(target_id),
            "factor_id": str(factor_id),
            "reason": "Duplicate open reset requests must be rejected by the lifecycle",
        },
    )
    assert duplicate.status_code == 409

    self_approval = client.post(
        f"/api/v1/auth/mfa-resets/{request_id}/approve",
        headers=admin_a_headers,
    )
    assert self_approval.status_code == 403

    approved = client.post(
        f"/api/v1/auth/mfa-resets/{request_id}/approve",
        headers=admin_b_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by_id"] == str(admin_b_id)

    executed = client.post(
        f"/api/v1/auth/mfa-resets/{request_id}/execute",
        headers=admin_a_headers,
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["request"]["status"] == "executed"
    assert executed.json()["invalidated_recovery_codes"] == 10
    assert executed.json()["revoked_sessions"] == 2

    replay = client.post(
        f"/api/v1/auth/mfa-resets/{request_id}/execute",
        headers=admin_a_headers,
    )
    assert replay.status_code == 409

    old_target_session = client.get("/api/v1/auth/me", headers=target_headers)
    assert old_target_session.status_code == 401

    with TestingSessionLocal() as db:
        reset = db.get(MfaFactorResetRequest, request_id)
        factor = db.get(TotpMfaFactor, factor_id)
        codes = db.query(MfaRecoveryCode).filter(MfaRecoveryCode.factor_id == factor_id).all()
        target_sessions = (
            db.query(AuthSession)
            .filter(
                AuthSession.organization_id == org_id,
                AuthSession.user_id == target_id,
            )
            .all()
        )
        assert reset is not None and reset.status == "executed"
        assert reset.requested_by_id == admin_a_id
        assert reset.approved_by_id == admin_b_id
        assert factor is not None and factor.revoked_at is not None
        assert factor.revocation_reason == f"governed_factor_reset:{request_id}"
        assert len(codes) == 10
        assert all(code.invalidated_at is not None for code in codes)
        assert {session.id for session in target_sessions} >= {
            target_session_id,
            second_target_session_id,
        }
        assert all(session.revoked_at is not None for session in target_sessions)

    fresh_target_headers, _ = _headers(target_id)
    reenrollment = client.post(
        "/api/v1/auth/mfa/totp/enroll",
        headers=fresh_target_headers,
    )
    assert reenrollment.status_code == 201, reenrollment.text
    assert UUID(reenrollment.json()["factor_id"]) != factor_id


def test_reset_rejection_cancellation_and_tenant_isolation() -> None:
    _, admin_a_id, admin_b_id, target_id = _seed_org("reset-transitions")
    _, foreign_admin_id, _, _ = _seed_org("reset-foreign")
    admin_a_headers, _ = _headers(admin_a_id)
    admin_b_headers, _ = _headers(admin_b_id)
    foreign_headers, _ = _headers(foreign_admin_id)
    _, target_session_id = _headers(target_id)
    factor_id = _confirmed_factor_with_recovery_codes(
        target_user_id=target_id,
        target_session_id=target_session_id,
    )

    first = client.post(
        "/api/v1/auth/mfa-resets",
        headers=admin_a_headers,
        json={
            "user_id": str(target_id),
            "factor_id": str(factor_id),
            "reason": "First governed reset request for transition coverage",
        },
    )
    assert first.status_code == 201
    first_id = UUID(first.json()["id"])

    foreign = client.post(
        f"/api/v1/auth/mfa-resets/{first_id}/approve",
        headers=foreign_headers,
    )
    assert foreign.status_code == 404

    rejected = client.post(
        f"/api/v1/auth/mfa-resets/{first_id}/reject",
        headers=admin_b_headers,
        json={"reason": "Identity evidence was not sufficient for this reset"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    second = client.post(
        "/api/v1/auth/mfa-resets",
        headers=admin_a_headers,
        json={
            "user_id": str(target_id),
            "factor_id": str(factor_id),
            "reason": "Second request after the prior request was formally rejected",
        },
    )
    assert second.status_code == 201
    second_id = UUID(second.json()["id"])

    non_requester_cancel = client.post(
        f"/api/v1/auth/mfa-resets/{second_id}/cancel",
        headers=admin_b_headers,
    )
    assert non_requester_cancel.status_code == 403

    cancelled = client.post(
        f"/api/v1/auth/mfa-resets/{second_id}/cancel",
        headers=admin_a_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    with TestingSessionLocal() as db:
        factor = db.get(TotpMfaFactor, factor_id)
        assert factor is not None and factor.revoked_at is None


def test_reset_admin_surface_obeys_enabled_tenant_mfa_policy() -> None:
    org_id, admin_a_id, _, _ = _seed_org("reset-policy")
    admin_headers, _ = _headers(admin_a_id)
    with TestingSessionLocal() as db:
        db.add(
            MfaPolicy(
                organization_id=org_id,
                is_enabled=True,
                required_roles=["admin"],
                updated_by_id=admin_a_id,
            )
        )
        db.commit()

    blocked = client.get("/api/v1/auth/mfa-resets", headers=admin_headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_enrollment_required"
