import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthSession
from app.modules.auth.scim_models import ScimUserBinding, ScimUserProvisioningGrant
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"


def setup_function() -> None:
    reset_database()


def _seed_actor(*, slug: str, email: str, role: UserRole = UserRole.ADMIN) -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"SCIM T {slug}", slug=slug)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email=email,
            full_name=f"SCIM T Actor {slug}",
            password_hash="",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return org.id, user.id


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


def _profile(headers: dict[str, str], *, user_capability: bool, name: str = "Provisioner"):
    return client.post(
        "/api/v1/auth/scim-provisioning/profiles",
        headers=headers,
        json={
            "client_name": name,
            "enabled": True,
            "token_ttl_days": 30,
            "user_provisioning_enabled": user_capability,
        },
    )


def _issue(headers: dict[str, str], profile_id: str):
    return client.post(
        f"/api/v1/auth/scim-provisioning/profiles/{profile_id}/tokens",
        headers=headers,
    )


def _grant(
    headers: dict[str, str],
    *,
    email: str,
    role: str = "claims_handler",
    ttl_hours: int = 24,
):
    return client.post(
        "/api/v1/auth/scim-provisioning/user-grants",
        headers=headers,
        json={"email": email, "role": role, "ttl_hours": ttl_hours},
    )


def _scim_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_user(token: str, *, email: str, external_id: str = "hr-123", roles=None):
    payload = {
        "schemas": [SCIM_USER_SCHEMA],
        "userName": email,
        "displayName": "Provisioned User",
        "active": True,
        "externalId": external_id,
    }
    if roles is not None:
        payload["roles"] = roles
    return client.post(
        "/api/v1/scim/v2/Users",
        headers=_scim_headers(token),
        json=payload,
    )


def test_existing_phase_s_profile_stays_non_mutating_and_new_capability_still_requires_grant() -> None:
    _, admin_id = _seed_actor(slug="capability", email="admin-capability@example.com")
    headers = _headers(admin_id)

    old_profile = _profile(headers, user_capability=False, name="Capability Only")
    assert old_profile.status_code == 201, old_profile.text
    assert old_profile.json()["user_provisioning_enabled"] is False
    old_token = _issue(headers, old_profile.json()["id"])
    assert old_token.status_code == 201
    denied_old = _create_user(old_token.json()["token"], email="new@example.com")
    assert denied_old.status_code == 403

    enabled_profile = _profile(headers, user_capability=True, name="User Provisioning")
    assert enabled_profile.status_code == 201, enabled_profile.text
    assert enabled_profile.json()["user_provisioning_enabled"] is True
    new_token = _issue(headers, enabled_profile.json()["id"])
    assert new_token.status_code == 201

    service_config = client.get(
        "/api/v1/scim/v2/ServiceProviderConfig",
        headers=_scim_headers(new_token.json()["token"]),
    )
    assert service_config.status_code == 200
    assert service_config.json()["filter"] == {"supported": True, "maxResults": 100}

    no_grant = _create_user(new_token.json()["token"], email="new@example.com")
    assert no_grant.status_code == 403


def test_local_grant_is_one_time_role_authority_and_admin_role_is_forbidden() -> None:
    org_id, admin_id = _seed_actor(slug="grant-role", email="admin-grant@example.com")
    headers = _headers(admin_id)
    profile = _profile(headers, user_capability=True)
    token_response = _issue(headers, profile.json()["id"])
    token = token_response.json()["token"]

    admin_grant = _grant(headers, email="dangerous-admin@example.com", role="admin")
    assert admin_grant.status_code == 409

    grant = _grant(headers, email="handler@example.com", role="claims_handler")
    assert grant.status_code == 201, grant.text
    grant_body = grant.json()
    assert "email" not in grant_body
    assert len(grant_body["email_fingerprint"]) == 64

    rejected_roles = _create_user(
        token,
        email="handler@example.com",
        roles=[{"value": "admin"}],
    )
    assert rejected_roles.status_code == 409

    created = _create_user(token, email="handler@example.com")
    assert created.status_code == 201, created.text
    user_id = UUID(created.json()["id"])
    assert "roles" not in created.json()
    assert "externalId" not in created.json()

    replay = _create_user(token, email="handler@example.com")
    assert replay.status_code in {403, 409}

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.organization_id == org_id
        assert user.role == UserRole.CLAIMS_HANDLER
        assert user.password_hash
        binding = db.query(ScimUserBinding).filter(ScimUserBinding.user_id == user_id).one()
        assert binding.external_id_fingerprint is not None
        assert binding.external_id_fingerprint != "hr-123"
        grant_row = db.get(ScimUserProvisioningGrant, UUID(grant_body["id"]))
        assert grant_row is not None
        assert grant_row.consumed_at is not None
        assert grant_row.consumed_user_id == user_id
        assert "email" not in ScimUserProvisioningGrant.__table__.columns

        audit_text = json.dumps(
            [
                {"action": row.action, "new": row.new_values, "old": row.old_values}
                for row in db.query(AuditLog).filter(AuditLog.organization_id == org_id).all()
            ],
            sort_keys=True,
        )
        assert "handler@example.com" not in audit_text
        assert "hr-123" not in audit_text


