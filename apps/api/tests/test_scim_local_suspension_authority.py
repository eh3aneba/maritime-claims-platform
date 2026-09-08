from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.scim_models import ScimUserBinding
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"


def setup_function() -> None:
    reset_database()


def _seed_admin() -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name="SCIM Local Authority", slug="scim-local-authority")
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email="admin-local-authority@example.com",
            full_name="Local Authority Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        return org.id, admin.id


def _admin_headers(admin_id: UUID) -> dict[str, str]:
    with TestingSessionLocal() as db:
        admin = db.get(User, admin_id)
        assert admin is not None
        session = create_auth_session(db, user=admin)
        db.commit()
        token = create_access_token(
            user_id=admin.id,
            organization_id=admin.organization_id,
            role=admin.role.value,
            session_id=session.id,
            identity_source=session.identity_source,
            auth_method=session.auth_method,
        )
    return {"Authorization": f"Bearer {token}"}


def test_scim_cannot_override_local_user_suspension() -> None:
    org_id, admin_id = _seed_admin()
    headers = _admin_headers(admin_id)

    profile = client.post(
        "/api/v1/auth/scim-provisioning/profiles",
        headers=headers,
        json={
            "client_name": "Local Authority Provisioner",
            "enabled": True,
            "token_ttl_days": 30,
            "user_provisioning_enabled": True,
        },
    )
    assert profile.status_code == 201, profile.text

    issued = client.post(
        f"/api/v1/auth/scim-provisioning/profiles/{profile.json()['id']}/tokens",
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    scim_headers = {"Authorization": f"Bearer {issued.json()['token']}"}

    grant = client.post(
        "/api/v1/auth/scim-provisioning/user-grants",
        headers=headers,
        json={
            "email": "managed-local-suspension@example.com",
            "role": "claims_handler",
            "ttl_hours": 24,
        },
    )
    assert grant.status_code == 201, grant.text

    created = client.post(
        "/api/v1/scim/v2/Users",
        headers=scim_headers,
        json={
            "schemas": [SCIM_USER_SCHEMA],
            "userName": "managed-local-suspension@example.com",
            "displayName": "Managed Local Suspension",
            "active": True,
            "externalId": "local-authority-1",
        },
    )
    assert created.status_code == 201, created.text
    user_id = UUID(created.json()["id"])

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        binding = db.query(ScimUserBinding).filter(ScimUserBinding.user_id == user_id).one()
        assert user is not None
        assert user.organization_id == org_id
        assert binding.deactivated_at is None
        user.is_active = False
        db.commit()

    attempted_reactivation = client.put(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=scim_headers,
        json={
            "schemas": [SCIM_USER_SCHEMA],
            "userName": "managed-local-suspension@example.com",
            "displayName": "Managed Local Suspension",
            "active": True,
            "externalId": "local-authority-1",
        },
    )
    assert attempted_reactivation.status_code == 403

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        binding = db.query(ScimUserBinding).filter(ScimUserBinding.user_id == user_id).one()
        assert user is not None
        assert user.is_active is False
        assert user.role == UserRole.CLAIMS_HANDLER
        assert binding.deactivated_at is None
