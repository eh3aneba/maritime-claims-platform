from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.claim_intelligence.models import (
    ClaimIntelligenceItem,
    ClaimIntelligenceItemDecision,
    ClaimIntelligenceSnapshot,
)
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.tasks.models import ClaimTask, TaskSource, TaskStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _set_status(claim_id: str, status: ClaimStatus) -> None:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        claim.status = status
        db.commit()


def _add_fact(claim_id: str, field_path: str, value) -> None:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        db.add(ClaimFact(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            field_path=field_path,
            value=value,
            source_extraction_id=uuid4(),
            source_document_id=uuid4(),
            source_segment_id=None,
            approved_by_id=None,
            version=1,
        ))
        db.commit()


def _build(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/intelligence/build")
    assert response.status_code == 201, response.text
    return response.json()


def test_builds_source_linked_non_authoritative_machinery_intelligence() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.running_hours_since_overhaul", 14800)
    _add_fact(claim_id, "maintenance.recommended_overhaul_interval", 12000)

    snapshot = _build(claim_id)

    assert snapshot["snapshot_version"] == 1
    assert snapshot["engine_version"] == "12A.1"
    assert len(snapshot["source_state_hash"]) == 64
    assert len(snapshot["snapshot_hash"]) == 64
    summary = snapshot["summary"]
    assert summary["source_linked"] is True
    assert summary["non_authoritative"] is True
    assert summary["human_review_required"] is True
    assert summary["external_provider_scope_expanded"] is False
    assert summary["authoritative_claim_facts_updated"] is False
    assert summary["coverage_decision_made"] is False
    assert summary["causation_decision_made"] is False
    assert summary["liability_decision_made"] is False
    assert summary["reserve_or_settlement_decision_made"] is False
    categories = {item["category"] for item in snapshot["items"]}
    assert {"incident_summary", "machinery_context", "missing_evidence", "hypothesis", "next_action"}.issubset(categories)
    overdue = next(item for item in snapshot["items"] if item["category"] == "hypothesis" and "overdue" in item["title"].lower())
    assert "hypothesis" in overdue["title"].lower()
    assert overdue["source_refs"]
    assert any(ref["kind"] == "rule" and ref["id"] == "TECH-001" for ref in overdue["source_refs"])
    assert all(item["source_refs"] for item in snapshot["items"])


def test_rebuild_is_content_addressed_and_new_source_state_creates_next_version() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)

    first = _build(claim_id)
    second = _build(claim_id)
    assert second["id"] == first["id"]
    assert second["snapshot_version"] == 1
    assert second["snapshot_hash"] == first["snapshot_hash"]

    _set_status(claim_id, ClaimStatus.TECHNICAL_REVIEW)
    third = _build(claim_id)
    assert third["id"] != first["id"]
    assert third["snapshot_version"] == 2
    assert third["source_state_hash"] != first["source_state_hash"]

    with TestingSessionLocal() as db:
        rows = list(db.scalars(select(ClaimIntelligenceSnapshot).where(
            ClaimIntelligenceSnapshot.claim_id == UUID(claim_id)
        ).order_by(ClaimIntelligenceSnapshot.snapshot_version.asc())))
        assert [row.snapshot_version for row in rows] == [1, 2]
        assert rows[0].snapshot_hash == first["snapshot_hash"]


def test_human_decisions_are_append_only_and_task_conversion_never_mutates_snapshot() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    snapshot = _build(claim_id)
    candidate = next(item for item in snapshot["items"] if item["category"] == "next_action" and item["suggested_action"])
    original_item_hash = candidate["item_hash"]
    original_snapshot_hash = snapshot["snapshot_hash"]

    accepted = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/items/{candidate['id']}/decision",
        json={
            "action": "accept",
            "note": "Reviewed against the cited requirement and source lineage.",
            "convert_to_task": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    first_decision = accepted.json()
    assert first_decision["decision_number"] == 1
    assert first_decision["converted_task_id"] is not None
    assert len(first_decision["decision_hash"]) == 64

    edited = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/items/{candidate['id']}/decision",
        json={
            "action": "edit",
            "note": "Narrowed the wording after human review.",
            "edited_title": "Human-edited evidence follow-up",
            "edited_suggested_action": "Request the outstanding evidence through the controlled correspondence workflow.",
            "convert_to_task": False,
        },
    )
    assert edited.status_code == 200, edited.text
    second_decision = edited.json()
    assert second_decision["decision_number"] == 2
    assert second_decision["previous_decision_hash"] == first_decision["decision_hash"]

    dashboard = client.get(f"/api/v1/claims/{claim_id}/intelligence")
    assert dashboard.status_code == 200
    current = dashboard.json()["snapshot"]
    current_item = next(item for item in current["items"] if item["id"] == candidate["id"])
    assert current["snapshot_hash"] == original_snapshot_hash
    assert current_item["item_hash"] == original_item_hash
    assert current_item["title"] == candidate["title"]
    assert current_item["latest_decision"]["action"] == "edit"
    assert current_item["latest_decision"]["edited_title"] == "Human-edited evidence follow-up"

    with TestingSessionLocal() as db:
        decisions = list(db.scalars(select(ClaimIntelligenceItemDecision).where(
            ClaimIntelligenceItemDecision.item_id == UUID(candidate["id"])
        ).order_by(ClaimIntelligenceItemDecision.decision_number.asc())))
        task = db.get(ClaimTask, UUID(first_decision["converted_task_id"]))
        item = db.get(ClaimIntelligenceItem, UUID(candidate["id"]))
        assert len(decisions) == 2
        assert task is not None and task.status == TaskStatus.OPEN and task.source == TaskSource.AI_SUGGESTION
        assert item is not None and item.item_hash == original_item_hash


def test_rejects_decision_on_superseded_snapshot_item() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    first = _build(claim_id)
    candidate = next(item for item in first["items"] if item["category"] == "next_action" and item["suggested_action"])

    _set_status(claim_id, ClaimStatus.TECHNICAL_REVIEW)
    second = _build(claim_id)
    assert second["snapshot_version"] == 2

    response = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/items/{candidate['id']}/decision",
        json={"action": "accept", "note": "Reviewed old item after refresh.", "convert_to_task": False},
    )
    assert response.status_code == 409
    assert "superseded snapshot" in response.json()["detail"]


def test_prevents_duplicate_task_conversion_for_same_intelligence_item() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    snapshot = _build(claim_id)
    candidate = next(item for item in snapshot["items"] if item["category"] == "next_action" and item["suggested_action"])

    first = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/items/{candidate['id']}/decision",
        json={"action": "accept", "note": "Create the controlled follow-up task.", "convert_to_task": True},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/items/{candidate['id']}/decision",
        json={"action": "accept", "note": "Attempt to create the same task again.", "convert_to_task": True},
    )
    assert second.status_code == 409
    assert "already been created" in second.json()["detail"]

    with TestingSessionLocal() as db:
        tasks = list(db.scalars(select(ClaimTask).where(
            ClaimTask.claim_id == UUID(claim_id),
            ClaimTask.source == TaskSource.AI_SUGGESTION,
        )))
        assert len(tasks) == 1


def test_claim_intelligence_is_tenant_scoped() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _build(claim_id)

    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/intelligence").status_code == 404
    assert client.post(f"/api/v1/claims/{claim_id}/intelligence/build").status_code == 404
