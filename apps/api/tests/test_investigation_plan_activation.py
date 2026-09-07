from sqlalchemy import func, select

from app.modules.claim_intelligence.models import (
    ClaimIntelligenceSnapshot,
    ClaimInvestigationPlanActivation,
)
from app.modules.claims.facts import ClaimFact
from app.modules.correspondence.models import ClaimCorrespondence
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RuleEvaluationRun
from app.modules.tasks.models import ClaimTask, DocumentRequestBatch, TaskSource, TaskStatus, TaskType
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


def _preview(claim_id: str) -> dict:
    response = client.get(f"/api/v1/claims/{claim_id}/intelligence/domain-playbook-preview")
    assert response.status_code == 200, response.text
    return response.json()


def _adopt_plan(claim_id: str) -> dict:
    preview = _preview(claim_id)
    payload = {
        "registry_version": preview["registry_version"],
        "registry_hash": preview["registry_hash"],
        "classification_id": preview["source_ref"]["id"],
        "classification_hash": preview["source_ref"]["classification_hash"],
        "investigation_tracks": [preview["playbook"]["investigation_tracks"][0]],
        "evidence_prompts": [preview["playbook"]["evidence_prompts"][0]],
        "review_topics": [preview["playbook"]["review_topics"][0]],
        "note": "Handler adopts a bounded investigation plan before any work-item activation is considered.",
        "confirm_adoption": True,
    }
    response = client.post(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _activation_payload(plan: dict, **overrides) -> dict:
    payload = {
        "plan_id": plan["id"],
        "plan_hash": plan["plan_hash"],
        "item_keys": ["track:0", "review:0"],
        "note": "Handler explicitly activates these current plan items as human-owned investigation work only.",
        "confirm_activation": True,
    }
    payload.update(overrides)
    return payload


def _non_task_authority_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            "rule_runs": db.scalar(select(func.count()).select_from(RuleEvaluationRun)) or 0,
            "requirements": db.scalar(select(func.count()).select_from(ClaimDocumentRequirement)) or 0,
            "issues": db.scalar(select(func.count()).select_from(ClaimIssue)) or 0,
            "facts": db.scalar(select(func.count()).select_from(ClaimFact)) or 0,
            "request_batches": db.scalar(select(func.count()).select_from(DocumentRequestBatch)) or 0,
            "correspondence": db.scalar(select(func.count()).select_from(ClaimCorrespondence)) or 0,
            "snapshots": db.scalar(select(func.count()).select_from(ClaimIntelligenceSnapshot)) or 0,
        }


def test_activation_requires_current_investigation_plan() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    before = _non_task_authority_counts()
    response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json={
            "plan_id": "00000000-0000-0000-0000-000000000001",
            "plan_hash": "a" * 64,
            "item_keys": ["track:0"],
            "note": "Handler cannot activate investigation work without an adopted current Investigation Plan.",
            "confirm_activation": True,
        },
    )
    assert response.status_code == 409
    assert "plan" in response.json()["detail"].lower()
    assert _non_task_authority_counts() == before
    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClaimTask)) == 0


def test_valid_activation_creates_only_human_tasks_with_exact_plan_provenance() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    classified = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    )
    assert classified.status_code == 201
    plan = _adopt_plan(claim_id)
    before = _non_task_authority_counts()

    response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json=_activation_payload(plan),
    )
    assert response.status_code == 201, response.text
    activation = response.json()
    assert activation["activation_number"] == 1
    assert activation["plan_id"] == plan["id"]
    assert activation["plan_hash"] == plan["plan_hash"]
    assert activation["plan_current"] is True
    assert [item["key"] for item in activation["selected_items"]] == ["track:0", "review:0"]
    assert len(activation["work_items"]) == 2
    assert activation["automatic_rule_execution"] is False
    assert activation["automatic_requirement_activation"] is False
    assert activation["automatic_document_request"] is False
    assert activation["automatic_intelligence_build"] is False
    assert activation["automatic_claim_decision"] is False
    assert _non_task_authority_counts() == before

    with TestingSessionLocal() as db:
        tasks = list(db.scalars(select(ClaimTask).order_by(ClaimTask.created_at.asc())))
        assert len(tasks) == 2
        assert {task.investigation_item_key for task in tasks} == {"track:0", "review:0"}
        assert all(str(task.investigation_plan_id) == plan["id"] for task in tasks)
        assert all(str(task.investigation_activation_id) == activation["id"] for task in tasks)
        assert all(task.source == TaskSource.HUMAN for task in tasks)
        assert all(task.status == TaskStatus.OPEN for task in tasks)
        by_key = {task.investigation_item_key: task for task in tasks}
        assert by_key["track:0"].task_type == TaskType.FOLLOW_UP
        assert by_key["review:0"].task_type == TaskType.REVIEW
        assert all(task.requirement_id is None for task in tasks)
        assert all(task.request_batch_id is None for task in tasks)


def test_activation_replay_is_idempotent_and_overlapping_new_activation_fails_closed() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    assert client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    ).status_code == 201
    plan = _adopt_plan(claim_id)
    payload = _activation_payload(plan)

    first = client.post(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation", json=payload)
    assert first.status_code == 201, first.text
    replay = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json={**payload, "note": "Handler repeats the exact same plan-item activation with a different explanatory note."},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]

    overlap = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json=_activation_payload(plan, item_keys=["track:0", "evidence:0"]),
    )
    assert overlap.status_code == 409
    assert "already been activated" in overlap.json()["detail"].lower()

    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClaimInvestigationPlanActivation)) == 1
        assert db.scalar(select(func.count()).select_from(ClaimTask)) == 2


def test_reclassification_preserves_old_activation_and_requires_new_current_plan_activation() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    assert client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    ).status_code == 201
    plan_v1 = _adopt_plan(claim_id)
    activated_v1 = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json=_activation_payload(plan_v1, item_keys=["track:0"]),
    )
    assert activated_v1.status_code == 201
    first_activation = activated_v1.json()

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

    current_activation = client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation")
    assert current_activation.status_code == 200
    assert current_activation.json()["id"] == first_activation["id"]
    assert current_activation.json()["plan_current"] is False

    stale_attempt = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json=_activation_payload(plan_v1, item_keys=["evidence:0"]),
    )
    assert stale_attempt.status_code == 409

    plan_v2 = _adopt_plan(claim_id)
    second = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json=_activation_payload(plan_v2, item_keys=["track:0"]),
    )
    assert second.status_code == 201, second.text
    activation_v2 = second.json()
    assert activation_v2["activation_number"] == 2
    assert activation_v2["plan_id"] == plan_v2["id"]
    assert activation_v2["previous_activation_hash"] == first_activation["activation_hash"]
    assert activation_v2["plan_current"] is True

    history = client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activations")
    assert history.status_code == 200
    rows = history.json()
    assert [row["activation_number"] for row in rows] == [2, 1]
    assert rows[0]["plan_current"] is True
    assert rows[1]["plan_current"] is False

    with TestingSessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClaimTask)) == 2


def test_activation_is_tenant_scoped() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    assert client.post(
        f"/api/v1/claims/{claim_id}/intelligence/domain-classification",
        json=_classification_payload(),
    ).status_code == 201
    plan = _adopt_plan(claim_id)
    assert client.post(
        f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation",
        json=_activation_payload(plan, item_keys=["track:0"]),
    ).status_code == 201

    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activation").status_code == 404
    assert client.get(f"/api/v1/claims/{claim_id}/intelligence/investigation-plan-activations").status_code == 404
