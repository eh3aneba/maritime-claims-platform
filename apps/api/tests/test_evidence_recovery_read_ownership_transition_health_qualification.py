from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_read_ownership_transition_health_service as phase_w_service
from app.modules.documents.recovery_read_ownership_transition_health_models import (
    EvidenceRecoveryReadOwnershipTransitionHealthQualification,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_read_ownership_transition_routing import (
    _activate_v,
    _approved_u,
    _prepare_v,
    _rollback_v,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Assess the completed Phase V read-ownership transition from immutable operational evidence."
QUALIFY_REASON = "Independently qualify the completed Phase V read-ownership transition health evidence."


def _completed_v(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_u(monkeypatch, tmp_path, endpoint, slug=slug)
    prepared = _prepare_v(data)
    assert prepared.status_code == 201, prepared.text
    lease_id = prepared.json()["lease"]["id"]
    activator_id, activator_headers = _independent_admin(data, slug=f"{slug}-v-activator")
    activated = _activate_v(data, lease_id, headers=activator_headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["outcome"] == "activated"
    download = client.get(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
        headers=data["manager_headers"],
    )
    assert download.status_code == 200, download.text
    assert download.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica-read-ownership-transition"
    rolled_back = _rollback_v(data, lease_id, headers=activator_headers)
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"
    data["phase_v_lease_id"] = lease_id
    data["phase_v_activator_id"] = activator_id
    data["phase_v_activator_headers"] = activator_headers
    return data


def _request_w(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-health-qualification",
        headers=headers or data["admin_headers"],
        json={"transition_lease_id": data["phase_v_lease_id"], "reason": reason},
    )


def _qualify_w(data, qualification_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-health-qualifications/{qualification_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_w_qualifies_completed_phase_v_without_new_authority(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_v(monkeypatch, tmp_path, endpoint, slug="phase-w-happy")
        requested = _request_w(data)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        q = body["qualification"]
        qid = q["id"]
        assert q["transition_lease_id"] == data["phase_v_lease_id"]
        assert q["health_state"] == "healthy"
        assert q["verified_read_count"] >= 1
        assert q["integrity_failure_count"] == 0
        assert q["storage_unavailable_count"] == 0
        assert q["routable_authority_created"] is False
        assert q["durable_read_route_created"] is False
        assert q["read_ownership_authority_created"] is False
        assert q["read_path_switched"] is False
        assert q["write_path_switched"] is False
        assert q["authoritative_storage_changed"] is False

        replay = _request_w(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == qid
        changed = _request_w(data, reason="Request the same Phase W evidence with intentionally changed semantics.")
        assert changed.status_code == 409

        same_requester = _qualify_w(data, qid, headers=data["admin_headers"])
        assert same_requester.status_code == 409
        v_activator = _qualify_w(data, qid, headers=data["phase_v_activator_headers"])
        assert v_activator.status_code == 409
        u_approver = _qualify_w(data, qid, headers=data["phase_u_approver_headers"])
        assert u_approver.status_code == 409

        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-w-happy-qualifier")
        qualified = _qualify_w(data, qid, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["qualified_by_id"] == str(qualifier_id)

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-health-qualifications/{qid}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionHealthQualification, UUID(qid))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "qualified"
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_read_ownership_transition_lease_id is None

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-w-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-health-qualifications/{qid}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_w_storage_outage_is_retryable_and_keeps_pending(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_v(monkeypatch, tmp_path, endpoint, slug="phase-w-outage")
        requested = _request_w(data)
        assert requested.status_code == 201, requested.text
        qid = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-w-outage-qualifier")
        original_reader = phase_w_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase W storage outage")

        monkeypatch.setattr(phase_w_service, "_read_verified_candidate", unavailable)
        outage = _qualify_w(data, qid, headers=qualifier_headers)
        assert outage.status_code == 503
        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionHealthQualification, UUID(qid))
            assert stored is not None and stored.status == "pending_second_approval"
        monkeypatch.setattr(phase_w_service, "_read_verified_candidate", original_reader)

        qualified = _qualify_w(data, qid, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
