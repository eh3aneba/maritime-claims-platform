from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth import mfa
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.models import TotpMfaFactor
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_admin(*, slug: str, email: str) -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Org {slug}", slug=slug)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email=email,
            full_name=f"Admin {slug}",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return org.id, user.id


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


def _enable_admin_policy(headers: dict[str, str]) -> None:
    response = client.put(
        "/api/v1/auth/mfa-policy",
        headers=headers,
        json={"is_enabled": True, "required_roles": ["admin"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_enabled"] is True
    assert response.json()["required_roles"] == ["admin"]


def test_mfa_policy_defaults_disabled_and_enforces_sensitive_admin_surface(monkeypatch) -> None:
    org_id, user_id = _seed_admin(
        slug="mfa-policy-primary",
        email="admin@example.com",
    )
    headers, _ = _headers(user_id)

    default_policy = client.get("/api/v1/auth/mfa-policy", headers=headers)
    assert default_policy.status_code == 200
    assert default_policy.json() == {
        "organization_id": str(org_id),
        "is_enabled": False,
        "required_roles": [],
    }

    provider = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": "policy-oidc",
            "display_name": "Policy OIDC",
            "protocol": "oidc",
            "issuer_identifier": "https://idp.policy.example.test",
        },
    )
    assert provider.status_code == 201, provider.text

    _enable_admin_policy(headers)

    # Ordinary authenticated surfaces are intentionally unchanged in this tranche.
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200

    blocked = client.get("/api/v1/auth/identity-providers", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_enrollment_required"

    policy_mutation_blocked = client.put(
        "/api/v1/auth/mfa-policy",
        headers=headers,
        json={"is_enabled": False, "required_roles": ["admin"]},
    )
    assert policy_mutation_blocked.status_code == 403
    assert policy_mutation_blocked.json()["detail"]["code"] == "mfa_enrollment_required"

    enrollment = client.post("/api/v1/auth/mfa/totp/enroll", headers=headers)
    assert enrollment.status_code == 201, enrollment.text
    factor_id = UUID(enrollment.json()["factor_id"])
    secret = enrollment.json()["secret"]

    first_step = mfa._current_time_step()
    confirmation = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/confirm",
        headers=headers,
        json={"code": mfa._totp_code(secret, first_step)},
    )
    assert confirmation.status_code == 200, confirmation.text

    before_verify = client.get("/api/v1/auth/identity-providers", headers=headers)
    assert before_verify.status_code == 403
    assert before_verify.json()["detail"]["code"] == "mfa_verification_required"

    second_step = first_step + 1
    monkeypatch.setattr(mfa, "_current_time_step", lambda period_seconds=30: second_step)
    verification = client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers=headers,
        json={"code": mfa._totp_code(secret, second_step)},
    )
    assert verification.status_code == 200, verification.text

    allowed = client.get("/api/v1/auth/identity-providers", headers=headers)
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1

    with TestingSessionLocal() as db:
        policy = db.query(MfaPolicy).filter(MfaPolicy.organization_id == org_id).one()
        factor = db.get(TotpMfaFactor, factor_id)
        user = db.get(User, user_id)
        assert policy.is_enabled is True
        assert policy.required_roles == ["admin"]
        assert factor is not None and factor.confirmed_at is not None
        assert user is not None and user.role == UserRole.ADMIN


def test_mfa_step_up_is_session_and_tenant_scoped_and_confirmed_factor_cannot_be_revoked_without_step_up(monkeypatch) -> None:
    org_a, user_a = _seed_admin(slug="mfa-a", email="a@example.com")
    org_b, user_b = _seed_admin(slug="mfa-b", email="b@example.com")
    headers_a, _ = _headers(user_a)
    headers_b, _ = _headers(user_b)

    _enable_admin_policy(headers_a)

    enrollment = client.post("/api/v1/auth/mfa/totp/enroll", headers=headers_a)
    assert enrollment.status_code == 201
    factor_id = UUID(enrollment.json()["factor_id"])
    secret = enrollment.json()["secret"]
    first_step = mfa._current_time_step()
    confirm = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/confirm",
        headers=headers_a,
        json={"code": mfa._totp_code(secret, first_step)},
    )
    assert confirm.status_code == 200

    second_step = first_step + 1
    monkeypatch.setattr(mfa, "_current_time_step", lambda period_seconds=30: second_step)
    verify = client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers=headers_a,
        json={"code": mfa._totp_code(secret, second_step)},
    )
    assert verify.status_code == 200

    second_session_headers, _ = _headers(user_a)
    session_isolation = client.get(
        "/api/v1/auth/identity-providers",
        headers=second_session_headers,
    )
    assert session_isolation.status_code == 403
    assert session_isolation.json()["detail"]["code"] == "mfa_verification_required"

    revoke_without_step_up = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/revoke",
        headers=second_session_headers,
    )
    assert revoke_without_step_up.status_code == 403
    assert revoke_without_step_up.json()["detail"]["code"] == "mfa_verification_required"

    tenant_b_policy = client.get("/api/v1/auth/mfa-policy", headers=headers_b)
    assert tenant_b_policy.status_code == 200
    assert tenant_b_policy.json()["organization_id"] == str(org_b)
    assert tenant_b_policy.json()["is_enabled"] is False

    revoke_verified = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/revoke",
        headers=headers_a,
    )
    assert revoke_verified.status_code == 204

    after_revoke = client.get(
        "/api/v1/auth/identity-providers",
        headers=headers_a,
    )
    assert after_revoke.status_code == 403
    assert after_revoke.json()["detail"]["code"] == "mfa_enrollment_required"

    with TestingSessionLocal() as db:
        policy_a = db.query(MfaPolicy).filter(MfaPolicy.organization_id == org_a).one()
        policy_b = db.query(MfaPolicy).filter(MfaPolicy.organization_id == org_b).one_or_none()
        user = db.get(User, user_a)
        assert policy_a.is_enabled is True
        assert policy_b is None
        assert user is not None and user.role == UserRole.ADMIN
