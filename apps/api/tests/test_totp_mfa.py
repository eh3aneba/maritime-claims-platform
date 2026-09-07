import json
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth import mfa
from app.modules.auth.models import AuthSession, TotpMfaFactor
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_user(*, slug: str, email: str) -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Org {slug}", slug=slug)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email=email,
            full_name=f"User {slug}",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
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


def test_totp_enrollment_confirmation_verification_replay_and_revocation(monkeypatch) -> None:
    org_id, user_id = _seed_user(slug="totp-primary", email="handler@example.test")
    headers, session_id = _headers(user_id)

    enrollment = client.post("/api/v1/auth/mfa/totp/enroll", headers=headers)
    assert enrollment.status_code == 201, enrollment.text
    bootstrap = enrollment.json()
    factor_id = UUID(bootstrap["factor_id"])
    secret = bootstrap["secret"]
    assert len(secret) >= 32
    assert bootstrap["otpauth_uri"].startswith("otpauth://totp/")
    assert secret in bootstrap["otpauth_uri"]

    with TestingSessionLocal() as db:
        factor = db.get(TotpMfaFactor, factor_id)
        assert factor is not None
        assert factor.organization_id == org_id
        assert factor.user_id == user_id
        assert factor.secret_ciphertext != secret
        assert secret not in factor.secret_ciphertext
        assert factor.secret_nonce
        assert factor.secret_fingerprint == mfa._secret_fingerprint(secret)
        assert factor.confirmed_at is None
        user = db.get(User, user_id)
        assert user is not None and user.role == UserRole.CLAIMS_HANDLER
        audits = db.query(AuditLog).all()
        serialized = json.dumps(
            [
                {
                    "action": row.action,
                    "old": row.old_values,
                    "new": row.new_values,
                    "details": row.details,
                }
                for row in audits
            ],
            sort_keys=True,
        )
        assert secret not in serialized
        assert bootstrap["otpauth_uri"] not in serialized

    first_step = mfa._current_time_step()
    first_code = mfa._totp_code(secret, first_step)
    confirm = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/confirm",
        headers=headers,
        json={"code": first_code},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["confirmed_at"] is not None
    assert "secret_ciphertext" not in confirm.json()
    assert "secret_nonce" not in confirm.json()

    second_step = first_step + 1
    monkeypatch.setattr(mfa, "_current_time_step", lambda period_seconds=30: second_step)
    second_code = mfa._totp_code(secret, second_step)
    verified = client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers=headers,
        json={"code": second_code},
    )
    assert verified.status_code == 200, verified.text
    verified_payload = verified.json()
    assert verified_payload["id"] == str(session_id)
    assert verified_payload["mfa_method"] == "totp"
    assert verified_payload["mfa_factor_id"] == str(factor_id)
    assert verified_payload["mfa_verified_at"] is not None

    session_response = client.get("/api/v1/auth/session", headers=headers)
    assert session_response.status_code == 200
    assert session_response.json()["mfa_method"] == "totp"
    assert session_response.json()["mfa_factor_id"] == str(factor_id)

    replay = client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers=headers,
        json={"code": second_code},
    )
    assert replay.status_code == 401
    assert "replay" in replay.json()["detail"].lower()

    revoke = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/revoke",
        headers=headers,
    )
    assert revoke.status_code == 204

    third_step = second_step + 1
    monkeypatch.setattr(mfa, "_current_time_step", lambda period_seconds=30: third_step)
    after_revoke = client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers=headers,
        json={"code": mfa._totp_code(secret, third_step)},
    )
    assert after_revoke.status_code == 401

    with TestingSessionLocal() as db:
        factor = db.get(TotpMfaFactor, factor_id)
        session = db.get(AuthSession, session_id)
        user = db.get(User, user_id)
        assert factor is not None and factor.revoked_at is not None
        assert session is not None and session.mfa_factor_id == factor_id
        assert user is not None and user.role == UserRole.CLAIMS_HANDLER
        serialized = json.dumps(
            [row.new_values or {} for row in db.query(AuditLog).all()],
            sort_keys=True,
        )
        assert secret not in serialized
        assert first_code not in serialized
        assert second_code not in serialized


def test_totp_factor_is_tenant_and_user_scoped() -> None:
    _, user_a = _seed_user(slug="totp-a", email="a@example.test")
    _, user_b = _seed_user(slug="totp-b", email="b@example.test")
    headers_a, _ = _headers(user_a)
    headers_b, _ = _headers(user_b)

    enrollment_b = client.post("/api/v1/auth/mfa/totp/enroll", headers=headers_b)
    assert enrollment_b.status_code == 201
    factor_b = enrollment_b.json()["factor_id"]

    cross_confirm = client.post(
        f"/api/v1/auth/mfa/totp/{factor_b}/confirm",
        headers=headers_a,
        json={"code": "000000"},
    )
    assert cross_confirm.status_code == 404

    cross_revoke = client.post(
        f"/api/v1/auth/mfa/totp/{factor_b}/revoke",
        headers=headers_a,
    )
    assert cross_revoke.status_code == 404

    own_factor_a = client.get("/api/v1/auth/mfa/totp/factor", headers=headers_a)
    assert own_factor_a.status_code == 404

    with TestingSessionLocal() as db:
        user = db.get(User, user_a)
        assert user is not None and user.role == UserRole.CLAIMS_HANDLER
