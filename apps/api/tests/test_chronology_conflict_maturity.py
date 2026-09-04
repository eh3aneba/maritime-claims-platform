from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.chronology.models import ConflictStatus, EvidenceConflict, EvidenceConflictDecision
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_chronology_engine import login, seed_timeline


def setup_function() -> None:
    reset_database()


def _build_and_get_conflict(ids: dict[str, str]) -> dict:
    built = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert built.status_code == 200, built.text
    summary = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology")
    assert summary.status_code == 200, summary.text
    conflicts = summary.json()["conflicts"]
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["state_fingerprint"]
    assert len(conflict["state_fingerprint"]) == 64
    assert conflict["state_version"] >= 1
    return conflict


def _decision_payload(conflict: dict, *, status: str, note: str, confirm_re_review: bool = False) -> dict:
    return {
        "status": status,
        "note": note,
        "expected_state_fingerprint": conflict["state_fingerprint"],
        "expected_state_version": conflict["state_version"],
        "confirm_re_review": confirm_re_review,
    }


def test_conflict_decision_history_is_append_only_and_exact_replay_is_idempotent() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    conflict = _build_and_get_conflict(ids)
    endpoint = f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/{conflict['id']}/resolve"
    payload = _decision_payload(
        conflict,
        status="explained",
        note="CE report records the operational response while the Engine Log records formal shutdown.",
    )

    first = client.post(endpoint, json=payload)
    replay = client.post(endpoint, json=payload)
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["decision_hash"] == replay.json()["decision_hash"]

    summary = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology").json()
    current = next(row for row in summary["conflicts"] if row["id"] == conflict["id"])
    assert current["decision_state"] == "current"
    assert current["status"] == "explained"
    assert len(current["decision_history"]) == 1
    assert current["decision_history"][0]["decision_number"] == 1

    with TestingSessionLocal() as db:
        decisions = list(
            db.scalars(
                select(EvidenceConflictDecision).where(
                    EvidenceConflictDecision.conflict_id == UUID(conflict["id"])
                )
            )
        )
        assert len(decisions) == 1
        audits = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == UUID(conflict["id"]),
                    AuditLog.action == "RESOLVE_EVIDENCE_CONFLICT",
                )
            )
        )
        assert len(audits) == 1


def test_disappearing_and_reappearing_conflict_reopens_and_preserves_stale_history() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    conflict = _build_and_get_conflict(ids)
    endpoint = f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/{conflict['id']}/resolve"
    first = client.post(
        endpoint,
        json=_decision_payload(
            conflict,
            status="accepted_difference",
            note="The two timestamps use different recording conventions.",
        ),
    )
    assert first.status_code == 200, first.text
    first_hash = first.json()["decision_hash"]

    with TestingSessionLocal() as db:
        engine_time = db.get(DocumentExtraction, UUID(ids["eng_time_id"]))
        assert engine_time is not None
        engine_time.human_status = AIReviewStatus.PENDING
        db.commit()
    absent = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert absent.status_code == 200, absent.text
    assert absent.json()["open_conflict_count"] == 0

    with TestingSessionLocal() as db:
        engine_time = db.get(DocumentExtraction, UUID(ids["eng_time_id"]))
        assert engine_time is not None
        engine_time.human_status = AIReviewStatus.APPROVED
        db.commit()
    restored = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert restored.status_code == 200, restored.text

    summary = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology").json()
    reopened = next(row for row in summary["conflicts"] if row["id"] == conflict["id"])
    assert reopened["status"] == "open"
    assert reopened["resolution_note"] is None
    assert reopened["state_version"] == conflict["state_version"] + 1
    assert reopened["decision_state"] == "stale"
    assert len(reopened["decision_history"]) == 1
    assert reopened["decision_history"][0]["decision_hash"] == first_hash

    stale = client.post(
        endpoint,
        json=_decision_payload(
            conflict,
            status="resolved",
            note="This request was prepared against the earlier conflict state.",
        ),
    )
    assert stale.status_code == 409, stale.text
    assert "state changed" in stale.json()["detail"].lower()

    current = client.post(
        endpoint,
        json=_decision_payload(
            reopened,
            status="resolved",
            note="Re-reviewed after the conflict reappeared in the current evidence set.",
        ),
    )
    assert current.status_code == 200, current.text
    assert current.json()["decision_number"] == 2

    after = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology").json()
    decided = next(row for row in after["conflicts"] if row["id"] == conflict["id"])
    assert decided["decision_state"] == "current"
    assert [row["decision_number"] for row in decided["decision_history"]] == [1, 2]
    assert decided["decision_history"][1]["previous_decision_hash"] == first_hash


def test_meaningful_second_disposition_requires_deliberate_re_review() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    conflict = _build_and_get_conflict(ids)
    endpoint = f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/{conflict['id']}/resolve"
    first = client.post(
        endpoint,
        json=_decision_payload(
            conflict,
            status="explained",
            note="First reviewer explained the recording convention difference.",
        ),
    )
    assert first.status_code == 200, first.text

    second_payload = _decision_payload(
        conflict,
        status="resolved",
        note="Second review concludes the conflict is resolved for chronology workflow purposes.",
    )
    denied = client.post(endpoint, json=second_payload)
    assert denied.status_code == 409, denied.text
    assert "confirm deliberate re-review" in denied.json()["detail"].lower()

    second_payload["confirm_re_review"] = True
    confirmed = client.post(endpoint, json=second_payload)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["decision_number"] == 2

    summary = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology").json()
    current = next(row for row in summary["conflicts"] if row["id"] == conflict["id"])
    assert current["status"] == "resolved"
    assert current["decision_state"] == "current"
    assert len(current["decision_history"]) == 2


def test_expected_conflict_state_must_be_supplied_as_a_complete_pair() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    conflict = _build_and_get_conflict(ids)
    endpoint = f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/{conflict['id']}/resolve"
    response = client.post(
        endpoint,
        json={
            "status": "explained",
            "note": "Incomplete optimistic-concurrency token must be rejected.",
            "expected_state_version": conflict["state_version"],
        },
    )
    assert response.status_code == 422, response.text


def test_conflict_decision_history_remains_tenant_scoped() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    conflict = _build_and_get_conflict(ids)
    endpoint = f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/{conflict['id']}/resolve"
    resolved = client.post(
        endpoint,
        json=_decision_payload(
            conflict,
            status="explained",
            note="Alpha tenant reviewed its own chronology conflict.",
        ),
    )
    assert resolved.status_code == 200, resolved.text

    client.cookies.clear()
    login("beta", "beta@example.com")
    hidden = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology")
    hidden_write = client.post(
        endpoint,
        json={"status": "resolved", "note": "Cross-tenant write must remain hidden."},
    )
    assert hidden.status_code == 404
    assert hidden_write.status_code == 404

    with TestingSessionLocal() as db:
        conflict_row = db.get(EvidenceConflict, UUID(conflict["id"]))
        assert conflict_row is not None
        assert conflict_row.status == ConflictStatus.EXPLAINED
