"""R5 synthetic H&M: actual replacement admission immediately retires stale chronology.

All dates, names, values, evidence, review decisions and upload bytes are
fictional. No local/external AI, customer documents or autonomous adjudication.
"""
from io import BytesIO
from uuid import UUID

from pypdf import PdfWriter
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.chronology.models import ChronologyEvent, EvidenceConflict, EvidenceConflictDecision
from app.modules.documents.models import Document
from app.modules.intelligence.models import DocumentExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_chronology_engine import login, seed_timeline


def setup_function() -> None:
    reset_database()


def _safe_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=360, height=360)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _get_timeline(claim_id: str) -> dict:
    result = client.get(f"/api/v1/claims/{claim_id}/chronology")
    assert result.status_code == 200, result.text
    return result.json()


def _initial_state() -> tuple[dict, str, str, dict, str]:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    claim_id = ids["claim_id"]
    build = client.post(f"/api/v1/claims/{claim_id}/chronology/rebuild")
    assert build.status_code == 200, build.text
    original = _get_timeline(claim_id)
    assert original["event_count"] == 2
    assert original["open_conflict_count"] == 1
    conflict = original["conflicts"][0]
    response = client.post(
        f"/api/v1/claims/{claim_id}/chronology/conflicts/{conflict['id']}/resolve",
        json={
            "status": "accepted_difference",
            "note": "Synthetic historical independent time-source review, not causal approval.",
            "expected_state_fingerprint": conflict["state_fingerprint"],
            "expected_state_version": conflict["state_version"],
        },
    )
    assert response.status_code == 200, response.text
    with TestingSessionLocal() as db:
        time_source = db.get(DocumentExtraction, UUID(ids["ce_time_id"]))
        assert time_source is not None
        old_source_id = str(time_source.document_id)
    return ids, claim_id, old_source_id, conflict, response.json()["decision_hash"]


def test_replacement_immediately_retires_old_timeline_without_manual_rebuild() -> None:
    ids, claim_id, source_id, old_conflict, decision_hash = _initial_state()
    replacement = client.post(
        f"/api/v1/claims/{claim_id}/documents/{source_id}/replacements",
        files={"file": ("synthetic_ce_v2.pdf", _safe_pdf(), "application/pdf")},
        data={"replacement_reason": "Synthetic revised Chief Engineer report supersedes the original."},
    )
    assert replacement.status_code == 201, replacement.text
    payload = replacement.json()
    assert payload["version_number"] == 2
    assert payload["supersedes_document_id"] == source_id
    assert payload["is_current"] is True
    assert payload["id"] != source_id

    # Critical property: NO call to /chronology/rebuild between replacement
    # and GET. The previously approved 10:30 clock is never shown as current.
    now = _get_timeline(claim_id)
    assert now["event_count"] == 1
    assert now["open_conflict_count"] == 0
    assert not now["conflicts"]
    assert all(event["occurred_time"][:5] == "10:52" for event in now["events"])
    assert all(
        link["document_id"] not in {source_id, payload["id"]}
        for event in now["events"] for link in event["evidence"]
    )

    # The historical decision stays immutable, but cannot be re-applied to
    # a no-longer-active contradiction.
    replay = client.post(
        f"/api/v1/claims/{claim_id}/chronology/conflicts/{old_conflict['id']}/resolve",
        json={
            "status": "accepted_difference",
            "note": "Synthetic historical independent time-source review, not causal approval.",
            "expected_state_fingerprint": old_conflict["state_fingerprint"],
            "expected_state_version": old_conflict["state_version"],
        },
    )
    assert replay.status_code == 404, replay.text
    with TestingSessionLocal() as db:
        old = db.get(Document, UUID(source_id))
        new = db.get(Document, UUID(payload["id"]))
        assert old is not None and old.is_current is False
        assert new is not None and new.is_current is True
        assert new.document_family_id == old.document_family_id
        assert not list(db.scalars(
            select(DocumentExtraction).where(DocumentExtraction.document_id == new.id)
        ))
        historic = db.get(EvidenceConflict, UUID(old_conflict["id"]))
        assert historic is not None and historic.is_active is False
        assert historic.status.value == "accepted_difference"
        assert db.scalar(select(EvidenceConflictDecision).where(
            EvidenceConflictDecision.conflict_id == historic.id,
            EvidenceConflictDecision.decision_hash == decision_hash,
        )) is not None
        assert db.scalar(select(ChronologyEvent).where(
            ChronologyEvent.claim_id == UUID(claim_id),
            ChronologyEvent.is_active.is_(False),
        )) is not None
        audit = list(db.scalars(
            select(AuditLog).where(
                AuditLog.organization_id == UUID(ids["alpha_org_id"]),
                AuditLog.action == "REPLACE_DOCUMENT",
                AuditLog.entity_id == new.id,
            )
        ))
        assert len(audit) == 1
        assert audit[0].new_values["chronology_events_invalidated"] >= 1
        assert audit[0].new_values["chronology_conflicts_invalidated"] == 1

    rebuilt = client.post(f"/api/v1/claims/{claim_id}/chronology/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert _get_timeline(claim_id)["event_count"] == 1


def test_rejected_replacement_never_invalidates_current_chronology() -> None:
    _, claim_id, source_id, old_conflict, decision_hash = _initial_state()
    attempted = client.post(
        f"/api/v1/claims/{claim_id}/documents/{source_id}/replacements",
        files={"file": ("bad_synthetic.pdf", b"not-a-pdf", "application/pdf")},
        data={"replacement_reason": "This invalid upload must not replace any valid source."},
    )
    assert attempted.status_code == 415, attempted.text
    current = _get_timeline(claim_id)
    assert current["event_count"] == 2
    assert current["conflicts"][0]["id"] == old_conflict["id"]
    assert current["conflicts"][0]["status"] == "accepted_difference"
    assert current["conflicts"][0]["decision_history"][0]["decision_hash"] == decision_hash
    with TestingSessionLocal() as db:
        source = db.get(Document, UUID(source_id))
        assert source is not None and source.is_current is True
