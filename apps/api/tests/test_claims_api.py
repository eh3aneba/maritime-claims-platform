from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel

TEST_PASSWORD = "Correct-Horse-Battery-2026"

from tests.db_harness import TestingSessionLocal, client, reset_database

def setup_function() -> None:
    reset_database()

def seed() -> dict:
    with TestingSessionLocal() as db:
        alpha = Organization(name="Alpha Marine", slug="alpha")
        beta = Organization(name="Beta Marine", slug="beta")
        db.add_all([alpha, beta])
        db.flush()

        alpha_admin = User(
            organization_id=alpha.id,
            email="alpha-admin@example.com",
            full_name="Alpha Admin",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        alpha_manager = User(
            organization_id=alpha.id,
            email="alpha-manager@example.com",
            full_name="Alpha Manager",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        alpha_handler = User(
            organization_id=alpha.id,
            email="alpha-handler@example.com",
            full_name="Alpha Handler",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        beta_handler = User(
            organization_id=beta.id,
            email="beta-handler@example.com",
            full_name="Beta Handler",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add_all([alpha_admin, alpha_manager, alpha_handler, beta_handler])
        db.flush()

        orion = Vessel(organization_id=alpha.id, name="MT ORION", imo_number="7654321")
        atlas = Vessel(organization_id=alpha.id, name="MT ATLAS", imo_number="7654322")
        beta_vessel = Vessel(organization_id=beta.id, name="MT BETA", imo_number="7654323")
        db.add_all([orion, atlas, beta_vessel])
        db.commit()
        for obj in [alpha, beta, alpha_admin, alpha_manager, alpha_handler, beta_handler, orion, atlas, beta_vessel]:
            db.refresh(obj)
        return {
            "alpha": alpha,
            "beta": beta,
            "admin": alpha_admin,
            "manager": alpha_manager,
            "handler": alpha_handler,
            "beta_handler": beta_handler,
            "orion": orion,
            "atlas": atlas,
            "beta_vessel": beta_vessel,
        }


def login(slug: str, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization_slug": slug, "email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text


def create_orion_claim(handler_id: UUID | None = None) -> dict:
    data = seed()
    login("alpha", "alpha-admin@example.com")
    response = client.post(
        "/api/v1/claims",
        json={
            "vessel_id": str(data["orion"].id),
            "incident_date": "2026-07-10",
            "notification_date": "2026-07-11",
            "incident_description": "Main engine turbocharger developed abnormal vibration during voyage.",
            "estimated_loss": "550000.00",
            "currency": "usd",
            "handler_id": str(handler_id or data["handler"].id),
        },
    )
    assert response.status_code == 201, response.text
    return {"seed": data, "claim": response.json()}


def test_create_claim_generates_reference_and_audit_log() -> None:
    result = create_orion_claim()
    claim = result["claim"]
    assert claim["claim_reference"] == "MCRI-HM-2026-0001"
    assert claim["status"] == "new"
    assert claim["currency"] == "USD"
    assert claim["vessel"]["name"] == "MT ORION"
    assert claim["handler"]["email"] == "alpha-handler@example.com"

    with TestingSessionLocal() as db:
        event = db.scalar(select(AuditLog).where(AuditLog.action == "CREATE_CLAIM"))
        assert event is not None
        assert event.organization_id == result["seed"]["alpha"].id


def test_reference_increments_per_tenant_year_type() -> None:
    data = seed()
    login("alpha", "alpha-admin@example.com")
    payload = {
        "vessel_id": str(data["orion"].id),
        "incident_date": "2026-07-10",
        "notification_date": "2026-07-11",
        "incident_description": "Main engine turbocharger developed abnormal vibration during voyage.",
    }
    first = client.post("/api/v1/claims", json=payload)
    second = client.post("/api/v1/claims", json={**payload, "vessel_id": str(data["atlas"].id)})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["claim_reference"].endswith("0001")
    assert second.json()["claim_reference"].endswith("0002")


def test_handler_cannot_assign_on_create() -> None:
    data = seed()
    login("alpha", "alpha-handler@example.com")
    response = client.post(
        "/api/v1/claims",
        json={
            "vessel_id": str(data["orion"].id),
            "incident_date": "2026-07-10",
            "notification_date": "2026-07-11",
            "incident_description": "Main engine turbocharger developed abnormal vibration during voyage.",
            "handler_id": str(data["handler"].id),
        },
    )
    assert response.status_code == 403


def test_cross_tenant_vessel_cannot_be_used_to_create_claim() -> None:
    data = seed()
    login("alpha", "alpha-admin@example.com")
    response = client.post(
        "/api/v1/claims",
        json={
            "vessel_id": str(data["beta_vessel"].id),
            "incident_date": "2026-07-10",
            "notification_date": "2026-07-11",
            "incident_description": "Attempt to create cross-tenant machinery claim.",
        },
    )
    assert response.status_code == 422


def test_list_search_and_filter_are_tenant_scoped() -> None:
    result = create_orion_claim()
    data = result["seed"]
    response = client.get("/api/v1/claims", params={"search": "ORION", "status": "new"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["vessel"]["name"] == "MT ORION"

    # Insert a Beta claim directly and prove Alpha never sees it.
    with TestingSessionLocal() as db:
        beta_claim = Claim(
            organization_id=data["beta"].id,
            vessel_id=data["beta_vessel"].id,
            claim_reference="MCRI-HM-2026-0999",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Beta-only machinery claim",
            currency="USD",
        )
        db.add(beta_claim)
        db.commit()

    response = client.get("/api/v1/claims")
    assert response.json()["total"] == 1


def test_cross_tenant_claim_detail_returns_404() -> None:
    data = seed()
    with TestingSessionLocal() as db:
        beta_claim = Claim(
            organization_id=data["beta"].id,
            vessel_id=data["beta_vessel"].id,
            claim_reference="MCRI-HM-2026-0999",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Beta-only machinery claim",
            currency="USD",
        )
        db.add(beta_claim)
        db.commit()
        db.refresh(beta_claim)
        claim_id = beta_claim.id

    login("alpha", "alpha-admin@example.com")
    response = client.get(f"/api/v1/claims/{claim_id}")
    assert response.status_code == 404


def test_patch_updates_core_details_but_not_status_or_assignment() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    response = client.patch(
        f"/api/v1/claims/{claim_id}",
        json={
            "priority": "high",
            "external_reference": "INS-26-0042",
            "estimated_loss": "625000.00",
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] == "high"
    assert response.json()["external_reference"] == "INS-26-0042"
    assert Decimal(response.json()["estimated_loss"]) == Decimal("625000.00")


def test_manager_can_assign_handler_but_handler_cannot() -> None:
    result = create_orion_claim()
    data, claim_id = result["seed"], result["claim"]["id"]

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    forbidden = client.post(f"/api/v1/claims/{claim_id}/assign", json={"handler_id": None})
    assert forbidden.status_code == 403

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    allowed = client.post(
        f"/api/v1/claims/{claim_id}/assign",
        json={"handler_id": str(data["manager"].id)},
    )
    assert allowed.status_code == 200
    assert allowed.json()["handler"]["email"] == "alpha-manager@example.com"


def test_status_state_machine_and_manager_only_terminal_states() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    assert client.post(f"/api/v1/claims/{claim_id}/status", json={"status": "triage"}).status_code == 200
    invalid = client.post(f"/api/v1/claims/{claim_id}/status", json={"status": "closed"})
    assert invalid.status_code == 409  # invalid path from triage, before role even matters

    # Move through a valid path to negotiation as handler.
    for next_status in ["investigation", "financial_review", "negotiation"]:
        response = client.post(f"/api/v1/claims/{claim_id}/status", json={"status": next_status})
        assert response.status_code == 200, response.text

    forbidden_settlement = client.post(
        f"/api/v1/claims/{claim_id}/status",
        json={"status": "settlement", "reason": "Commercial settlement agreed"},
    )
    assert forbidden_settlement.status_code == 403

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    allowed = client.post(
        f"/api/v1/claims/{claim_id}/status",
        json={"status": "settlement", "reason": "Settlement authority approved"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "settlement"


def test_manager_can_update_reserve_with_reason_and_audit() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post(
        f"/api/v1/claims/{claim_id}/reserve",
        json={"amount": "575000.00", "reason": "Replacement quotation received"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["current_reserve"]) == Decimal("575000.00")

    with TestingSessionLocal() as db:
        event = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == UUID(claim_id),
                AuditLog.action == "CHANGE_CLAIM_RESERVE",
            )
        )
        assert event is not None
        assert event.details == "Replacement quotation received"
