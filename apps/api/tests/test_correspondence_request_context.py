from __future__ import annotations

from uuid import UUID

from app.modules.claims.models import Claim, ClaimStatus
from app.modules.rules.models import ClaimDocumentRequirement, RequirementStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _expected(item: dict) -> dict:
    return {
        "expected_state_fingerprint": item["state_fingerprint"],
        "expected_state_version": item["state_version"],
    }


def _prepare_request(claim_id: str) -> tuple[dict, dict]:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        claim.status = ClaimStatus.TRIAGE
        db.commit()
    evaluated = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    requirement = evaluated.json()["summary"]["requirements"][0]
    created = client.post(
        f"/api/v1/claims/{claim_id}/document-requests",
        json={"requirement_ids": [requirement["id"]], "recipient_label": "Owners"},
    )
    assert created.status_code == 201, created.text
    return requirement, created.json()["batch"]


def _linked_item(claim_id: str, batch_id: str) -> dict:
    listed = client.get(f"/api/v1/claims/{claim_id}/correspondence")
    assert listed.status_code == 200, listed.text
    return next(item for item in listed.json()["items"] if item["request_batch_id"] == batch_id)


def _approve(claim_id: str, item: dict, *, re_review: bool = False) -> dict:
    submitted = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/submit",
        json=_expected(item),
    )
    assert submitted.status_code == 200, submitted.text
    submitted_item = submitted.json()
    approved = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/approve",
        json={
            "note": "Human manager reviewed the exact communication and linked request context.",
            "confirm_re_review": re_review,
            **_expected(submitted_item),
        },
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _mark_sent(claim_id: str, item: dict, reference: str):
    return client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json={
            "confirm_sent": True,
            "channel": "email",
            "external_reference": reference,
            "expected_review_hash": item["latest_review"]["review_hash"],
            **_expected(item),
        },
    )


def test_request_context_change_stales_approval_and_requires_deliberate_rereview() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    requirement, batch = _prepare_request(claim_id)
    item = _linked_item(claim_id, batch["id"])
    approved = _approve(claim_id, item)

    first_review = approved["latest_review"]
    assert first_review["request_context_fingerprint"] is not None
    assert len(first_review["request_context_fingerprint"]) == 64
    assert approved["review_state"] == "current"

    with TestingSessionLocal() as db:
        row = db.get(ClaimDocumentRequirement, UUID(requirement["id"]))
        assert row is not None
        row.status = RequirementStatus.RECEIVED
        row.satisfaction_basis = "document_processing_pending"
        db.commit()

    refreshed = _linked_item(claim_id, batch["id"])
    assert refreshed["state_fingerprint"] == approved["state_fingerprint"]
    assert refreshed["state_version"] == approved["state_version"]
    assert refreshed["review_state"] == "stale"

    stale_dispatch = _mark_sent(claim_id, approved, "REQ-CONTEXT-STALE")
    assert stale_dispatch.status_code == 409
    assert "request" in stale_dispatch.json()["detail"].lower()
    assert "re-review" in stale_dispatch.json()["detail"].lower()

    resubmitted = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{approved['id']}/submit",
        json=_expected(approved),
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["status"] == "under_review"
    assert resubmitted.json()["state_version"] == approved["state_version"]

    reapproved = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{approved['id']}/approve",
        json={
            "note": "Human manager deliberately re-reviewed the evolved document-request context.",
            "confirm_re_review": True,
            **_expected(resubmitted.json()),
        },
    )
    assert reapproved.status_code == 200, reapproved.text
    reapproved_item = reapproved.json()
    assert reapproved_item["review_state"] == "current"
    assert len(reapproved_item["review_history"]) == 2
    assert reapproved_item["latest_review"]["review_hash"] != first_review["review_hash"]
    assert reapproved_item["latest_review"]["request_context_fingerprint"] != first_review["request_context_fingerprint"]

    sent = _mark_sent(claim_id, reapproved_item, "REQ-CONTEXT-CURRENT")
    assert sent.status_code == 200, sent.text
    sent_item = sent.json()
    assert sent_item["status"] == "sent_externally"
    # Dispatch changes batch/requirement state by design, but the historical sent record remains
    # bound to the exact review that authorized the external dispatch.
    assert sent_item["review_state"] == "current"
    assert sent_item["sent_review_hash"] == reapproved_item["latest_review"]["review_hash"]

    historical = _linked_item(claim_id, batch["id"])
    assert historical["review_state"] == "current"
    assert historical["sent_review_hash"] == sent_item["sent_review_hash"]


def test_unrelated_requirement_change_does_not_stale_freeform_correspondence() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    requirement, _ = _prepare_request(claim_id)

    created = client.post(
        f"/api/v1/claims/{claim_id}/correspondence",
        json={
            "direction": "outbound",
            "kind": "status_update",
            "sensitivity": "standard",
            "recipient_label": "Lead Underwriter",
            "subject": "MT ORION factual status update",
            "body": "Dear Sirs,\n\nThis is a free-form factual status update for human review.\n\nKind regards,",
        },
    )
    assert created.status_code == 201, created.text
    approved = _approve(claim_id, created.json())
    assert approved["latest_review"]["request_context_fingerprint"] is None

    with TestingSessionLocal() as db:
        row = db.get(ClaimDocumentRequirement, UUID(requirement["id"]))
        assert row is not None
        row.status = RequirementStatus.RECEIVED
        row.satisfaction_basis = "document_processing_pending"
        db.commit()

    listed = client.get(f"/api/v1/claims/{claim_id}/correspondence").json()["items"]
    freeform = next(item for item in listed if item["id"] == approved["id"])
    assert freeform["review_state"] == "current"
    sent = _mark_sent(claim_id, freeform, "FREEFORM-CURRENT")
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent_externally"
