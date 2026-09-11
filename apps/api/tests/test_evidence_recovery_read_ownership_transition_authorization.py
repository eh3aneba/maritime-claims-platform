from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_durable_read_reauthorized_renewal_health_service as phase_t_service
from app.modules.documents.recovery_read_ownership_transition_authorization_models import (
    EvidenceRecoveryReadOwnershipTransitionAuthorization,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_reauthorized_renewal_health_qualification import (
    _completed_s,
    _qualify_t,
    _request_t,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Authorize one later bounded stronger recovery read-ownership transition from healthy Phase T evidence."
APPROVE_REASON = "Independently approve the bounded Phase U recovery read-ownership transition authorization."


def _qualified_t(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _completed_s(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_t(data)
    assert requested.status_code == 201, requested.text
    qualification_id = requested.json()["qualification"]["id"]
    qualifier_id, qualifier_headers = _independent_admin(data, slug=f"{slug}-t-qualifier")
    qualified = _qualify_t(data, qualification_id, headers=qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_t_health_qualification_id"] = qualification_id
    data["phase_t_qualifier_id"] = qualifier_id
    data["phase_t_qualifier_headers"] = qualifier_headers
    return data


def _request_u(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-health-qualifications/{data['phase_t_health_qualification_id']}/read-ownership-transition-authorization",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _approve_u(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_u_authorizes_from_healthy_t_without_changing_authority(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_t(monkeypatch, tmp_path, endpoint, slug="phase-u-happy")
        requested = _request_u(data)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        authorization = body["authorization"]
        authorization_id = authorization["id"]
        assert authorization["phase_t_health_qualification_id"] == data["phase_t_health_qualification_id"]
        assert authorization["health_state"] == "healthy"
        assert authorization["verified_durable_read_count"] >= 1
        assert authorization["integrity_failure_count"] == 0
        assert authorization["storage_unavailable_count"] == 0
        assert authorization["routable_authority_created"] is False
        assert authorization["durable_read_route_created"] is False
        assert authorization["read_path_switched"] is False
        assert authorization["write_path_switched"] is False
        assert authorization["document_storage_key_mutated"] is False
        assert authorization["authoritative_storage_changed"] is False
        assert authorization["destructive_action_performed"] is False

        replay = _request_u(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id
        changed = _request_u(
            data,
            reason="Use a different Phase U request reason for the same qualified Phase T record.",
        )
        assert changed.status_code == 409

        assert _approve_u(data, authorization_id, headers=data["admin_headers"]).status_code == 409
        assert _approve_u(data, authorization_id, headers=data["phase_t_qualifier_headers"]).status_code == 409
        assert _approve_u(data, authorization_id, headers=data["phase_s_activator_headers"]).status_code == 409
        assert _approve_u(data, authorization_id, headers=data["phase_r_approver_headers"]).status_code == 409
        assert _approve_u(data, authorization_id, headers=data["phase_q_qualifier_headers"]).status_code == 409
        assert _approve_u(data, authorization_id, headers=data["renewal_admin_headers"]).status_code == 409

        approver_id, approver_headers = _independent_admin(data, slug="phase-u-happy-approver")
        approved = _approve_u(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        assert approved.json()["authorization"]["approved_by_id"] == str(approver_id)
        assert approved.json()["authorization"]["authorization_expires_at"] is not None

        manager_get = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-authorizations/{authorization_id}",
            headers=data["manager_headers"],
        )
        assert manager_get.status_code == 200, manager_get.text
        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        assert _request_u(data, headers=data["manager_headers"]).status_code == 403

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionAuthorization, UUID(authorization_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert stored is not None and stored.status == "approved"
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_durable_renewal_lease_id is None
            assert route.active_durable_reauthorized_renewal_lease_id is None
            assert route.active_replica_id is None

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(
            slug="phase-u-other", storage_root=tmp_path / "other"
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-authorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_u_approval_storage_outage_is_retryable(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_t(monkeypatch, tmp_path, endpoint, slug="phase-u-outage")
        requested = _request_u(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        _, approver_headers = _independent_admin(data, slug="phase-u-outage-approver")
        original_reader = phase_t_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase U fresh-preflight storage outage")

        monkeypatch.setattr(phase_t_service, "_read_verified_candidate", unavailable)
        outage = _approve_u(data, authorization_id, headers=approver_headers)
        assert outage.status_code == 503
        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionAuthorization, UUID(authorization_id))
            assert stored is not None and stored.status == "pending_second_approval"
        monkeypatch.setattr(phase_t_service, "_read_verified_candidate", original_reader)

        approved = _approve_u(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"


def test_phase_u_route_drift_after_request_invalidates_fail_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_t(monkeypatch, tmp_path, endpoint, slug="phase-u-route-drift")
        requested = _request_u(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        _, approver_headers = _independent_admin(data, slug="phase-u-route-drift-approver")

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        invalidated = _approve_u(data, authorization_id, headers=approver_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["authorization"]["status"] == "invalidated"
        assert invalidated.json()["authorization"]["authoritative_storage_changed"] is False
        assert invalidated.json()["authorization"]["read_path_switched"] is False
