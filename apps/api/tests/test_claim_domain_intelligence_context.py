from uuid import UUID

from sqlalchemy import func, select

from app.modules.claim_intelligence.models import ClaimIntelligenceSnapshot
from app.modules.rules.models import RuleEvaluationRun
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _classify(claim_id: str, **overrides) -> dict:
    payload = {
        "incident_code": "machinery_failure",
        "component_code": "turbocharger",
        "failure_mode": "bearing damage",
        "note": "Sensitive handler classification note that must not surface in intelligence output.",
        "confirm_classification": True,
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _build(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/intelligence/build")
    assert response.status_code == 201, response.text
    return response.json()


def test_build_without_classification_remains_valid_and_has_no_domain_context() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    snapshot = _build(claim_id)

    assert snapshot["engine_version"] == "12A.1"
    assert snapshot["summary"]["domain_context_integration_version"] == "16.1-B.1"
    assert snapshot["summary"]["domain_classification_present"] is False
    assert snapshot["summary"]["domain_context_count"] == 0
    assert snapshot["summary"]["domain_classification_drives_rules"] is False
    assert all(item["category"] != "domain_context" for item in snapshot["items"])


def test_explicit_build_consumes_current_classification_as_bounded_source_linked_context() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    classification = _classify(claim_id)

    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClaimIntelligenceSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(RuleEvaluationRun)) == 0

    snapshot = _build(claim_id)
    domain_items = [item for item in snapshot["items"] if item["category"] == "domain_context"]
    assert len(domain_items) == 1
    item = domain_items[0]

    assert item["title"] == "Claim domain: Machinery Failure"
    assert "Turbocharger" in item["description"]
    assert "bearing damage" in item["description"]
    assert "Sensitive handler classification note" not in str(item)
    assert item["action_type"] is None
    assert item["suggested_action"] is None
    assert item["related_entity_type"] == "claim_domain_classification"
    assert item["related_entity_id"] == classification["id"]
    assert len(item["source_refs"]) == 1
    source = item["source_refs"][0]
    assert source["kind"] == "claim_domain_classification"
    assert source["id"] == classification["id"]
    assert source["catalog_version"] == classification["catalog_version"]
    assert source["classification_number"] == 1
    assert source["classification_hash"] == classification["classification_hash"]
    assert "note" not in source
    assert snapshot["summary"]["domain_classification_present"] is True
    assert snapshot["summary"]["domain_context_count"] == 1
    assert snapshot["summary"]["domain_classification_drives_rules"] is False


def test_reclassification_changes_source_identity_only_on_next_explicit_build() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    first_classification = _classify(claim_id)
    first = _build(claim_id)

    second_classification = _classify(
        claim_id,
        incident_code="collision",
        component_code=None,
        failure_mode=None,
        note="Handler reclassified the casualty as collision after later evidence review.",
    )

    with TestingSessionLocal() as db:
        snapshots_before_rebuild = list(
            db.scalars(
                select(ClaimIntelligenceSnapshot)
                .where(ClaimIntelligenceSnapshot.claim_id == UUID(claim_id))
                .order_by(ClaimIntelligenceSnapshot.snapshot_version.asc())
            )
        )
        assert len(snapshots_before_rebuild) == 1

    second = _build(claim_id)

    assert first_classification["id"] != second_classification["id"]
    assert second["id"] != first["id"]
    assert second["snapshot_version"] == first["snapshot_version"] + 1
    assert second["source_state_hash"] != first["source_state_hash"]
    domain_item = next(item for item in second["items"] if item["category"] == "domain_context")
    assert domain_item["title"] == "Claim domain: Collision"
    assert domain_item["related_entity_id"] == second_classification["id"]
    assert "reclassified" not in str(domain_item).lower()


def test_domain_context_never_creates_an_actionable_intelligence_item() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _classify(
        claim_id,
        incident_code="general_average",
        component_code=None,
        failure_mode=None,
        note="Handler confirms General Average context for controlled intelligence display only.",
    )

    snapshot = _build(claim_id)
    domain_item = next(item for item in snapshot["items"] if item["category"] == "domain_context")

    assert domain_item["action_type"] is None
    assert domain_item["suggested_action"] is None
    assert domain_item["severity"] == "info"
    assert snapshot["summary"]["coverage_decision_made"] is False
    assert snapshot["summary"]["causation_decision_made"] is False
    assert snapshot["summary"]["liability_decision_made"] is False
    assert snapshot["summary"]["recoverability_decision_made"] is False
    assert snapshot["summary"]["domain_classification_drives_rules"] is False
