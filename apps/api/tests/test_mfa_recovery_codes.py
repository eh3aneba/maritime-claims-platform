from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth import mfa
from app.modules.auth.mfa_recovery_models import MfaRecoveryCode
from app.modules.auth.models import AuthSession, TotpMfaFactor
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


def _confirmed_factor(headers: dict[str, str]) -> tuple[UUID, str, int]:
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
    return factor_id, secret, first_step


def _verify_totp_session(
    monkeypatch,
    *,
    headers: dict[str, str],
    secret: str,
    time_step: int,
) -> None:
    monkeypatch.setattr(mfa, "_current_time_step", lambda period_seconds=30: time_step)
    response = client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers=headers,
        json={"code": mfa._totp_code(secret, time_step)},
    )
    assert response.status_code == 200, response.text


def test_recovery_codes_are_one_time_hashed_and_exact_session_scoped(monkeypatch) -> None:
    org_id, user_id = _seed_admin(
        slug="mfa-recovery-primary",
        email="recovery-primary@example.com",
    )
    primary_headers, primary_session_id = _headers(user_id)
    factor_id, secret, first_step = _confirmed_factor(primary_headers)

    blocked_generation = client.post(
        "/api/v1/auth/mfa/recovery-codes/regenerate",
        headers=primary_headers,
    )
    assert blocked_generation.status_code == 403
    assert blocked_generation.json()["detail"]["code"] == "mfa_verification_required"

    _verify_totp_session(
        monkeypatch,
        headers=primary_headers,
        secret=secret,
        time_step=first_step + 1,
    )

    generated = client.post(
        "/api/v1/auth/mfa/recovery-codes/regenerate",
        headers=primary_headers,
    )
    assert generated.status_code == 201, generated.text
    payload = generated.json()
    assert payload["factor_id"] == str(factor_id)
    assert payload["count"] == 10
    assert len(payload["recovery_codes"]) == 10
    assert len(set(payload["recovery_codes"])) == 10
    first_code = payload["recovery_codes"][0]
    second_code = payload["recovery_codes"][1]
    assert len(first_code.replace("-", "")) == 32

    with TestingSessionLocal() as db:
        rows = (
            db.query(MfaRecoveryCode)
            .filter(
                MfaRecoveryCode.organization_id == org_id,
                MfaRecoveryCode.user_id == user_id,
                MfaRecoveryCode.factor_id == factor_id,
            )
            .order_by(MfaRecoveryCode.position.asc())
            .all()
        )
        assert len(rows) == 10
        assert all(len(row.code_digest) == 64 for row in rows)
        assert all(row.consumed_at is None for row in rows)
        assert all(row.invalidated_at is None for row in rows)
        assert all(first_code not in row.code_digest for row in rows)
        assert all(first_code.replace("-", "") not in row.code_digest for row in rows)

    recovery_headers, recovery_session_id = _headers(user_id)
    before_recovery = client.get(
        "/api/v1/auth/identity-providers",
        headers=recovery_headers,
    )
    assert before_recovery.status_code == 200

    recovery_verify = client.post(
        "/api/v1/auth/mfa/recovery-codes/verify",
        headers=recovery_headers,
        json={"code": first_code},
    )
    assert recovery_verify.status_code == 200, recovery_verify.text
    assert recovery_verify.json()["id"] == str(recovery_session_id)
    assert recovery_verify.json()["mfa_method"] == "recovery_code"
    assert recovery_verify.json()["mfa_factor_id"] == str(factor_id)

    replay = client.post(
        "/api/v1/auth/mfa/recovery-codes/verify",
        headers=recovery_headers,
        json={"code": first_code},
    )
    assert replay.status_code == 401
    assert replay.json()["detail"] == "Invalid recovery code"

    isolated_headers, isolated_session_id = _headers(user_id)
    with TestingSessionLocal() as db:
        isolated_session = db.get(AuthSession, isolated_session_id)
        assert isolated_session is not None
        assert isolated_session.mfa_verified_at is None
        assert isolated_session.mfa_method is None

    regenerated = client.post(
        "/api/v1/auth/mfa/recovery-codes/regenerate",
        headers=recovery_headers,
    )
    assert regenerated.status_code == 201, regenerated.text
    new_codes = regenerated.json()["recovery_codes"]
    assert len(new_codes) == 10
    assert set(new_codes).isdisjoint(set(payload["recovery_codes"]))

    invalidated_old_code = client.post(
        "/api/v1/auth/mfa/recovery-codes/verify",
        headers=isolated_headers,
        json={"code": second_code},
    )
    assert invalidated_old_code.status_code == 401

    with TestingSessionLocal() as db:
        rows = (
            db.query(MfaRecoveryCode)
            .filter(MfaRecoveryCode.factor_id == factor_id)
            .order_by(MfaRecoveryCode.created_at.asc(), MfaRecoveryCode.position.asc())
            .all()
        )
        assert len(rows) == 20
        first_batch = [row for row in rows if str(row.batch_id) == payload["batch_id"]]
        second_batch = [row for row in rows if str(row.batch_id) == regenerated.json()["batch_id"]]
        assert len(first_batch) == 10
        assert len(second_batch) == 10
        consumed = [row for row in first_batch if row.consumed_at is not None]
        invalidated = [row for row in first_batch if row.invalidated_at is not None]
        assert len(consumed) == 1
        assert consumed[0].consumed_auth_session_id == recovery_session_id
        assert len(invalidated) == 9
        assert all(row.invalidated_by_session_id == recovery_session_id for row in invalidated)
        assert all(row.consumed_at is None for row in second_batch)
        primary_session = db.get(AuthSession, primary_session_id)
        recovery_session = db.get(AuthSession, recovery_session_id)
        isolated_session = db.get(AuthSession, isolated_session_id)
        factor = db.get(TotpMfaFactor, factor_id)
        assert primary_session is not None and primary_session.mfa_method == "totp"
        assert recovery_session is not None and recovery_session.mfa_method == "recovery_code"
        assert isolated_session is not None and isolated_session.mfa_verified_at is None
        assert factor is not None and factor.revoked_at is None


