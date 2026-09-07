from uuid import UUID

from sqlalchemy import func, select

from app.modules.claim_intelligence.domain_catalog import INCIDENT_DOMAINS
from app.modules.claim_intelligence.domain_playbook import (
    DOMAIN_PLAYBOOK_REGISTRY_VERSION,
    DOMAIN_PLAYBOOKS,
    domain_playbook_registry_hash,
    get_domain_playbook,
)
from app.modules.claim_intelligence.models import ClaimIntelligenceSnapshot
from app.modules.claims.facts import ClaimFact
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RuleEvaluationRun
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
        "note": "Handler confirms the bounded incident context after reviewing the available casualty record.",
        "confirm_classification": True,
    }
    payload.update(overrides)
    return payload


def _authority_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            "rule_runs": db.scalar(select(func.count()).select_from(RuleEvaluationRun)) or 0,
            "requirements": db.scalar(select(func.count()).select_from(ClaimDocumentRequirement)) or 0,
            "issues": db.scalar(select(func.count()).select_from(ClaimIssue)) or 0,
            "facts": db.scalar(select(func.count()).select_from(ClaimFact)) or 0,
            "tasks": db.scalar(select(func.count()).select_from(ClaimTask)) or 0,
            "snapshots": db.scalar(select(func.count()).select_from(ClaimIntelligenceSnapshot)) or 0,
        }


def test_playbook_registry_is_complete_unique_and_deterministic() -> None:
    catalog_codes = {str(item["code"]) for item in INCIDENT_DOMAINS}
    playbook_codes = [str(item["incident_code"]) for item in DOMAIN_PLAYBOOKS]

    assert set(playbook_codes) == catalog_codes
    assert len(playbook_codes) == len(set(playbook_codes)) == 8
    assert DOMAIN_PLAYBOOK_REGISTRY_VERSION == "16.2-A.1"

    first_hash = domain_playbook_registry_hash()
    second_hash = domain_playbook_registry_hash()
    assert first_hash == second_hash
    assert len(first_hash) == 64

    for code in catalog_codes:
        playbook = get_domain_playbook(code)
        assert playbook["incident_code"] == code
        assert playbook["title"]
        assert playbook["objective"]
        assert playbook["investigation_tracks"]
        assert playbook["evidence_prompts"]
        assert playbook["review_topics"]


def test_unclassified_claim_returns_bounded_preview_with_zero_side_effects() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    before = _authority_counts()

    response = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-playbook-preview")
    assert response.status_code == 200, response.text
    preview = response.json()

    assert preview["registry_version"] == DOMAIN_PLAYBOOK_REGISTRY_VERSION
    assert len(preview["registry_hash"]) == 64
    assert preview["classification_required"] is True
    assert preview["non_authoritative"] is True
    assert preview["read_only_preview"] is True
    assert preview["automatic_rule_execution"] is False
    assert preview["automatic_requirement_activation"] is False
    assert preview["automatic_task_creation"] is False
    assert preview["automatic_claim_decision"] is False
    assert preview["source_ref"] is None
    assert preview["classification_context"] is None
    assert preview["playbook"] is None
    assert _authority_counts() == before


def test_machinery_preview_is_source_linked_and_excludes_classification_note() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    note = "Handler confirms machinery failure after reviewing the controlled technical casualty evidence."
    classified = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(note=note),
    )
    assert classified.status_code == 201, classified.text
    classification = classified.json()
    before = _authority_counts()

    response = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-playbook-preview")
    assert response.status_code == 200, response.text
    preview = response.json()

    assert preview["classification_required"] is False
    assert preview["source_ref"] == {
        "kind": "claim_domain_classification",
        "id": classification["id"],
        "catalog_version": classification["catalog_version"],
        "classification_number": classification["classification_number"],
        "classification_hash": classification["classification_hash"],
    }
    assert preview["classification_context"] == {
        "incident_code": "machinery_failure",
        "incident_title": "Machinery Failure",
        "component_code": "turbocharger",
        "component_title": "Turbocharger",
        "failure_mode": "bearing damage",
    }
    assert preview["playbook"]["incident_code"] == "machinery_failure"
    assert "TECH-001" in preview["playbook"]["contextual_rule_ids"]
    assert any("PMS" in item for item in preview["playbook"]["evidence_prompts"])
    serialized = response.text
    assert "classification_note" not in serialized
    assert note not in serialized
    assert _authority_counts() == before


def test_reclassification_changes_preview_identity_without_building_or_running_rules() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    first = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert first.status_code == 201, first.text
    first_preview = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-playbook-preview")
    assert first_preview.status_code == 200
    first_body = first_preview.json()

    second = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(
            incident_code="collision",
            component_code=None,
            failure_mode=None,
            note="Handler reclassifies the casualty as collision after reviewing the later navigation evidence package.",
        ),
    )
    assert second.status_code == 201, second.text
    before_preview = _authority_counts()

    second_preview = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-playbook-preview")
    assert second_preview.status_code == 200, second_preview.text
    second_body = second_preview.json()

    assert second_body["source_ref"]["id"] != first_body["source_ref"]["id"]
    assert second_body["source_ref"]["classification_hash"] != first_body["source_ref"]["classification_hash"]
    assert second_body["source_ref"]["classification_number"] == 2
    assert second_body["classification_context"]["incident_code"] == "collision"
    assert second_body["classification_context"]["component_code"] is None
    assert second_body["playbook"]["incident_code"] == "collision"
    assert second_body["playbook"]["title"] == "Collision Investigation Preview"
    assert second_body["playbook"]["evidence_prompts"] != first_body["playbook"]["evidence_prompts"]
    assert not any("PMS" in item for item in second_body["playbook"]["evidence_prompts"])
    assert _authority_counts() == before_preview

    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClaimIntelligenceSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(RuleEvaluationRun)) == 0
        assert db.scalar(select(func.count()).select_from(ClaimDocumentRequirement)) == 0
        assert db.scalar(select(func.count()).select_from(ClaimIssue)) == 0
        assert db.scalar(select(func.count()).select_from(ClaimTask)) == 0


def test_playbook_preview_is_tenant_scoped() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    classified = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert classified.status_code == 201, classified.text

    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    response = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-playbook-preview")
    assert response.status_code == 404
