from sqlalchemy import select

from app.modules.correspondence.models import CorrespondenceReviewDecision
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _create(claim_id: str, subject: str = "MT ORION integrity review") -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/correspondence",
        json={
            "direction": "outbound",
            "kind": "status_update",
            "sensitivity": "standard",
            "recipient_label": "Owners",
            "subject": subject,
            "body": "Dear Sirs,\n\nInitial factual wording for human review.\n\nKind regards,",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _expected(item: dict) -> dict:
    return {
        "expected_state_fingerprint": item["state_fingerprint"],
        "expected_state_version": item["state_version"],
    }


def _submit(claim_id: str, item: dict):
    return client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/submit",
        json=_expected(item),
    )


def _review(claim_id: str, item: dict, *, action: str, note: str, confirm_re_review: bool = False):
    return client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/{action}",
        json={
            "note": note,
            "confirm_re_review": confirm_re_review,
            **_expected(item),
        },
    )


def test_stale_browser_state_fails_closed_after_material_edit() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    original = _create(claim_id)
    stale = dict(original)

    edited = client.patch(
        f"/api/v1/claims/{claim_id}/correspondence/{original['id']}",
        json={
            "body": "Dear Sirs,\n\nRevised factual wording after operator review.\n\nKind regards,",
            **_expected(original),
        },
    )
    assert edited.status_code == 200, edited.text
    current = edited.json()
    assert current["state_version"] == original["state_version"] + 1
    assert current["state_fingerprint"] != original["state_fingerprint"]

    stale_submit = _submit(claim_id, stale)
    assert stale_submit.status_code == 409
    assert "changed" in stale_submit.json()["detail"].lower()

    current_submit = _submit(claim_id, current)
    assert current_submit.status_code == 200
    assert current_submit.json()["status"] == "under_review"


def test_exact_review_retry_is_idempotent_and_does_not_duplicate_lineage() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    item = _create(claim_id)
    submitted = _submit(claim_id, item).json()

    first = _review(
        claim_id,
        submitted,
        action="approve",
        note="Manager reviewed the exact wording and recipient.",
    )
    assert first.status_code == 200, first.text
    first_item = first.json()
    assert len(first_item["review_history"]) == 1
    first_hash = first_item["latest_review"]["review_hash"]

    replay = _review(
        claim_id,
        submitted,
        action="approve",
        note="Manager reviewed the exact wording and recipient.",
    )
    assert replay.status_code == 200, replay.text
    replay_item = replay.json()
    assert len(replay_item["review_history"]) == 1
    assert replay_item["latest_review"]["review_hash"] == first_hash

    with TestingSessionLocal() as db:
        rows = list(db.scalars(select(CorrespondenceReviewDecision).where(
            CorrespondenceReviewDecision.correspondence_id == first_item["id"]
        )))
        assert len(rows) == 1


def test_rejected_revision_preserves_append_only_review_history_and_requires_explicit_rereview() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    item = _create(claim_id, "MT ORION re-review lineage")
    submitted = _submit(claim_id, item).json()
    rejected_response = _review(
        claim_id,
        submitted,
        action="reject",
        note="Recipient scope requires revision before approval.",
    )
    assert rejected_response.status_code == 200, rejected_response.text
    rejected = rejected_response.json()
    first_review = rejected["latest_review"]
    assert first_review["action"] == "reject"
    assert rejected["review_state"] == "current"

    revised_response = client.patch(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}",
        json={
            "recipient_label": "Owners and Lead Underwriter",
            **_expected(rejected),
        },
    )
    assert revised_response.status_code == 200, revised_response.text
    revised = revised_response.json()
    assert revised["status"] == "draft"
    assert revised["state_version"] == rejected["state_version"] + 1
    assert revised["review_state"] == "stale"
    assert len(revised["review_history"]) == 1
    assert revised["review_history"][0]["review_hash"] == first_review["review_hash"]

    resubmitted = _submit(claim_id, revised).json()
    without_confirmation = _review(
        claim_id,
        resubmitted,
        action="approve",
        note="Revised recipient and wording now reviewed.",
        confirm_re_review=False,
    )
    assert without_confirmation.status_code == 409
    assert "re-review" in without_confirmation.json()["detail"].lower()

    approved_response = _review(
        claim_id,
        resubmitted,
        action="approve",
        note="Revised recipient and wording now reviewed.",
        confirm_re_review=True,
    )
    assert approved_response.status_code == 200, approved_response.text
    approved = approved_response.json()
    assert approved["review_state"] == "current"
    assert len(approved["review_history"]) == 2
    assert approved["review_history"][1]["review_number"] == 2
    assert approved["review_history"][1]["previous_review_hash"] == first_review["review_hash"]
    assert approved["review_history"][1]["correspondence_state_fingerprint"] == approved["state_fingerprint"]


def test_external_dispatch_is_bound_to_exact_approved_review_and_retry_is_idempotent() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    item = _create(claim_id, "MT ORION dispatch binding")
    submitted = _submit(claim_id, item).json()
    approved = _review(
        claim_id,
        submitted,
        action="approve",
        note="Approved exact external wording.",
    ).json()

    wrong_review = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json={
            "confirm_sent": True,
            "channel": "email",
            "external_reference": "MAIL-13.9A",
            "expected_review_hash": "f" * 64,
            **_expected(approved),
        },
    )
    assert wrong_review.status_code == 409

    payload = {
        "confirm_sent": True,
        "channel": "email",
        "external_reference": "MAIL-13.9A",
        "expected_review_hash": approved["latest_review"]["review_hash"],
        **_expected(approved),
    }
    sent = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json=payload,
    )
    assert sent.status_code == 200, sent.text
    sent_item = sent.json()
    assert sent_item["sent_review_hash"] == approved["latest_review"]["review_hash"]

    replay = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["sent_at"] == sent_item["sent_at"]

    conflicting_replay = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json={**payload, "external_reference": "DIFFERENT-REF"},
    )
    assert conflicting_replay.status_code == 409
