from uuid import UUID

from sqlalchemy import select

from app.modules.chronology.models import ChronologyEvent, EventEvidence
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_chronology_engine import login, seed_timeline


def setup_function() -> None:
    reset_database()


def _engine_event_id(*, claim_id: str, extraction_id: str) -> UUID:
    with TestingSessionLocal() as db:
        event_id = db.scalar(
            select(ChronologyEvent.id)
            .join(EventEvidence, EventEvidence.event_id == ChronologyEvent.id)
            .where(
                ChronologyEvent.claim_id == UUID(claim_id),
                ChronologyEvent.is_active.is_(True),
                EventEvidence.extraction_id == UUID(extraction_id),
            )
        )
        assert event_id is not None
        return event_id


def _decision_payload(conflict: dict, *, status: str, note: str) -> dict:
    return {
        "status": status,
        "note": note,
        "expected_state_fingerprint": conflict["state_fingerprint"],
        "expected_state_version": conflict["state_version"],
        "confirm_re_review": False,
    }


def test_reviewed_timestamp_correction_preserves_event_and_conflict_lineage() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")

    built = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert built.status_code == 200, built.text
    summary = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology")
    assert summary.status_code == 200, summary.text
    original_conflict = summary.json()["conflicts"][0]
    original_event_id = _engine_event_id(
        claim_id=ids["claim_id"],
        extraction_id=ids["eng_time_id"],
    )

    endpoint = (
        f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/"
        f"{original_conflict['id']}/resolve"
    )
    first = client.post(
        endpoint,
        json=_decision_payload(
            original_conflict,
            status="explained",
            note="The original difference was reviewed against the then-current timestamps.",
        ),
    )
    assert first.status_code == 200, first.text
    first_decision_hash = first.json()["decision_hash"]

    # A human edit keeps the same DocumentExtraction identity while correcting
    # its approved value. Chronology should treat that as mutable event state,
    # not as a brand-new source-linked event identity.
    with TestingSessionLocal() as db:
        engine_time = db.get(DocumentExtraction, UUID(ids["eng_time_id"]))
        assert engine_time is not None
        engine_time.human_status = AIReviewStatus.EDITED
        engine_time.approved_value = "10:58"
        db.commit()

    rebuilt = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["open_conflict_count"] == 1

    after = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology")
    assert after.status_code == 200, after.text
    conflicts = after.json()["conflicts"]
    assert len(conflicts) == 1
    evolved = conflicts[0]

    assert evolved["id"] == original_conflict["id"]
    assert _engine_event_id(
        claim_id=ids["claim_id"],
        extraction_id=ids["eng_time_id"],
    ) == original_event_id
    assert evolved["state_fingerprint"] != original_conflict["state_fingerprint"]
    assert evolved["state_version"] == original_conflict["state_version"] + 1
    assert evolved["status"] == "open"
    assert evolved["decision_state"] == "stale"
    assert len(evolved["decision_history"]) == 1
    assert evolved["decision_history"][0]["decision_hash"] == first_decision_hash

    stale = client.post(
        endpoint,
        json=_decision_payload(
            original_conflict,
            status="resolved",
            note="This disposition was prepared against the pre-correction evidence state.",
        ),
    )
    assert stale.status_code == 409, stale.text
    assert "state changed" in stale.json()["detail"].lower()

    current = client.post(
        endpoint,
        json=_decision_payload(
            evolved,
            status="resolved",
            note="Re-reviewed after the human timestamp correction and chronology rebuild.",
        ),
    )
    assert current.status_code == 200, current.text
    assert current.json()["decision_number"] == 2

    final = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology").json()
    decided = final["conflicts"][0]
    assert decided["id"] == original_conflict["id"]
    assert decided["decision_state"] == "current"
    assert [row["decision_number"] for row in decided["decision_history"]] == [1, 2]
    assert decided["decision_history"][1]["previous_decision_hash"] == first_decision_hash
