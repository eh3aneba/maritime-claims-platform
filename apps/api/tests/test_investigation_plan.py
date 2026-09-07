from sqlalchemy import func, select

from app.modules.claim_intelligence.models import ClaimIntelligenceSnapshot, ClaimInvestigationPlan
from app.modules.claims.facts import ClaimFact
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RuleEvaluationRun
from app.modules.tasks.models import ClaimTask, DocumentRequestBatch
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _classification_payload(**overrides) -> dict:
    payload = {
        "incident_code": "machinery_failure",
        "component_code": "turbocharger",
        "failure_mode": "bearing damage",
        "note": "Handler confirms machinery failure after reviewing the controlled casualty evidence package.",
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
            "request_batches": db.scalar(select(func.count()).select_from(DocumentRequestBatch)) or 0,
            "snapshots": db.scalar(select(func.count()).select_from(ClaimIntelligenceSnapshot)) or 0,
        }


def _live_preview(claim_id: str) -> dict:
    response = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-playbook-preview")
    assert response.status_code == 200, response.text
    return response.json()


def _adoption_payload(preview: dict, **overrides) -> dict:
    payload = {
        "registry_version": preview["registry_version"],
        "registry_hash": preview["registry_hash"],
        "classification_id": preview["source_ref"]["id"],
        "classification_hash": preview["source_ref"]["classification_hash"],
        "investigation_tracks": [preview["playbook"]["investigation_tracks"][0]],
        "evidence_prompts": [preview["playbook"]["evidence_prompts"][0]],
        "review_topics": [],
        "note": "Handler adopts this bounded investigation plan after reviewing the current governed playbook.",
        "confirm_adoption": True,
    }
    payload.update(overrides)
    return payload


def test_plan_adoption_requires_current_human_classification() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    before = _authority_counts()
    response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan",
        json={
            "registry_version": "16.2-A.1",
            "registry_hash": "a" * 64,
            "classification_id": "00000000-0000-0000-0000-000000000001",
            "classification_hash": "b" * 64,
            "investigation_tracks": ["Some item"],
            "evidence_prompts": [],
            "review_topics": [],
            "note": "Handler explicitly attempts adoption only after reviewing a governed current source.",
            "confirm_adoption": True,
        },
    )
    assert response.status_code == 409
    assert "classification" in response.json()["detail"].lower()
    assert _authority_counts() == before


def test_valid_plan_adoption_is_immutable_source_linked_and_has_zero_authority_side_effects() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    classified = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert classified.status_code == 201, classified.text
    preview = _live_preview(claim_id)
    before = _authority_counts()

    response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan",
        json=_adoption_payload(preview),
    )
    assert response.status_code == 201, response.text
    plan = response.json()

    assert plan["plan_number"] == 1
    assert plan["classification_id"] == preview["source_ref"]["id"]
    assert plan["classification_hash"] == preview["source_ref"]["classification_hash"]
    assert plan["registry_version"] == preview["registry_version"]
    assert plan["registry_hash"] == preview["registry_hash"]
    assert plan["incident_code"] == "machinery_failure"
    assert plan["component_code"] == "turbocharger"
    assert plan["source_current"] is True
    assert plan["non_authoritative"] is True
    assert plan["automatic_rule_execution"] is False
    assert plan["automatic_requirement_activation"] is False
    assert plan["automatic_task_creation"] is False
    assert plan["automatic_claim_decision"] is False
    assert plan["investigation_tracks"] == [preview["playbook"]["investigation_tracks"][0]]
    assert plan["evidence_prompts"] == [preview["playbook"]["evidence_prompts"][0]]
    assert plan["contextual_rule_ids"] == preview["playbook"]["contextual_rule_ids"]
    assert len(plan["adoption_key_hash"]) == 64
    assert len(plan["plan_hash"]) == 64
    assert _authority_counts() == before


def test_plan_rejects_stale_source_and_noncanonical_selection() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    first = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert first.status_code == 201
    stale_preview = _live_preview(claim_id)

    changed = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(
            incident_code="collision",
            component_code=None,
            failure_mode=None,
            note="Handler reclassifies the casualty as collision after reviewing later navigation evidence.",
        ),
    )
    assert changed.status_code == 201
    before = _authority_counts()

    stale = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan",
        json=_adoption_payload(stale_preview),
    )
    assert stale.status_code == 409
    assert "classification changed" in stale.json()["detail"].lower()

    current = _live_preview(claim_id)
    invalid = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan",
        json=_adoption_payload(current, investigation_tracks=["Invented autonomous investigation instruction"]),
    )
    assert invalid.status_code == 409
    assert "current governed playbook" in invalid.json()["detail"].lower()
    assert _authority_counts() == before


def test_exact_adoption_replay_is_idempotent() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    classified = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert classified.status_code == 201
    preview = _live_preview(claim_id)
    payload = _adoption_payload(preview)

    first = client.post(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan", json=payload)
    assert first.status_code == 201, first.text
    replay_payload = {**payload, "note": "Handler repeats the exact same governed source and selected playbook items with another note."}
    second = client.post(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan", json=replay_payload)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["plan_hash"] == first.json()["plan_hash"]

    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClaimInvestigationPlan)) == 1


def test_reclassification_marks_prior_plan_stale_and_new_explicit_adoption_creates_v2() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    first_classification = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert first_classification.status_code == 201
    first_preview = _live_preview(claim_id)
    first_plan_response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan",
        json=_adoption_payload(first_preview),
    )
    assert first_plan_response.status_code == 201
    first_plan = first_plan_response.json()

    second_classification = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(
            incident_code="collision",
            component_code=None,
            failure_mode=None,
            note="Handler reclassifies the casualty as collision after reviewing later casualty evidence.",
        ),
    )
    assert second_classification.status_code == 201

    current_before_adoption = client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan")
    assert current_before_adoption.status_code == 200
    assert current_before_adoption.json()["id"] == first_plan["id"]
    assert current_before_adoption.json()["source_current"] is False

    second_preview = _live_preview(claim_id)
    before = _authority_counts()
    second_plan_response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan",
        json=_adoption_payload(second_preview, review_topics=[second_preview["playbook"]["review_topics"][0]]),
    )
    assert second_plan_response.status_code == 201, second_plan_response.text
    second_plan = second_plan_response.json()
    assert second_plan["plan_number"] == 2
    assert second_plan["source_current"] is True
    assert second_plan["supersedes_plan_id"] == first_plan["id"]
    assert second_plan["previous_plan_hash"] == first_plan["plan_hash"]
    assert second_plan["incident_code"] == "collision"
    assert _authority_counts() == before

    history = client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plans")
    assert history.status_code == 200
    rows = history.json()
    assert [row["plan_number"] for row in rows] == [2, 1]
    assert rows[0]["source_current"] is True
    assert rows[1]["source_current"] is False


def test_investigation_plan_is_tenant_scoped() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    classified = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert classified.status_code == 201
    preview = _live_preview(claim_id)
    adopted = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan",
        json=_adoption_payload(preview),
    )
    assert adopted.status_code == 201

    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan").status_code == 404
    assert client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plans").status_code == 404
