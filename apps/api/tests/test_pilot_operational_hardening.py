from tests.db_harness import client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


CONTROLS = {
    "tls": True, "secret_references": True, "backup_restore": True, "migrations": True,
    "malware_scan": True, "least_privilege": True, "retention": True, "incident_contacts": True,
}


def test_deployment_readiness_requires_all_controls_and_manager_attestation() -> None:
    create_orion_claim()
    blocked = client.post("/api/v1/pilot-operations/readiness", json={
        "environment": "pilot", "review_key": "review-one", "controls": {**CONTROLS, "backup_restore": False},
    })
    assert blocked.status_code == 201 and blocked.json()["status"] == "blocked"
    assert client.post(f"/api/v1/pilot-operations/readiness/{blocked.json()['id']}/attest", json={
        "confirm_ready": True, "note": "Cannot override a failed backup restore exercise.",
    }).status_code == 409
    ready = client.post("/api/v1/pilot-operations/readiness", json={
        "environment": "pilot", "review_key": "review-two", "controls": CONTROLS,
    })
    assert ready.status_code == 201 and len(ready.json()["snapshot_hash"]) == 64
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    assert client.post(f"/api/v1/pilot-operations/readiness/{ready.json()['id']}/attest", json={
        "confirm_ready": True, "note": "Handler must not attest deployment readiness.",
    }).status_code == 403
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    attested = client.post(f"/api/v1/pilot-operations/readiness/{ready.json()['id']}/attest", json={
        "confirm_ready": True, "note": "All eight controls reviewed against pilot evidence.",
    })
    assert attested.status_code == 200 and attested.json()["status"] == "ready"


def test_monitoring_is_idempotent_content_free_and_incidents_have_lifecycle() -> None:
    create_orion_claim()
    payload = {"idempotency_key": "aaaaaaaa", "pending_intake_threshold": 1,
               "adapter_failure_threshold": 1, "expired_portal_threshold": 1}
    first = client.post("/api/v1/pilot-operations/monitor-runs", json=payload)
    second = client.post("/api/v1/pilot-operations/monitor-runs", json=payload)
    assert first.status_code == 201 and first.json()["id"] == second.json()["id"]
    assert set(first.json()["metrics"]) == {"failed_adapter_runs", "pending_email_intake", "expired_or_revoked_portal_sessions", "retention_runs"}
    incident = client.post("/api/v1/pilot-operations/incidents", json={
        "monitor_run_id": first.json()["id"], "severity": "high", "category": "availability",
        "title": "Pilot adapter unavailable", "summary": "The bounded provider adapter requires operational investigation.",
        "owner_label": "Pilot Operations Lead",
    })
    assert incident.status_code == 201 and incident.json()["status"] == "open"
    acknowledged = client.post(f"/api/v1/pilot-operations/incidents/{incident.json()['id']}/transition",
                               json={"action": "acknowledge", "note": "Operations owner accepted the incident."})
    resolved = client.post(f"/api/v1/pilot-operations/incidents/{incident.json()['id']}/transition",
                           json={"action": "resolve", "note": "Adapter restored and bounded run verified."})
    assert acknowledged.json()["status"] == "acknowledged" and resolved.json()["status"] == "resolved"
    client.cookies.clear(); login("beta", "beta-handler@example.com")
    beta = client.get("/api/v1/pilot-operations")
    assert beta.status_code == 200 and beta.json()["incidents"] == []