def test_existing_local_user_cannot_be_silently_claimed() -> None:
    org_id, admin_id = _seed_actor(slug="collision", email="admin-collision@example.com")
    headers = _headers(admin_id)
    profile = _profile(headers, user_capability=True)
    assert profile.status_code == 201

    with TestingSessionLocal() as db:
        existing = User(
            organization_id=org_id,
            email="existing@example.com",
            full_name="Existing Local User",
            password_hash="local-hash",
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        db.add(existing)
        db.commit()

    blocked = _grant(headers, email="existing@example.com")
    assert blocked.status_code == 409
    with TestingSessionLocal() as db:
        existing = db.query(User).filter(User.email == "existing@example.com").one()
        assert existing.role == UserRole.CLAIMS_MANAGER
        assert db.query(ScimUserBinding).filter(ScimUserBinding.user_id == existing.id).count() == 0


def test_scim_reads_are_bound_only_and_deactivation_revokes_sessions_without_role_change() -> None:
    org_id, admin_id = _seed_actor(slug="lifecycle", email="admin-life@example.com")
    headers = _headers(admin_id)
    profile = _profile(headers, user_capability=True)
    token = _issue(headers, profile.json()["id"]).json()["token"]
    grant = _grant(headers, email="managed@example.com", role="claims_manager")
    assert grant.status_code == 201
    created = _create_user(token, email="managed@example.com", external_id="person-77")
    assert created.status_code == 201, created.text
    user_id = UUID(created.json()["id"])

    with TestingSessionLocal() as db:
        local_only = User(
            organization_id=org_id,
            email="local-only@example.com",
            full_name="Local Only",
            password_hash="local",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add(local_only)
        managed_user = db.get(User, user_id)
        assert managed_user is not None
        session = create_auth_session(db, user=managed_user)
        db.commit()
        session_id = session.id

    listing = client.get("/api/v1/scim/v2/Users", headers=_scim_headers(token))
    assert listing.status_code == 200
    resources = listing.json()["Resources"]
    assert [item["userName"] for item in resources] == ["managed@example.com"]

    filtered = client.get(
        '/api/v1/scim/v2/Users?filter=userName%20eq%20%22managed%40example.com%22',
        headers=_scim_headers(token),
    )
    assert filtered.status_code == 200
    assert filtered.json()["totalResults"] == 1

    changed_identity = client.put(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=_scim_headers(token),
        json={
            "schemas": [SCIM_USER_SCHEMA],
            "userName": "other@example.com",
            "displayName": "Attempted Rebind",
            "active": True,
            "externalId": "person-77",
        },
    )
    assert changed_identity.status_code == 409

    deactivated = client.put(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=_scim_headers(token),
        json={
            "schemas": [SCIM_USER_SCHEMA],
            "userName": "managed@example.com",
            "displayName": "Managed Updated",
            "active": False,
            "externalId": "person-77",
        },
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["active"] is False

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        assert user is not None and session is not None
        assert user.role == UserRole.CLAIMS_MANAGER
        assert user.full_name == "Managed Updated"
        assert user.is_active is False
        assert session.revoked_at is not None
        assert session.revocation_reason == "scim_deprovisioned"

    deleted_again = client.delete(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=_scim_headers(token),
    )
    assert deleted_again.status_code == 204

    reactivated = client.put(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=_scim_headers(token),
        json={
            "schemas": [SCIM_USER_SCHEMA],
            "userName": "managed@example.com",
            "displayName": "Managed Updated",
            "active": True,
            "externalId": "person-77",
        },
    )
    assert reactivated.status_code == 200
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.is_active is True
        assert user.role == UserRole.CLAIMS_MANAGER


def test_grant_expiry_profile_rotation_and_cross_tenant_access_fail_closed() -> None:
    _, admin_a = _seed_actor(slug="tenant-a-t", email="admin-a@example.com")
    _, admin_b = _seed_actor(slug="tenant-b-t", email="admin-b@example.com")
    headers_a = _headers(admin_a)
    headers_b = _headers(admin_b)

    profile_a = _profile(headers_a, user_capability=True, name="A User Provisioner")
    token_a = _issue(headers_a, profile_a.json()["id"]).json()["token"]
    grant_a = _grant(headers_a, email="a-user@example.com")
    assert grant_a.status_code == 201

    with TestingSessionLocal() as db:
        grant_row = db.get(ScimUserProvisioningGrant, UUID(grant_a.json()["id"]))
        assert grant_row is not None
        grant_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    expired = _create_user(token_a, email="a-user@example.com")
    assert expired.status_code == 403

    fresh = _grant(headers_a, email="fresh@example.com")
    assert fresh.status_code == 201
    rotated_profile = _profile(headers_a, user_capability=True, name="A User Provisioner v2")
    assert rotated_profile.status_code == 201
    assert _create_user(token_a, email="fresh@example.com").status_code == 401

    token_a2 = _issue(headers_a, rotated_profile.json()["id"]).json()["token"]
    profile_b = _profile(headers_b, user_capability=True, name="B User Provisioner")
    token_b = _issue(headers_b, profile_b.json()["id"]).json()["token"]
    grant_b = _grant(headers_b, email="tenant-b@example.com")
    assert grant_b.status_code == 201
    created_b = _create_user(token_b, email="tenant-b@example.com")
    assert created_b.status_code == 201
    user_b = created_b.json()["id"]

    cross_tenant_read = client.get(
        f"/api/v1/scim/v2/Users/{user_b}",
        headers=_scim_headers(token_a2),
    )
    assert cross_tenant_read.status_code == 404
