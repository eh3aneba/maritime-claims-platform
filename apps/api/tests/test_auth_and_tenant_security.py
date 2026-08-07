from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.metadata import Base
from app.db.session import get_db
from app.main import app
from app.modules.claims.models import Claim
from app.modules.claims.security import get_claim_for_tenant
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel

TEST_PASSWORD = "Correct-Horse-Battery-2026"


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@event.listens_for(engine, "connect")
def register_sqlite_functions(dbapi_connection, connection_record) -> None:
    del connection_record
    dbapi_connection.create_function("char_length", 1, lambda value: len(value) if value is not None else None)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    client.cookies.clear()


def seed_identity_data() -> tuple[Organization, User, Organization, User]:
    with TestingSessionLocal() as db:
        org_a = Organization(name="Alpha Marine", slug="alpha")
        org_b = Organization(name="Beta Marine", slug="beta")
        db.add_all([org_a, org_b])
        db.flush()

        admin_a = User(
            organization_id=org_a.id,
            email="admin@example.com",
            full_name="Alpha Admin",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        handler_b = User(
            organization_id=org_b.id,
            email="handler@example.com",
            full_name="Beta Handler",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add_all([admin_a, handler_b])
        db.commit()
        db.refresh(org_a)
        db.refresh(admin_a)
        db.refresh(org_b)
        db.refresh(handler_b)
        return org_a, admin_a, org_b, handler_b


def test_login_and_me_use_organization_context() -> None:
    seed_identity_data()
    login = client.post(
        "/api/v1/auth/login",
        json={
            "organization_slug": "alpha",
            "email": "admin@example.com",
            "password": TEST_PASSWORD,
        },
    )
    assert login.status_code == 200
    body = login.json()
    assert body["user"]["email"] == "admin@example.com"
    assert body["user"]["role"] == "admin"
    assert body["access_token"]

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"


def test_same_email_can_exist_in_different_organizations_but_login_is_unambiguous() -> None:
    org_a, _, org_b, _ = seed_identity_data()
    with TestingSessionLocal() as db:
        db.add(
            User(
                organization_id=org_b.id,
                email="admin@example.com",
                full_name="Beta Same Email",
                password_hash=hash_password("Different-Password-2026"),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    wrong_org = client.post(
        "/api/v1/auth/login",
        json={
            "organization_slug": org_b.slug,
            "email": "admin@example.com",
            "password": TEST_PASSWORD,
        },
    )
    assert wrong_org.status_code == 401

    right_org = client.post(
        "/api/v1/auth/login",
        json={
            "organization_slug": org_a.slug,
            "email": "admin@example.com",
            "password": TEST_PASSWORD,
        },
    )
    assert right_org.status_code == 200


def test_admin_can_create_user_only_in_own_organization() -> None:
    org_a, _, _, _ = seed_identity_data()
    assert client.post(
        "/api/v1/auth/login",
        json={"organization_slug": "alpha", "email": "admin@example.com", "password": TEST_PASSWORD},
    ).status_code == 200

    response = client.post(
        "/api/v1/users",
        json={
            "email": "claims@example.com",
            "full_name": "Claims Handler",
            "password": "Another-Strong-Password-2026",
            "role": "claims_handler",
        },
    )
    assert response.status_code == 201
    assert response.json()["organization_id"] == str(org_a.id)

    with TestingSessionLocal() as db:
        from uuid import UUID
        created = db.get(User, UUID(response.json()["id"]))
        assert created is not None
        assert created.organization_id == org_a.id
        assert created.password_hash != "Another-Strong-Password-2026"


def test_claim_handler_cannot_create_users() -> None:
    seed_identity_data()
    assert client.post(
        "/api/v1/auth/login",
        json={"organization_slug": "beta", "email": "handler@example.com", "password": TEST_PASSWORD},
    ).status_code == 200

    response = client.post(
        "/api/v1/users",
        json={
            "email": "other@example.com",
            "full_name": "Other User",
            "password": "Another-Strong-Password-2026",
            "role": "claims_handler",
        },
    )
    assert response.status_code == 403


def test_database_membership_overrides_tampered_token_org_context() -> None:
    org_a, admin_a, org_b, _ = seed_identity_data()
    tampered_context_token = create_access_token(
        user_id=admin_a.id,
        organization_id=org_b.id,
        role=admin_a.role.value,
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tampered_context_token}"},
    )
    assert response.status_code == 401


def test_cross_tenant_claim_lookup_returns_nothing() -> None:
    org_a, admin_a, org_b, _ = seed_identity_data()
    with TestingSessionLocal() as db:
        vessel_b = Vessel(organization_id=org_b.id, name="MT BETA", imo_number="1234567")
        db.add(vessel_b)
        db.flush()
        claim_b = Claim(
            organization_id=org_b.id,
            vessel_id=vessel_b.id,
            handler_id=None,
            claim_reference="BETA-HM-2026-0001",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Turbocharger failure",
            currency="USD",
        )
        db.add(claim_b)
        db.commit()
        db.refresh(claim_b)

        assert get_claim_for_tenant(db, claim_id=claim_b.id, organization_id=org_b.id) is not None
        assert get_claim_for_tenant(db, claim_id=claim_b.id, organization_id=org_a.id) is None


def test_logout_clears_cookie() -> None:
    seed_identity_data()
    assert client.post(
        "/api/v1/auth/login",
        json={"organization_slug": "alpha", "email": "admin@example.com", "password": TEST_PASSWORD},
    ).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_database_role_overrides_role_claim_in_token() -> None:
    _, _, org_b, handler_b = seed_identity_data()
    token_with_forged_admin_role = create_access_token(
        user_id=handler_b.id,
        organization_id=org_b.id,
        role=UserRole.ADMIN.value,
    )
    response = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token_with_forged_admin_role}"},
        json={
            "email": "forged@example.com",
            "full_name": "Forged Admin Attempt",
            "password": "Another-Strong-Password-2026",
            "role": "admin",
        },
    )
    assert response.status_code == 403


def test_inactive_organization_invalidates_existing_token() -> None:
    org_a, admin_a, _, _ = seed_identity_data()
    token = create_access_token(user_id=admin_a.id, organization_id=org_a.id, role=admin_a.role.value)
    with TestingSessionLocal() as db:
        stored_org = db.get(Organization, org_a.id)
        stored_org.status = "inactive"
        db.commit()

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