def test_external_publication_requires_different_reviewer() -> None:
    result = create_orion_claim(); claim_id = result["claim"]["id"]
    source = client.post(f"/api/v1/claims/{claim_id}/correspondence", json={
        "direction": "inbound", "kind": "status_update", "sensitivity": "standard",
        "sender_label": "Owners", "subject": "Reviewed operational update",
        "body": "Factual status reviewed for possible controlled sharing.", "channel": "email",
    })
    invitation = client.post(f"/api/v1/claims/{claim_id}/external-portal/invitations", json={
        "participant_name": "Captain Graham", "participant_email": "captain@orion-shipping.com",
        "purpose": "Controlled exchange of factual claim updates with the vessel owner.",
        "expires_in_hours": 48, "permission_manifest": ["claim_summary.view", "published_items.view"],
        "published_items": [],
    }).json()
    token = invitation["invitation_token"]
    direct = client.post(f"/api/v1/claims/{claim_id}/external-portal/invitations", json={
        "participant_name": "Surveyor", "participant_email": "surveyor@marine-partner.com",
        "purpose": "Attempt direct publication that must be rejected by the new workflow.",
        "expires_in_hours": 24, "permission_manifest": ["published_items.view"],
        "published_items": [{"item_type": "correspondence", "source_id": source.json()["id"], "title": "Direct share"}],
    })
    assert direct.status_code == 422
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    proposal = client.post(f"/api/v1/claims/{claim_id}/external-portal/invitations/{invitation['id']}/publications", json={
        "item_type": "correspondence", "source_id": source.json()["id"],
        "title": "Approved factual update", "summary": "No privileged or financial content.",
    })
    assert proposal.status_code == 201 and proposal.json()["status"] == "under_review"
    assert client.post(f"/api/v1/claims/{claim_id}/external-portal/publications/{proposal.json()['id']}/review",
                       json={"action": "approve", "note": "Self approval must fail."}).status_code == 403
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    approved = client.post(f"/api/v1/claims/{claim_id}/external-portal/publications/{proposal.json()['id']}/review",
                           json={"action": "approve", "note": "Source eligibility and external wording checked."})
    assert approved.status_code == 200 and approved.json()["published_item_id"]
    session = client.post("/api/v1/external-portal/accept", json={"invitation_token": token}).json()["session_token"]
    view = client.get("/api/v1/external-portal/session", headers={"X-MCRI-Portal-Session": session})
    assert view.status_code == 200 and view.json()["published_items"][0]["title"] == "Approved factual update"


def test_governance_approval_blocks_then_authorizes_manifest_only_exit() -> None:
    result = create_orion_claim(); claim_id = result["claim"]["id"]
    profile = client.put("/api/v1/pilot-operations/governance", json={
        "pilot_purpose": "Controlled validation of the H&M machinery claims workflow with designated users.",
        "legal_basis": "Documented contractual pilot and organization authorization.",
        "data_owner": "Alpha Marine Claims Director",
        "retention_statement": "Pilot records follow documented staging and claim-record retention responsibilities.",
        "residency_statement": "Pilot hosting region and subprocessors are recorded in the deployment register.",
        "exit_contact": "exit-control@alpha-maritime.com",
    })
    assert profile.status_code == 200 and profile.json()["status"] == "draft"
    blocked = client.post(f"/api/v1/pilot-operations/claims/{claim_id}/exit-manifests", json={
        "idempotency_key": "bbbbbbbb", "confirm_manifest_only": True,
    })
    assert blocked.status_code == 409
    approved = client.post("/api/v1/pilot-operations/governance/approve", json={
        "confirm_approved": True, "note": "Purpose, legal basis, ownership, retention, residency and exit contact reviewed.",
    })
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    created = client.post(f"/api/v1/pilot-operations/claims/{claim_id}/exit-manifests", json={
        "idempotency_key": "bbbbbbbb", "confirm_manifest_only": True,
    })
    duplicate = client.post(f"/api/v1/pilot-operations/claims/{claim_id}/exit-manifests", json={
        "idempotency_key": "bbbbbbbb", "confirm_manifest_only": True,
    })
    assert created.status_code == 201 and created.json()["id"] == duplicate.json()["id"]
    manifest = created.json()["manifest"]
    assert manifest["content_included"] is False and manifest["deletion_performed"] is False
    assert set(manifest["counts"]) == {"documents", "correspondence", "portal_submissions", "linked_email_messages"}
    assert len(created.json()["manifest_checksum"]) == 64
