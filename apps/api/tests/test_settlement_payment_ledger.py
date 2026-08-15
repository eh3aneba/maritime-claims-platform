from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_adjustment_controls import _seed_cost_schedule
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _approved_adjustment() -> tuple[str, dict]:
    claim_id, _ = _seed_cost_schedule()
    statement = client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).json()
    for line in statement["lines"]:
        response = client.patch(
            f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{line['id']}",
            json={"treatment": "included", "basis": "particular_average",
                  "considered_amount": line["claimed_amount"]},
        )
        assert response.status_code == 200, response.text
    assert client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit").status_code == 200
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/approve",
        json={"note": "Approved source adjustment for settlement control."},
    )
    assert approved.status_code == 200, approved.text
    return claim_id, approved.json()


def test_settlement_and_payment_require_human_separation_and_preserve_hashes() -> None:
    claim_id, adjustment = _approved_adjustment()
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    created = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements",
        json={"adjustment_statement_id": adjustment["id"], "title": "Without Prejudice Final Settlement",
              "settlement_type": "final", "amount": "1000.00",
              "terms": "Full and final settlement subject to signed release.",
              "release_required": True, "without_prejudice": True},
    )
    assert created.status_code == 201, created.text
    settlement = created.json()
    assert settlement["currency"] == "USD"
    assert settlement["source_adjustment_hash"] == adjustment["content_hash"]
    assert client.post(f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement['id']}/submit").status_code == 200

    own_review = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement['id']}/approve",
        json={"note": "Creator must not self-approve."},
    )
    assert own_review.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement['id']}/approve",
        json={"note": "Amount and written terms reviewed by Claims Manager."},
    )
    assert approved.status_code == 200, approved.text
    assert len(approved.json()["content_hash"]) == 64
    immutable = client.patch(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement['id']}",
        json={"amount": "900.00"},
    )
    assert immutable.status_code == 409
    accepted = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement['id']}/disposition/record",
        json={"disposition": "accepted", "note": "Signed acceptance recorded from the external claim file."},
    )
    assert accepted.status_code == 200, accepted.text

    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    payment = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments",
        json={"settlement_id": settlement["id"], "payee": "Orion Shipowning Ltd",
              "amount": "700.00", "purpose": "First controlled settlement instalment."},
    )
    assert payment.status_code == 201, payment.text
    payment_id = payment.json()["id"]
    assert client.post(f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/submit").status_code == 200
    over_cap = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments",
        json={"settlement_id": settlement["id"], "payee": "Orion Shipowning Ltd",
              "amount": "400.00", "purpose": "Would exceed settlement cap."},
    )
    assert over_cap.status_code == 422

    with TestingSessionLocal() as db:
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        second = User(organization_id=manager.organization_id, email="alpha-manager-two@example.com",
                      full_name="Alpha Manager Two", password_hash=hash_password(TEST_PASSWORD),
                      role=UserRole.CLAIMS_MANAGER, is_active=True)
        db.add(second); db.commit()

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    first = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/approve",
        json={"note": "First independent authorization."},
    )
    assert first.status_code == 200 and first.json()["status"] == "first_approved"
    duplicate = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/approve",
        json={"note": "Same reviewer must not complete authorization."},
    )
    assert duplicate.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-manager-two@example.com")
    second = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/approve",
        json={"note": "Second independent authorization."},
    )
    assert second.status_code == 200 and second.json()["status"] == "authorized"
    assert len(second.json()["content_hash"]) == 64
    unconfirmed = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/record-paid",
        json={"confirm_paid_externally": False, "channel": "bank_transfer",
              "external_reference": "BANK-2026-001", "value_date": "2026-08-15"},
    )
    assert unconfirmed.status_code == 422
    paid = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/record-paid",
        json={"confirm_paid_externally": True, "channel": "bank_transfer",
              "external_reference": "BANK-2026-001", "value_date": "2026-08-15",
              "note": "Execution evidence checked outside the platform."},
    )
    assert paid.status_code == 200 and paid.json()["status"] == "paid_externally"

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == UUID(payment_id))))
        assert {"CREATE_PAYMENT_AUTHORIZATION", "FIRST_APPROVE_PAYMENT_AUTHORIZATION",
                "SECOND_APPROVE_PAYMENT_AUTHORIZATION", "RECORD_PAYMENT_PAID_EXTERNALLY"}.issubset(actions)


def test_settlement_amount_and_tenant_scope_are_enforced() -> None:
    claim_id, adjustment = _approved_adjustment()
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    excessive = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements",
        json={"adjustment_statement_id": adjustment["id"], "title": "Excess proposal",
              "settlement_type": "final", "amount": "99999.00", "terms": "Invalid excess."},
    )
    assert excessive.status_code == 422
    client.cookies.clear(); login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/settlement-ledger").status_code == 404