def test_recovery_code_respects_tenant_and_mfa_policy_authority(monkeypatch) -> None:
    _, user_a = _seed_admin(slug="mfa-recovery-a", email="recovery-a@example.com")
    _, user_b = _seed_admin(slug="mfa-recovery-b", email="recovery-b@example.com")
    headers_a, _ = _headers(user_a)
    headers_b, _ = _headers(user_b)

    factor_a, secret_a, step_a = _confirmed_factor(headers_a)
    _verify_totp_session(
        monkeypatch,
        headers=headers_a,
        secret=secret_a,
        time_step=step_a + 1,
    )
    generated = client.post(
        "/api/v1/auth/mfa/recovery-codes/regenerate",
        headers=headers_a,
    )
    assert generated.status_code == 201
    recovery_code = generated.json()["recovery_codes"][0]

    policy = client.put(
        "/api/v1/auth/mfa-policy",
        headers=headers_a,
        json={"is_enabled": True, "required_roles": ["admin"]},
    )
    assert policy.status_code == 200, policy.text

    tenant_b_attempt = client.post(
        "/api/v1/auth/mfa/recovery-codes/verify",
        headers=headers_b,
        json={"code": recovery_code},
    )
    assert tenant_b_attempt.status_code == 409

    recovery_headers, recovery_session_id = _headers(user_a)
    blocked_sensitive = client.get(
        "/api/v1/auth/identity-providers",
        headers=recovery_headers,
    )
    assert blocked_sensitive.status_code == 403
    assert blocked_sensitive.json()["detail"]["code"] == "mfa_verification_required"

    verified = client.post(
        "/api/v1/auth/mfa/recovery-codes/verify",
        headers=recovery_headers,
        json={"code": recovery_code},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["id"] == str(recovery_session_id)
    assert verified.json()["mfa_method"] == "recovery_code"
    assert verified.json()["mfa_factor_id"] == str(factor_a)

    allowed_sensitive = client.get(
        "/api/v1/auth/identity-providers",
        headers=recovery_headers,
    )
    assert allowed_sensitive.status_code == 200

    another_session_headers, _ = _headers(user_a)
    still_blocked = client.get(
        "/api/v1/auth/identity-providers",
        headers=another_session_headers,
    )
    assert still_blocked.status_code == 403
    assert still_blocked.json()["detail"]["code"] == "mfa_verification_required"
