from app.core.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def _seed():
    reset_database()
    with TestingSessionLocal() as db:
        org_a = Organization(name="Alpha Marine", slug="alpha")
        org_b = Organization(name="Beta Marine", slug="beta")
        db.add_all([org_a, org_b])
        db.flush()
        a = User(organization_id=org_a.id, email="a@example.com", full_name="Alpha User", password_hash=hash_password("a-very-strong-password"), role=UserRole.CLAIMS_HANDLER)
        b = User(organization_id=org_b.id, email="b@example.com", full_name="Beta User", password_hash=hash_password("another-strong-password"), role=UserRole.CLAIMS_HANDLER)
        db.add_all([a, b])
        db.commit()


def _login(org, email, password):
    response = client.post("/api/v1/auth/login", json={"organization_slug": org, "email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_vessels_are_tenant_scoped_and_creatable():
    _seed()
    alpha = _login("alpha", "a@example.com", "a-very-strong-password")
    beta = _login("beta", "b@example.com", "another-strong-password")

    created = client.post("/api/v1/vessels", headers=alpha, json={"name": "MT ORION", "imo_number": "1234567", "vessel_type": "Tanker"})
    assert created.status_code == 201
    assert created.json()["name"] == "MT ORION"

    alpha_list = client.get("/api/v1/vessels", headers=alpha)
    beta_list = client.get("/api/v1/vessels", headers=beta)
    assert alpha_list.json()["total"] == 1
    assert beta_list.json()["total"] == 0


def test_duplicate_imo_is_rejected_within_tenant():
    _seed()
    headers = _login("alpha", "a@example.com", "a-very-strong-password")
    payload = {"name": "MT ORION", "imo_number": "1234567"}
    assert client.post("/api/v1/vessels", headers=headers, json=payload).status_code == 201
    assert client.post("/api/v1/vessels", headers=headers, json=payload).status_code == 409
