from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_durable_read_reauthorized_renewal_health_service as phase_t_service
from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_reauthorized_renewal_routing import (
    _activate_happy_s,
    _approved_r,
    _rollback_s,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Assess the completed Phase S reauthorized renewal window from immutable operational evidence."
QUALIFY_REASON = "Independently qualify the completed Phase S renewal health evidence as reviewed."
REJECT_REASON = "Reject the Phase S renewal health evidence after independent governance review."


def _completed_s(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_r(monkeypatch, tmp_path, endpoint, slug=slug)
    lease_id, activator_headers = _activate_happy_s(data, slug=slug)
    download = client.get(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
        headers=data["manager_headers"],
    )
    assert download.status_code == 200, download.text
    assert download.headers["X-MCRI-Evidence-Read-Source"] == (
        "recovery-replica-durable-reauthorized-renewal"
    )
    rolled_back = _rollback_s(data, lease_id, headers=activator_headers)
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"
    data["phase_s_lease_id"] = lease_id
    return data


def _request_t(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-health-qualification",
        headers=headers or data["admin_headers"],
        json={
            "reauthorized_renewal_lease_id": data["phase_s_lease_id"],
            "reason": reason,
        },
    )


def _qualify_t(data, qualification_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-health-qualifications/{qualification_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_t_qualifies_completed_phase_s_health_without_new_authority(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_s(monkeypatch, tmp_path, endpoint, slug="phase-t-happy")
        requested = _request_t(data)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        qualification = body["qualification"]
        qualification_id = qualification["id"]
        assert qualification["reauthorized_renewal_lease_id"] == data["phase_s_lease_id"]
        assert qualification["health_state"] == "healthy"
        assert qualification["verified_durable_read_count"] >= 1
        assert qualification["integrity_failure_count"] == 0
        assert qualification["storage_unavailable_count"] == 0
        assert qualification["routable_authority_created"] is False
        assert qualification["durable_read_route_created"] is False
        assert qualification["read_path_switched"] is False
        assert qualification["write_path_switched"] is False
        assert qualification["document_storage_key_mutated"] is False
        assert qualification["authoritative_storage_changed"] is False
        assert qualification["destructive_action_performed"] is False

        replay = _request_t(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == qualification_id
        changed_replay = _request_t(
            data,
            reason="Use a different Phase T request reason for the already-bound Phase S lease.",
        )
        assert changed_replay.status_code == 409

        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-t-happy-qualifier")
        qualified = _qualify_t(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["status"] == "qualified"
        assert qualified.json()["qualification"]["qualified_by_id"] == str(qualifier_id)

        manager_get = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-health-qualifications/{qualification_id}",
            headers=data["manager_headers"],
        )
        assert manager_get.status_code == 200, manager_get.text
        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-health-qualifications/{qualification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]

        manager_mutation = _request_t(data, headers=data["manager_headers"])
        assert manager_mutation.status_code == 403

        with TestingSessionLocal() as db:
            stored = db.get(
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
                UUID(qualification_id),
            )
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert stored is not None
            assert stored.status == "qualified"
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_durable_renewal_lease_id is None
            assert route.active_durable_reauthorized_renewal_lease_id is None

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(
            slug="phase-t-other", storage_root=tmp_path / "other"
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-health-qualifications/{qualification_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_t_enforces_independent_qualifier(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_s(monkeypatch, tmp_path, endpoint, slug="phase-t-four-eyes")
        requested = _request_t(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        same_requester = _qualify_t(data, qualification_id, headers=data["admin_headers"])
        assert same_requester.status_code == 409
        s_activator = _qualify_t(
            data, qualification_id, headers=data["phase_s_activator_headers"]
        )
        assert s_activator.status_code == 409
        r_approver = _qualify_t(
            data, qualification_id, headers=data["phase_r_approver_headers"]
        )
        assert r_approver.status_code == 409
        q_qualifier = _qualify_t(
            data, qualification_id, headers=data["phase_q_qualifier_headers"]
        )
        assert q_qualifier.status_code == 409
        p_activator = _qualify_t(
            data, qualification_id, headers=data["renewal_admin_headers"]
        )
        assert p_activator.status_code == 409

        _, independent_headers = _independent_admin(data, slug="phase-t-independent")
        qualified = _qualify_t(data, qualification_id, headers=independent_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"


def test_phase_t_storage_outage_is_retryable_and_does_not_terminalize_pending(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_s(monkeypatch, tmp_path, endpoint, slug="phase-t-outage")
        requested = _request_t(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-t-outage-qualifier")
        original_reader = phase_t_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase T storage outage")

        monkeypatch.setattr(phase_t_service, "_read_verified_candidate", unavailable)
        outage = _qualify_t(data, qualification_id, headers=qualifier_headers)
        assert outage.status_code == 503
        with TestingSessionLocal() as db:
            stored = db.get(
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
                UUID(qualification_id),
            )
            assert stored is not None and stored.status == "pending_second_approval"
        monkeypatch.setattr(phase_t_service, "_read_verified_candidate", original_reader)

        qualified = _qualify_t(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"


def test_phase_t_records_degraded_window_from_phase_s_storage_failure(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-t-degraded")
        lease_id, activator_headers = _activate_happy_s(data, slug="phase-t-degraded")
        original_reader = __import__(
            "app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_service",
            fromlist=["_read_verified_candidate"],
        )._read_verified_candidate
        phase_s_module = __import__(
            "app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_service",
            fromlist=["_read_verified_candidate"],
        )

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase S storage outage")

        monkeypatch.setattr(phase_s_module, "_read_verified_candidate", unavailable)
        outage = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert outage.status_code == 503
        monkeypatch.setattr(phase_s_module, "_read_verified_candidate", original_reader)
        successful = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert successful.status_code == 200, successful.text
        assert _rollback_s(data, lease_id, headers=activator_headers).status_code == 200
        data["phase_s_lease_id"] = lease_id

        requested = _request_t(data)
        assert requested.status_code == 201, requested.text
        qualification = requested.json()["qualification"]
        assert qualification["health_state"] == "degraded"
        assert qualification["storage_unavailable_count"] >= 1
        _, qualifier_headers = _independent_admin(data, slug="phase-t-degraded-qualifier")
        assessed = _qualify_t(data, qualification["id"], headers=qualifier_headers)
        assert assessed.status_code == 200, assessed.text
        assert assessed.json()["outcome"] == "degraded"
        assert assessed.json()["qualification"]["status"] == "degraded"
        assert assessed.json()["qualification"]["routable_authority_created"] is False
        assert assessed.json()["qualification"]["authoritative_storage_changed"] is False
