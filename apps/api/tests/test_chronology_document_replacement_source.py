"""R5 H&M: superseded approved source evidence is historical, never current truth.

All records are synthetic. Approval in the fixture is simulated only; this
does not substitute for an actual adjuster or validate an OCR transcript.
"""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.modules.chronology.models import ChronologyEvent, EvidenceConflict, EvidenceConflictDecision
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.intelligence.models import DocumentExtraction
from app.modules.organizations.models import Organization
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_chronology_engine import _document, _extraction, login, seed_timeline


def setup_function() -> None:
    reset_database()


def _rebuild(claim_id: str) -> dict:
    result = client.post(f"/api/v1/claims/{claim_id}/chronology/rebuild")
    assert result.status_code == 200, result.text
    view = client.get(f"/api/v1/claims/{claim_id}/chronology")
    assert view.status_code == 200, view.text
    return view.json()


def test_replaced_ce_source_drops_from_active_chronology_without_revoking_old_decision() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    claim_id = ids["claim_id"]

    initial = _rebuild(claim_id)
    assert initial["event_count"] == 2
    assert initial["open_conflict_count"] == 1
    old_conflict = initial["conflicts"][0]
    old_event_ids = {event["id"] for event in initial["events"]}
    resolution = client.post(
        f"/api/v1/claims/{claim_id}/chronology/conflicts/{old_conflict['id']}/resolve",
        json={
            "status": "accepted_difference",
            "note": "Synthetic human review: historical source timestamps remain different.",
            "expected_state_fingerprint": old_conflict["state_fingerprint"],
            "expected_state_version": old_conflict["state_version"],
        },
    )
    assert resolution.status_code == 200, resolution.text
    old_decision_hash = resolution.json()["decision_hash"]

    with TestingSessionLocal() as db:
        old_ce_time = db.get(DocumentExtraction, UUID(ids["ce_time_id"]))
        assert old_ce_time is not None
        old_document = db.get(Document, old_ce_time.document_id)
        claim = db.get(Claim, UUID(claim_id))
        user = db.get(User, UUID(ids["alpha_user_id"]))
        org = db.get(Organization, UUID(ids["alpha_org_id"]))
        assert old_document is not None and claim and user and org
        assert old_document.is_current is True
        old_document.is_current = False
        old_document.superseded_at = datetime.now(UTC)
        old_document.superseded_by_id = user.id
        db.flush()
        replacement, segment, run = _document(
            db,
            org=org,
            claim=claim,
            user=user,
            name="CE_Report_v2.pdf",
            doc_type="chief_engineer_report",
            hash_char="b",
        )
        replacement.document_family_id = old_document.document_family_id
        replacement.version_number = 2
        replacement.supersedes_document_id = old_document.id
        db.commit()
        old_document_id = str(old_document.id)
        replacement_id = str(replacement.id)

    # Replacement v2 has no human-reviewed extraction yet. Historical v1
    # approval and decision remain auditable but cannot populate live chronology.
    after_replacement = _rebuild(claim_id)
    assert after_replacement["event_count"] == 1
    assert after_replacement["open_conflict_count"] == 0
    assert len(after_replacement["events"]) == 1
    assert all(
        evidence["document_id"] != old_document_id
        for event in after_replacement["events"]
        for evidence in event["evidence"]
    )

    with TestingSessionLocal() as db:
        old_event_rows = list(db.scalars(
            select(ChronologyEvent).where(
                ChronologyEvent.id.in_([UUID(x) for x in old_event_ids])
            )
        ))
        assert any(not event.is_active for event in old_event_rows)
        historical = db.get(EvidenceConflict, UUID(old_conflict["id"]))
        assert historical is not None and historical.is_active is False
        assert historical.status.value == "accepted_difference"
        decisions = list(db.scalars(
            select(EvidenceConflictDecision).where(
                EvidenceConflictDecision.conflict_id == historical.id
            )
        ))
        assert len(decisions) == 1
        assert decisions[0].decision_hash == old_decision_hash
        # The original approved extraction still exists; no auto-revocation.
        old_ce_time = db.get(DocumentExtraction, UUID(ids["ce_time_id"]))
        assert old_ce_time is not None and old_ce_time.approved_value == "10:30"

        replacement = db.get(Document, UUID(replacement_id))
        assert replacement is not None and replacement.is_current
        claim = db.get(Claim, UUID(claim_id))
        org = db.get(Organization, UUID(ids["alpha_org_id"]))
        user = db.get(User, UUID(ids["alpha_user_id"]))
        assert claim and org and user
        # Test fixture simulates separately approved v2; production never
        # automatically approves newly uploaded replacement evidence.
        from app.modules.processing.models import DocumentTextSegment
        from app.modules.intelligence.models import AIRun
        segment = db.scalar(select(DocumentTextSegment).where(
            DocumentTextSegment.document_id == replacement.id
        ))
        run = db.scalar(select(AIRun).where(AIRun.document_id == replacement.id))
        assert segment is not None and run is not None
        for path, value in (
            ("reported_events[0].date", "2026-07-10"),
            ("reported_events[0].time", "11:20"),
            ("reported_events[0].timezone", "UTC"),
            ("reported_events[0].description", "Main engine stopped at 11:20 for review."),
        ):
            _extraction(
                db, org=org, claim=claim, document=replacement,
                segment=segment, run=run, path=path, value=value,
            )
        db.commit()

    current = _rebuild(claim_id)
    assert current["event_count"] == 2
    assert current["open_conflict_count"] == 1
    assert current["conflicts"][0]["id"] != old_conflict["id"]
    assert current["conflicts"][0]["status"] == "open"
    assert {event["occurred_time"][:5] for event in current["events"]} == {"10:52", "11:20"}
    source_ids = {
        evidence["document_id"]
        for event in current["events"]
        for evidence in event["evidence"]
    }
    assert replacement_id in source_ids
    assert old_document_id not in source_ids

    repeated = _rebuild(claim_id)
    assert {event["id"] for event in repeated["events"]} == {
        event["id"] for event in current["events"]
    }
    assert repeated["conflicts"][0]["id"] == current["conflicts"][0]["id"]
    with TestingSessionLocal() as db:
        historical = db.get(EvidenceConflict, UUID(old_conflict["id"]))
        assert historical is not None and historical.is_active is False
        assert db.scalar(select(EvidenceConflictDecision).where(
            EvidenceConflictDecision.decision_hash == old_decision_hash
        )) is not None
