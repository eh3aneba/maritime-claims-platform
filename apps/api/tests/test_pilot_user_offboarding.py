"""Tenant-scoped pilot user deactivation acceptance (synthetic identities)."""
from __future__ import annotations

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth import mfa
from app.modules.auth.models import AuthSession
from app.modules.auth.service import create_auth_session
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_auth_session_assurance import _login, _seed_users, _test_password


def setup_function() -> None:
    reset_database()


def _verified_admin(monkeypatch):
    token, admin_session_id = _login(
        "alpha-session", "alpha-admin-session@example.com"
    )
    headers = {"Authorization": f"Bearer {token}"}
    enrollment = client.post("/api/v1/auth/mfa/totp/enroll", headers=headers)
    assert enrollment.status_code == 201, enrollment.text
    factor_id = enrollment.json()["factor_id"]
    secret = enrollment.json()["secret"]
    step = mfa._current_time_step()
    confirmation = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/confirm",
        headers=headers, json={"code": mfa._totp_code(secret, step)},
    )
    assert confirmation.status_code == 200, confirmation.text
    verified_step = step + 1
    monkeypatch.setattr(
        mfa, "_current_time_step",
        lambda period_seconds=30: verified_step,
    )
    verification = client.post(
        "/api/v1/auth/mfa/totp/verify",
        headers=headers,
        json={"code": mfa._totp_code(secret, verified_step)},
    )
    assert verification.status_code == 200, verification.text
    return headers, admin_session_id


def _deactivate(headers, target_id, ticket="pilot-offboard-001"):
    return client.post(
        f"/api/v1/users/{target_id}/deactivate",
        headers=headers,
        json={
            "change_ticket_ref": ticket,
            "confirmation": "DEACTIVATE_USER",
        },
    )


def test_deactivation_requires_current_mfa_even_without_tenant_policy(monkeypatch):
    _org, _admin, target, _other_org, _other_admin = _seed_users()
    token, _ = _login("alpha-session", "alpha-admin-session@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    denied = _deactivate(headers, target)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "mfa_enrollment_required"
    with TestingSessionLocal() as db:
        assert db.get(User, target).is_active is True


def test_offboarding_revokes_sessions_denies_new_login_and_is_idempotent(monkeypatch):
    _org, admin_id, target_id, _other_org, _other_admin = _seed_users()
    token1, sid1 = _login("alpha-session", "alpha-handler-session@example.com")
    token2, sid2 = _login("alpha-session", "alpha-handler-session@example.com")
    headers, admin_sid = _verified_admin(monkeypatch)

    result = _deactivate(headers, target_id)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "id": str(target_id),
        "is_active": False,
        "newly_deactivated": True,
        "sessions_revoked": 2,
        "external_identity_deprovisioned": False,
        "external_integrations_disabled": False,
    }
    with TestingSessionLocal() as db:
        assert db.get(User, target_id).is_active is False
        for sid in (sid1, sid2):
            revoked = db.get(AuthSession, sid)
            assert revoked.revoked_at is not None
            assert revoked.revoked_by_id == admin_id
        assert db.get(AuthSession, admin_sid).revoked_at is None
        audits = db.query(AuditLog).filter(
            AuditLog.action == "PILOT_USER_DEACTIVATED_AND_SESSIONS_REVOKED"
        ).all()
        assert len(audits) == 1
        assert audits[0].new_values["sessions_revoked"] == 2

    for token in (token1, token2):
        assert client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={
            "organization_slug": "alpha-session",
            "email": "alpha-handler-session@example.com",
            "password": _test_password(),
        },
    ).status_code == 401

    replay = _deactivate(headers, target_id, ticket="pilot-offboard-002")
    assert replay.status_code == 200
    assert replay.json()["newly_deactivated"] is False
    assert replay.json()["sessions_revoked"] == 0
    with TestingSessionLocal() as db:
        assert db.query(AuditLog).filter(
            AuditLog.action == "PILOT_USER_DEACTIVATED_AND_SESSIONS_REVOKED"
        ).count() == 1


def test_cross_tenant_self_unprivileged_and_unconfirmed_denied(monkeypatch):
    _org, admin_id, target_id, _other_org, outside_id = _seed_users()
    handler_token, sid = _login(
        "alpha-session", "alpha-handler-session@example.com"
    )
    headers, admin_sid = _verified_admin(monkeypatch)
    assert _deactivate(headers, outside_id).status_code == 404
    assert _deactivate(headers, admin_id).status_code == 409
    assert _deactivate(
        {"Authorization": f"Bearer {handler_token}"}, target_id
    ).status_code == 403
    bad_confirm = client.post(
        f"/api/v1/users/{target_id}/deactivate",
        headers=headers,
        json={"change_ticket_ref": "pilot-offboard-003", "confirmation": "YES"},
    )
    assert bad_confirm.status_code == 422
    with TestingSessionLocal() as db:
        assert db.get(User, target_id).is_active is True
        assert db.get(User, outside_id).is_active is True
        assert db.get(AuthSession, sid).revoked_at is None
        assert db.get(AuthSession, admin_sid).revoked_at is None


def test_external_identity_session_and_delayed_token_fail_after_deactivation(monkeypatch):
    org_id, _admin, target_id, _other_org, _other_admin = _seed_users()
    headers, _admin_sid = _verified_admin(monkeypatch)
    with TestingSessionLocal() as db:
        target = db.get(User, target_id)
        assert target is not None
        external = create_auth_session(
            db, user=target, identity_source="oidc", auth_method="oidc"
        )
        db.commit()
        external_sid = external.id
    external_token = create_access_token(
        user_id=target_id, organization_id=org_id,
        role=UserRole.CLAIMS_HANDLER.value, session_id=external_sid,
        identity_source="oidc", auth_method="oidc",
    )
    response = _deactivate(headers, target_id)
    assert response.status_code == 200, response.text
    assert response.json()["sessions_revoked"] == 1
    assert response.json()["external_identity_deprovisioned"] is False
    with TestingSessionLocal() as db:
        assert db.get(AuthSession, external_sid).revoked_at is not None
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {external_token}"},
    ).status_code == 401

    # Even if a delayed callback created a server-side session after the
    # deactivation commit, inactive app membership denies the new token.
    with TestingSessionLocal() as db:
        target = db.get(User, target_id)
        delayed = create_auth_session(db, user=target)
        db.commit()
        delayed_sid = delayed.id
    delayed_token = create_access_token(
        user_id=target_id, organization_id=org_id,
        role=UserRole.CLAIMS_HANDLER.value, session_id=delayed_sid,
        identity_source="local", auth_method="password",
    )
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {delayed_token}"},
    ).status_code == 401
    replay = _deactivate(headers, target_id, ticket="pilot-offboard-004")
    assert replay.status_code == 200
    assert replay.json()["newly_deactivated"] is False
    assert replay.json()["sessions_revoked"] == 1
    with TestingSessionLocal() as db:
        assert db.get(AuthSession, delayed_sid).revoked_at is not None
