from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _create_outbound(claim_id: str, sensitivity: str = "standard") -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/correspondence",
        json={
            "direction": "outbound",
            "kind": "status_update",
            "sensitivity": sensitivity,
            "recipient_label": "Owners and Underwriters",
            "subject": "MT ORION – Machinery casualty update",
            "body": "Dear Sirs,\n\nPlease find our factual status update for joint review.\n\nKind regards,",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _expected(item: dict) -> dict:
    return {
        "expected_state_fingerprint": item["state_fingerprint"],
        "expected_state_version": item["state_version"],
    }


def test_outbound_correspondence_requires_review_and_explicit_dispatch_confirmation() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    item = _create_outbound(claim_id, "without_prejudice")
    assert item["status"] == "draft"
    assert item["body"].startswith("WITHOUT PREJUDICE")
    assert len(item["state_fingerprint"]) == 64
    assert item["state_version"] == 1
    assert item["review_history"] == []

    premature = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json={
            "confirm_sent": True,
            "channel": "email",
            "expected_review_hash": "0" * 64,
            **_expected(item),
        },
    )
    assert premature.status_code == 409

    submitted = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/submit",
        json=_expected(item),
    )
    assert submitted.status_code == 200
    submitted_item = submitted.json()
    approved = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/approve",
        json={"note": "Factual framing and recipients reviewed.", **_expected(submitted_item)},
    )
    assert approved.status_code == 200
    approved_item = approved.json()
    assert len(approved_item["content_hash"]) == 64
    assert approved_item["review_state"] == "current"
    assert approved_item["latest_review"]["action"] == "approve"
    assert approved_item["latest_review"]["content_hash"] == approved_item["content_hash"]

    unconfirmed = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json={
            "confirm_sent": False,
            "channel": "email",
            "expected_review_hash": approved_item["latest_review"]["review_hash"],
            **_expected(approved_item),
        },
    )
    assert unconfirmed.status_code == 422
    sent = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/mark-sent",
        json={
            "confirm_sent": True,
            "channel": "email",
            "external_reference": "MAIL-42",
            "expected_review_hash": approved_item["latest_review"]["review_hash"],
            **_expected(approved_item),
        },
    )
    assert sent.status_code == 200, sent.text
    sent_item = sent.json()
    assert sent_item["status"] == "sent_externally"
    assert sent_item["sent_at"] is not None
    assert sent_item["sent_review_hash"] == approved_item["latest_review"]["review_hash"]

    immutable = client.patch(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}",
        json={"subject": "Changed after approval", **_expected(sent_item)},
    )
    assert immutable.status_code == 409

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == UUID(item["id"]))))
        assert {"CREATE_CORRESPONDENCE", "SUBMIT_CORRESPONDENCE_FOR_REVIEW", "APPROVE_CORRESPONDENCE", "MARK_CORRESPONDENCE_SENT_EXTERNALLY"}.issubset(actions)


def test_handler_cannot_approve_but_manager_can() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    item = _create_outbound(claim_id)
    submitted = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/submit",
        json=_expected(item),
    )
    assert submitted.status_code == 200
    submitted_item = submitted.json()

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/approve",
        json={"note": "Handler attempt must be rejected.", **_expected(submitted_item)},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/correspondence/{item['id']}/approve",
        json={"note": "Manager reviewed and approved the wording.", **_expected(submitted_item)},
    )
    assert approved.status_code == 200


def test_inbound_and_internal_records_are_filed_without_fake_sending() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    inbound = client.post(
        f"/api/v1/claims/{claim_id}/correspondence",
        json={
            "direction": "inbound",
            "kind": "follow_up",
            "sensitivity": "confidential",
            "sender_label": "Average Adjuster",
            "subject": "Request for repair invoices",
            "body": "Please provide the final repair invoices for our review.",
            "channel": "email",
            "external_reference": "AA-77",
        },
    )
    assert inbound.status_code == 201, inbound.text
    assert inbound.json()["status"] == "received_external"
    assert inbound.json()["sent_at"] is None
    assert len(inbound.json()["state_fingerprint"]) == 64

    internal = client.post(
        f"/api/v1/claims/{claim_id}/correspondence",
        json={
            "direction": "internal",
            "kind": "general",
            "sensitivity": "privileged_confidential",
            "subject": "Internal legal review note",
            "body": "Options remain subject to factual, technical and insurance assessment.",
        },
    )
    assert internal.status_code == 201, internal.text
    assert internal.json()["status"] == "filed_internal"
    assert internal.json()["body"].startswith("PRIVILEGED & CONFIDENTIAL")


def test_correspondence_is_tenant_scoped() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _create_outbound(claim_id)
    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/correspondence").status_code == 404
    assert client.post(
        f"/api/v1/claims/{claim_id}/correspondence",
        json={"direction": "internal", "kind": "general", "subject": "Cross tenant", "body": "Must not be created."},
    ).status_code == 404
