from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.intelligence.models import DocumentExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_review_fact_maturity import _add_intake_fact_and_ai_candidate
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


def test_review_detail_exposes_tenant_scoped_canonical_revision_history() -> None:
    ids = seed_review_candidates()
    candidate_id = _add_intake_fact_and_ai_candidate(ids)
    login("alpha", "alpha@example.com")

    before = client.get(f"/api/v1/ai-review/{candidate_id}")
    assert before.status_code == 200, before.text
    before_payload = before.json()
    assert before_payload["current_claim_fact"]["provenance_kind"] == "intake_review"
    assert before_payload["current_claim_fact"]["version"] == 1
    assert [row["version"] for row in before_payload["claim_fact_revisions"]] == [1]
    assert before_payload["claim_fact_revisions"][0]["provenance_kind"] == "intake_review"

    approved = client.post(f"/api/v1/ai-review/{candidate_id}", json={"action": "approve"})
    assert approved.status_code == 200, approved.text

    after_approve = client.get(f"/api/v1/ai-review/{candidate_id}")
    assert after_approve.status_code == 200, after_approve.text
    approve_payload = after_approve.json()
    assert approve_payload["item"]["human_status"] == "approved"
    assert approve_payload["current_claim_fact"]["provenance_kind"] == "ai_review"
    assert approve_payload["current_claim_fact"]["version"] == 2
    assert [row["version"] for row in approve_payload["claim_fact_revisions"]] == [2, 1]
    assert [row["provenance_kind"] for row in approve_payload["claim_fact_revisions"]] == ["ai_review", "intake_review"]

    approved_queue = client.get(
        f"/api/v1/ai-review?claim_id={ids['claim_id']}&review_status=approved&limit=1"
    )
    assert approved_queue.status_code == 200, approved_queue.text
    assert approved_queue.json()["items"][0]["extraction_id"] == candidate_id

    rejected = client.post(
        f"/api/v1/ai-review/{candidate_id}",
        json={
            "action": "reject",
            "reason": "Second review restores the intake-reviewed fact.",
            "confirm_re_review": True,
        },
    )
    assert rejected.status_code == 200, rejected.text

    after_reject = client.get(f"/api/v1/ai-review/{candidate_id}")
    assert after_reject.status_code == 200, after_reject.text
    reject_payload = after_reject.json()
    assert reject_payload["item"]["human_status"] == "rejected"
    assert reject_payload["current_claim_fact"]["provenance_kind"] == "intake_review"
    assert reject_payload["current_claim_fact"]["version"] == 3
    assert [row["version"] for row in reject_payload["claim_fact_revisions"]] == [3, 2, 1]
    assert [row["provenance_kind"] for row in reject_payload["claim_fact_revisions"]] == [
        "intake_review",
        "ai_review",
        "intake_review",
    ]

    login("beta", "beta@example.com")
    cross_tenant = client.get(f"/api/v1/ai-review/{candidate_id}")
    assert cross_tenant.status_code == 404


def test_reviewed_status_queue_shows_latest_human_decision_first() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")

    first = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    second = client.post(f"/api/v1/ai-review/{ids['time_id']}", json={"action": "approve"})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    # Make the review ordering deterministic independently of test execution speed.
    now = datetime.now(UTC)
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        incident_time = db.get(DocumentExtraction, UUID(ids["time_id"]))
        assert maker is not None and incident_time is not None
        maker.reviewed_at = now - timedelta(minutes=1)
        incident_time.reviewed_at = now
        db.commit()

    response = client.get(
        f"/api/v1/ai-review?claim_id={ids['claim_id']}&review_status=approved&limit=1"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["extraction_id"] == ids["time_id"]
