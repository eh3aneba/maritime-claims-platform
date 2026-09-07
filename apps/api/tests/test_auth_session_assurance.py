from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.modules.auth.models import AuthSession
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database

settings = get_settings()


def _test_password() -> str:
    return "session-" + "test-" + "only"


def setup_function() -> None:
    reset_database()


def _seed_users() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org_a = Organization(name="Alpha Marine", slug="alpha-session")
        org_b = Organization(name="Beta Marine", slug="beta-session")
        db.add_all([org_a, org_b])
        db.flush()

        admin_a = User(
            organization_id=org_a.id,
            email="alpha-admin-session@example.com",
            full_name="Alpha Admin",
            password_hash=hash_password(_test_password()),
            role=UserRole.ADMIN,
            is_active=True,
        )
        handler_a = User(
            organization_id=org_a.id,
            email="alpha-handler-session@example.com",
            full_name="Alpha Handler",
            password_hash=hash_password(_test_password()),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        admin_b = User(
            organization_id=org_b.id,
            email="beta-admin-session@example.com",
            full_name="Beta Admin",
            password_hash=hash_password(_test_password()),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add_all([admin_a, handler_a, admin_b])
        db.commit()
        return org_a.id, admin_a.id, handler_a.id, org_b.id, admin_b.id


def _login(org_slug: str, email: str) -> tuple[str, UUID]:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization_slug": org_slug, "email": email, "password": _test_password()},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    session_id = UUID(decode_access_token(token)["sid"])
    return token, session_id


def test_login_creates_server_session_and_exposes_bounded_context() -> None:
    org_a_id, admin_a_id, _, _, _ = _seed_users()
    token, session_id = _login("alpha-session", "alpha-admin-session@example.com")

    with TestingSessionLocal() as db:
        auth_session = db.get(AuthSession, session_id)
        assert auth_session is not None
        assert auth_session.organization_id == org_a_id
        assert auth_session.user_id == admin_a_id
        assert auth_session.identity_source == "local"
        assert auth_session.auth_method == "password"
        assert auth_session.revoked_at is None

    payload = decode_access_token(token)
    assert payload["src"] == "local"
    assert payload["amr"] == "password"

    response = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": str(session_id),
        "organization_id": str(org_a_id),
        "user_id": str(admin_a_id),
        "identity_source": "local",
        "auth_method": "password",
        "created_at": body["created_at"],
        "expires_at": body["expires_at"],
    }
    serialized = str(body).lower()
    for forbidden in ("password_hash", "access_token", "assertion", "client_secret", "mfa_secret"):
        assert forbidden not in serialized


def test_logout_revokes_exact_session_and_rejects_captured_token() -> None:
    _seed_users()
    token, session_id = _login("alpha-session", "alpha-admin-session@example.com")

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout.status_code == 204

    with TestingSessionLocal() as db:
        auth_session = db.get(AuthSession, session_id)
        assert auth_session is not None
        assert auth_session.revoked_at is not None
        assert auth_session.revoked_by_id == auth_session.user_id
        assert auth_session.revocation_reason == "logout"

    replay = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert replay.status_code == 401


def test_nonexistent_session_fails_closed() -> None:
    org_a_id, admin_a_id, _, _, _ = _seed_users()
    token = create_access_token(
        user_id=admin_a_id,
        organization_id=org_a_id,
        role=UserRole.ADMIN.value,
        session_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        identity_source="local",
        auth_method="password",
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_expired_session_fails_closed() -> None:
    org_a_id, admin_a_id, _, _, _ = _seed_users()
    with TestingSessionLocal() as db:
        user = db.get(User, admin_a_id)
        assert user is not None
        auth_session = create_auth_session(db, user=user)
        auth_session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        session_id = auth_session.id

    token = create_access_token(
        user_id=admin_a_id,
        organization_id=org_a_id,
        role=UserRole.ADMIN.value,
        session_id=session_id,
        identity_source="local",
        auth_method="password",
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_session_provenance_mismatch_fails_closed() -> None:
    org_a_id, admin_a_id, _, _, _ = _seed_users()
    with TestingSessionLocal() as db:
        user = db.get(User, admin_a_id)
        assert user is not None
        auth_session = create_auth_session(db, user=user)
        db.commit()
        session_id = auth_session.id

    token = create_access_token(
        user_id=admin_a_id,
        organization_id=org_a_id,
        role=UserRole.ADMIN.value,
        session_id=session_id,
        identity_source="oidc",
        auth_method="password",
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_token_without_session_claim_is_rejected() -> None:
    org_a_id, admin_a_id, _, _, _ = _seed_users()
    now = datetime.now(timezone.utc)
    legacy_payload = {
        "sub": str(admin_a_id),
        "org": str(org_a_id),
        "role": UserRole.ADMIN.value,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.token_issuer,
        "aud": settings.token_audience,
    }
    token = jwt.encode(
        legacy_payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_admin_can_revoke_same_tenant_session() -> None:
    _seed_users()
    handler_token, handler_session_id = _login(
        "alpha-session",
        "alpha-handler-session@example.com",
    )
    admin_token, admin_session_id = _login(
        "alpha-session",
        "alpha-admin-session@example.com",
    )

    response = client.post(
        f"/api/v1/auth/sessions/{handler_session_id}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 204

    with TestingSessionLocal() as db:
        target = db.get(AuthSession, handler_session_id)
        assert target is not None
        assert target.revoked_at is not None
        assert target.revoked_by_id == UUID(decode_access_token(admin_token)["sub"])
        admin_session = db.get(AuthSession, admin_session_id)
        assert admin_session is not None
        assert admin_session.revoked_at is None

    rejected = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {handler_token}"},
    )
    assert rejected.status_code == 401


def test_cross_tenant_admin_cannot_revoke_or_discover_session() -> None:
    _seed_users()
    beta_token, beta_session_id = _login(
        "beta-session",
        "beta-admin-session@example.com",
    )
    alpha_token, _ = _login(
        "alpha-session",
        "alpha-admin-session@example.com",
    )

    response = client.post(
        f"/api/v1/auth/sessions/{beta_session_id}/revoke",
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert response.status_code == 404

    still_valid = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {beta_token}"},
    )
    assert still_valid.status_code == 200
    with TestingSessionLocal() as db:
        target = db.get(AuthSession, beta_session_id)
        assert target is not None
        assert target.revoked_at is None


def test_claim_handler_cannot_revoke_sessions() -> None:
    _seed_users()
    handler_token, handler_session_id = _login(
        "alpha-session",
        "alpha-handler-session@example.com",
    )
    response = client.post(
        f"/api/v1/auth/sessions/{handler_session_id}/revoke",
        headers={"Authorization": f"Bearer {handler_token}"},
    )
    assert response.status_code == 403


def test_mt_orion_design_partner_login_logout_lifecycle() -> None:
    with TestingSessionLocal() as db:
        org = Organization(name="Pilot Marine Insurer", slug="pilot")
        db.add(org)
        db.flush()
        manager = User(
            organization_id=org.id,
            email="manager@demo.mcri.app",
            full_name="Pilot Claims Manager",
            password_hash=hash_password(_test_password()),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        db.add(manager)
        db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={
            "organization_slug": "pilot",
            "email": "manager@demo.mcri.app",
            "password": _test_password(),
        },
    )
    assert login.status_code == 200
    captured_token = login.json()["access_token"]

    session_response = client.get("/api/v1/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["identity_source"] == "local"
    assert session_response.json()["auth_method"] == "password"

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert (
        client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {captured_token}"},
        ).status_code
        == 401
    )
