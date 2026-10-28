"""R5: deleting a current approved source immediately retires dependent live chronology.

Only synthetic CE and engine-log evidence; historical review dispositions must
remain auditable. No actual insurer documents or automatic adjudication.
"""
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.chronology.models import ChronologyEvent, EvidenceConflict, EvidenceConflictDecision
from app.modules.documents.models import Document
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_chronology_engine import login
from tests.test_chronology_immediate_replacement_invalidation import _get_timeline, _initial_state


def setup_function() -> None:
    reset_database()


def test_soft_delete_retires_active_chronology_without_rebuild_or_rewriting_decisions() -> None:
    ids, claim_id, source_id, prior_conflict, decision_hash = _initial_state()

    deleted = client.delete(f"/api/v1/claims/{claim_id}/documents/{source_id}")
    assert deleted.status_code == 204, deleted.text

    # Crucial: observe the GET immediately, with NO manual rebuild.
    current = _get_timeline(claim_id)
    assert current["event_count"] == 1
    assert current["open_conflict_count"] == 0
    assert not current["conflicts"]
    assert current["events"][0]["occurred_time"][:5] == "10:52"
    assert all(
        link["document_id"] != source_id
        for event in current["events"] for link in event["evidence"]
    )

    stale_action = client.post(
        f"/api/v1/claims/{claim_id}/chronology/conflicts/{prior_conflict['id']}/resolve",
        json={
            "status": "accepted_difference",
            "note": "This source is no longer current; no stale decision replay.",
            "expected_state_fingerprint": prior_conflict["state_fingerprint"],
            "expected_state_version": prior_conflict["state_version"],
        },
    )
    assert stale_action.status_code == 404, stale_action.text

    with TestingSessionLocal() as db:
        source = db.get(Document, UUID(source_id))
        assert source is not None and source.deleted_at is not None
        old_extraction = db.get(DocumentExtraction, UUID(ids["ce_time_id"]))
        assert old_extraction is not None
        assert old_extraction.approved_value == "10:30"
        assert old_extraction.human_status == AIReviewStatus.APPROVED
        historic = db.get(EvidenceConflict, UUID(prior_conflict["id"]))
        assert historic is not None and historic.is_active is False
        assert historic.status.value == "accepted_difference"
        decisions = list(db.scalars(
            select(EvidenceConflictDecision).where(
                EvidenceConflictDecision.conflict_id == historic.id
            )
        ))
        assert len(decisions) == 1
        assert decisions[0].decision_hash == decision_hash
        assert db.scalar(select(ChronologyEvent).where(
            ChronologyEvent.claim_id == UUID(claim_id),
            ChronologyEvent.is_active.is_(False),
        )) is not None
        audit = list(db.scalars(select(AuditLog).where(
            AuditLog.organization_id == UUID(ids["alpha_org_id"]),
            AuditLog.action == "DELETE_DOCUMENT",
            AuditLog.entity_id == source.id,
        )))
        assert len(audit) == 1
        assert audit[0].new_values["chronology_events_invalidated"] >= 1
        assert audit[0].new_values["chronology_conflicts_invalidated"] == 1

    repeated = client.delete(f"/api/v1/claims/{claim_id}/documents/{source_id}")
    assert repeated.status_code == 404, repeated.text
    rebuild = client.post(f"/api/v1/claims/{claim_id}/chronology/rebuild")
    assert rebuild.status_code == 200, rebuild.text
    assert _get_timeline(claim_id)["event_count"] == 1


def test_cross_tenant_soft_delete_cannot_retire_someone_elses_timeline() -> None:
    _, claim_id, source_id, prior_conflict, _ = _initial_state()
    login("beta", "beta@example.com")
    rejected = client.delete(f"/api/v1/claims/{claim_id}/documents/{source_id}")
    assert rejected.status_code == 404, rejected.text

    login("alpha", "alpha@example.com")
    current = _get_timeline(claim_id)
    assert current["event_count"] == 2
    assert len(current["conflicts"]) == 1
    assert current["conflicts"][0]["id"] == prior_conflict["id"]
    with TestingSessionLocal() as db:
        source = db.get(Document, UUID(source_id))
        assert source is not None and source.deleted_at is None
