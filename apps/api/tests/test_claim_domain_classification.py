from uuid import UUID

from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from app.modules.claim_intelligence.domain_catalog import DOMAIN_CATALOG_VERSION
from app.modules.claim_intelligence.models import ClaimDomainClassification, ClaimIntelligenceSnapshot
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.rules.models import RuleRun
from app.modules.tasks.models import ClaimTask
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _classification_payload(**overrides) -> dict:
    payload = {
        "incident_code": "machinery_failure",
        "component_code": "turbocharger",
        "failure_mode": "bearing damage",
        "note": "Confirmed by the claim handler after reviewing the incident record.",
        "confirm_classification": True,
    }
    payload.update(overrides)
    return payload


def test_domain_catalog_exposes_bounded_non_authoritative_taxonomy() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    response = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-catalog")
    assert response.status_code == 200, response.text
    catalog = response.json()

    assert catalog["catalog_version"] == DOMAIN_CATALOG_VERSION
    assert catalog["non_authoritative"] is True
    assert catalog["human_classification_required"] is True
    assert catalog["automatic_claim_decision"] is False
    assert {item["code"] for item in catalog["incidents"]} == {
        "machinery_failure",
        "collision",
        "grounding",
        "fire",
        "cargo_damage",
        "pollution",
        "salvage",
        "general_average",
    }
    assert {item["code"] for item in catalog["machinery_components"]} == {
        "main_engine",
        "turbocharger",
        "generator",
        "propeller",
        "steering_gear",
        "boiler",
        "pump",
    }


def test_human_classification_is_append_only_and_hash_chained() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    first_response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert first_response.status_code == 201, first_response.text
    first = first_response.json()
    assert first["classification_number"] == 1
    assert first["catalog_version"] == DOMAIN_CATALOG_VERSION
    assert first["incident_code"] == "machinery_failure"
    assert first["component_code"] == "turbocharger"
    assert first["previous_classification_hash"] is None
    assert first["supersedes_classification_id"] is None
    assert len(first["classification_hash"]) == 64

    second_response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(
            component_code="main_engine",
            failure_mode="lubrication system damage",
            note="Reclassified after the handler reviewed the later technical evidence package.",
        ),
    )
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    assert second["classification_number"] == 2
    assert second["supersedes_classification_id"] == first["id"]
    assert second["previous_classification_hash"] == first["classification_hash"]
    assert second["classification_hash"] != first["classification_hash"]

    current = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-classification")
    assert current.status_code == 200
    assert current.json()["id"] == second["id"]

    history = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-classifications")
    assert history.status_code == 200
    assert [item["classification_number"] for item in history.json()] == [2, 1]

    with TestingSessionLocal() as db:
        rows = list(
            db.scalars(
                select(ClaimDomainClassification)
                .where(ClaimDomainClassification.claim_id == UUID(claim_id))
                .order_by(ClaimDomainClassification.classification_number.asc())
            )
        )
        assert len(rows) == 2
        assert rows[0].classification_hash == first["classification_hash"]
        assert rows[1].previous_classification_hash == rows[0].classification_hash


def test_classification_requires_confirmation_and_compatible_taxonomy() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    no_confirmation = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(confirm_classification=False),
    )
    assert no_confirmation.status_code == 422
    assert "confirmation" in no_confirmation.json()["detail"].lower()

    incompatible = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(
            incident_code="collision",
            component_code="turbocharger",
            failure_mode="bearing damage",
            note="Handler confirms collision context but supplied an incompatible component.",
        ),
    )
    assert incompatible.status_code == 422
    assert "compatible" in incompatible.json()["detail"].lower()

    unknown = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(
            incident_code="unknown_casualty",
            component_code=None,
            failure_mode=None,
            note="Handler attempted to use a domain code outside the governed catalog.",
        ),
    )
    assert unknown.status_code == 422
    assert "unknown" in unknown.json()["detail"].lower()

    with TestingSessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(ClaimDomainClassification))
        assert count == 0


def test_classification_has_zero_autonomous_claim_decision_side_effects() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    with TestingSessionLocal() as db:
        claim_before = db.get(Claim, UUID(claim_id))
        assert claim_before is not None
        claim_type_before = claim_before.claim_type
        status_before = claim_before.status

    response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert response.status_code == 201, response.text

    with TestingSessionLocal() as db:
        claim_after = db.get(Claim, UUID(claim_id))
        assert claim_after is not None
        assert claim_after.claim_type == claim_type_before
        assert claim_after.status == status_before
        assert db.scalar(select(func.count()).select_from(ClaimIntelligenceSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(RuleRun)) == 0
        assert db.scalar(select(func.count()).select_from(ClaimFact)) == 0
        assert db.scalar(select(func.count()).select_from(ClaimTask)) == 0
        event = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.organization_id == claim_after.organization_id,
                AuditLog.action == "CLASSIFY_CLAIM_DOMAIN",
            )
            .order_by(AuditLog.created_at.desc())
        )
        assert event is not None
        assert event.new_values["incident_code"] == "machinery_failure"
        assert "classification_note" not in event.new_values
        assert "classification_hash" not in event.new_values


def test_domain_classification_is_tenant_scoped() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    created = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert created.status_code == 201, created.text

    client.cookies.clear()
    login("beta", "beta-handler@example.com")

    assert client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-catalog").status_code == 404
    assert client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-classification").status_code == 404
    assert client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-classifications").status_code == 404
    cross_tenant_write = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert cross_tenant_write.status_code == 404
