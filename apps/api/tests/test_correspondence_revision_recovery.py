from tests.db_harness import client, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _expected(item: dict) -> dict:
    return {
        "expected_state_fingerprint": item["state_fingerprint"],
        "expected_state_version": item["state_version"],
    }


def _create(claim_id: str, subject: str = "MT ORION revision recovery") -> dict:
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


def _submit(claim_id: str, item: dict) -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/submit",
        json=_expected(item),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve(claim_id: str, item: dict, *, note: str, confirm_re_review: bool = False):
    return client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/approve",
        json={
            "note": note,
            "confirm_re_review": confirm_re_review,
            **_expected(item),
        },
    )


def test_approved_unsent_can_be_reopened_without_rewriting_review_lineage() -> None:
    claim_id = create_orion_claim()["claim"]["id"]
    item = _create(claim_id)
    submitted = _submit(claim_id, item)
    approved_response = _approve(claim_id, submitted, note="Exact wording approved before dispatch.")
    assert approved_response.status_code == 200, approved_response.text
    approved = approved_response.json()
    first_review = approved["latest_review"]

    reopened_response = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/revise",
        json=_expected(approved),
    )
    assert reopened_response.status_code == 200, reopened_response.text
    reopened = reopened_response.json()
    assert reopened["status"] == "draft"
    assert reopened["state_fingerprint"] == approved["state_fingerprint"]
    assert reopened["state_version"] == approved["state_version"]
    assert reopened["content_hash"] is None
    assert reopened["review_note"] is None
    assert reopened["review_state"] == "current"
    assert len(reopened["review_history"]) == 1
    assert reopened["review_history"][0]["review_hash"] == first_review["review_hash"]

    replay = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/revise",
        json=_expected(reopened),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["review_history"] == reopened["review_history"]


def test_material_revision_after_reopen_gets_new_state_and_requires_explicit_rereview() -> None:
    claim_id = create_orion_claim()["claim"]["id"]
    item = _create(claim_id, "MT ORION controlled revision")
    approved = _approve(
        claim_id,
        _submit(claim_id, item),
        note="Initial approved state.",
    ).json()
    stale_browser_state = dict(approved)

    reopened = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/revise",
        json=_expected(approved),
    ).json()
    edited_response = client.patch(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}",
        json={
            "body": "Dear Sirs,\n\nRevised factual wording after deliberate recovery.\n\nKind regards,",
            **_expected(reopened),
        },
    )
    assert edited_response.status_code == 200, edited_response.text
    edited = edited_response.json()
    assert edited["state_version"] == approved["state_version"] + 1
    assert edited["state_fingerprint"] != approved["state_fingerprint"]
    assert edited["review_state"] == "stale"
    assert len(edited["review_history"]) == 1

    stale_competing_write = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/submit",
        json=_expected(stale_browser_state),
    )
    assert stale_competing_write.status_code == 409

    resubmitted = _submit(claim_id, edited)
    no_confirmation = _approve(
        claim_id,
        resubmitted,
        note="Revised exact wording approved.",
        confirm_re_review=False,
    )
    assert no_confirmation.status_code == 409
    assert "re-review" in no_confirmation.json()["detail"].lower()

    reapproved_response = _approve(
        claim_id,
        resubmitted,
        note="Revised exact wording approved.",
        confirm_re_review=True,
    )
    assert reapproved_response.status_code == 200, reapproved_response.text
    reapproved = reapproved_response.json()
    assert reapproved["review_state"] == "current"
    assert len(reapproved["review_history"]) == 2
    assert reapproved["latest_review"]["review_number"] == 2
    assert reapproved["latest_review"]["previous_review_hash"] == approved["latest_review"]["review_hash"]
    assert reapproved["latest_review"]["correspondence_state_fingerprint"] == reapproved["state_fingerprint"]


def test_sent_correspondence_remains_immutable_and_cannot_be_reopened() -> None:
    claim_id = create_orion_claim()["claim"]["id"]
    item = _create(claim_id, "MT ORION immutable sent record")
    approved = _approve(
        claim_id,
        _submit(claim_id, item),
        note="Approved exact external wording.",
    ).json()
    sent_response = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json={
            "confirm_sent": True,
            "channel": "email",
            "external_reference": "MCRI-13.9C-IMMUTABLE",
            "expected_review_hash": approved["latest_review"]["review_hash"],
            **_expected(approved),
        },
    )
    assert sent_response.status_code == 200, sent_response.text
    sent = sent_response.json()

    reopen = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/revise",
        json=_expected(sent),
    )
    assert reopen.status_code == 409
    assert "immutable" in reopen.json()["detail"].lower()

    current = client.get(f"/api/v1/claims/{claim_id}/correspondence").json()["items"]
    same = next(row for row in current if row["id"] == item["id"])
    assert same["status"] == "sent_externally"
    assert same["sent_review_hash"] == sent["sent_review_hash"]
    assert same["sent_at"] == sent["sent_at"]
