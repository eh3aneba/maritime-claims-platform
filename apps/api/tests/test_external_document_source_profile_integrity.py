from uuid import UUID

from app.modules.external_document_sources.models import (
    ExternalDocumentSourceProfile,
    ExternalDocumentSourceProfileReceipt,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_profiles import (
    _headers,
    _request_sharepoint,
    _seed_tenant,
)


def setup_function() -> None:
    reset_database()


def _approved_profile(slug: str):
    _, requester_id, approver_id, _ = _seed_tenant(slug)
    requester_headers = _headers(requester_id)
    approver_headers = _headers(approver_id)
    requested = _request_sharepoint(requester_headers)
    assert requested.status_code == 201, requested.text
    profile_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=approver_headers,
        json={"reason": "Independently approve the exact governed source profile configuration."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    return UUID(profile_id), approver_headers


def test_truncated_approval_receipt_fails_closed() -> None:
    profile_id, reader_headers = _approved_profile("truncated-chain")
    with TestingSessionLocal() as db:
        approval_receipt = (
            db.query(ExternalDocumentSourceProfileReceipt)
            .filter(
                ExternalDocumentSourceProfileReceipt.profile_id == profile_id,
                ExternalDocumentSourceProfileReceipt.event_type == "approved",
            )
            .one()
        )
        db.delete(approval_receipt)
        db.commit()

    blocked = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}",
        headers=reader_headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert "lifecycle" in blocked.text.lower()


def test_approval_decision_hash_drift_fails_closed_even_when_receipts_remain() -> None:
    profile_id, reader_headers = _approved_profile("decision-drift")
    with TestingSessionLocal() as db:
        profile = db.get(ExternalDocumentSourceProfile, profile_id)
        assert profile is not None
        profile.approval_hash = "0" * 64
        db.commit()

    blocked = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}",
        headers=reader_headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert "approval decision integrity" in blocked.text.lower()
