from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.correspondence.models import ClaimCorrespondence, CorrespondenceStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _invite() -> tuple[str, dict]:
    result = create_orion_claim(); claim_id = result["claim"]["id"]
    source = client.post(f"/api/v1/claims/{claim_id}/correspondence", json={
        "direction": "inbound", "kind": "status_update", "sensitivity": "standard",
        "sender_label": "Owners", "subject": "Joint factual casualty update",
        "body": "Reviewed factual update for controlled sharing.", "channel": "email",
    })
    assert source.status_code == 201, source.text
    created = client.post(f"/api/v1/claims/{claim_id}/external-portal/invitations", json={
        "participant_name": "Captain Graham", "participant_email": "captain@orion-shipping.com",
        "purpose": "Provide a controlled claim update and receive requested factual material.",
        "expires_in_hours": 48,
        "permission_manifest": ["claim_summary.view", "published_items.view", "submission.create"],
        "published_items": [],
    })
    assert created.status_code == 201, created.text
    return claim_id, created.json()


def test_portal_invitation_session_submission_and_human_promotion() -> None:
    claim_id, invitation = _invite()
    token = invitation["invitation_token"]
    assert len(token) >= 32 and invitation["published_items"] == []
    accepted = client.post("/api/v1/external-portal/accept", json={"invitation_token": token})
    assert accepted.status_code == 200, accepted.text
    session = accepted.json()["session_token"]
    replay = client.post("/api/v1/external-portal/accept", json={"invitation_token": token})
    assert replay.status_code == 410
    view = client.get("/api/v1/external-portal/session", headers={"X-MCRI-Portal-Session": session})
    assert view.status_code == 200
    assert view.json()["claim_reference"].startswith("MCRI-HM-")
    assert "current_reserve" not in view.json() and "estimated_loss" not in view.json()

    submitted = client.post("/api/v1/external-portal/submissions", headers={"X-MCRI-Portal-Session": session}, json={
        "subject": "Chief Engineer report submitted for review",
        "body": "The requested factual report is available for the claims team's review.",
        "attachment_manifests": [{"filename": "ce-report.pdf", "mime_type": "application/pdf",
                                  "file_size_bytes": 12000, "sha256": "b" * 64}],
    })
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["attachment_manifests"][0]["admission_status"] == "blocked_pending_quarantine"
    promoted = client.post(
        f"/api/v1/claims/{claim_id}/external-portal/submissions/{submitted.json()['id']}/review",
        json={"action": "promote", "confirm_promotion": True,
              "note": "Identity, claim context and factual content checked manually."},
    )
    assert promoted.status_code == 200 and promoted.json()["status"] == "promoted"
    with TestingSessionLocal() as db:
        correspondence = db.get(ClaimCorrespondence, UUID(promoted.json()["correspondence_id"]))
        assert correspondence.status == CorrespondenceStatus.RECEIVED_EXTERNAL
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == UUID(submitted.json()["id"]))))
        assert {"SUBMIT_EXTERNAL_PORTAL_MESSAGE", "PROMOTE_EXTERNAL_PORTAL_SUBMISSION"}.issubset(actions)

    revoked = client.post(f"/api/v1/claims/{claim_id}/external-portal/invitations/{invitation['id']}/revoke",
                          json={"note": "Collaboration purpose completed."})
    assert revoked.status_code == 200
    assert client.get("/api/v1/external-portal/session", headers={"X-MCRI-Portal-Session": session}).status_code == 410


def test_portal_is_tenant_scoped_and_permissions_are_allowlisted() -> None:
    claim_id, invitation = _invite()
    overbroad = client.post(f"/api/v1/claims/{claim_id}/external-portal/invitations", json={
        "participant_name": "External User", "participant_email": "external@partner-maritime.com",
        "purpose": "Attempt an overbroad external permission manifest.", "expires_in_hours": 12,
        "permission_manifest": ["settlements.view"], "published_items": [],
    })
    assert overbroad.status_code == 422
    client.cookies.clear(); login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/external-portal").status_code == 404
    assert client.post(f"/api/v1/claims/{claim_id}/external-portal/invitations/{invitation['id']}/revoke",
                       json={"note": "Cross tenant attempt."}).status_code == 403
