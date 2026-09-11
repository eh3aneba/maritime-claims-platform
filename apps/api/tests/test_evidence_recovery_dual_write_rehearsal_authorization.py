from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_read_ownership_transition_health_service as phase_w_service
from app.modules.documents.recovery_dual_write_rehearsal_authorization_models import (
    EvidenceRecoveryDualWriteRehearsalAuthorization,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_read_ownership_transition_health_qualification import (
    _completed_v,
    _qualify_w,
    _request_w,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Authorize one bounded future dual-write rehearsal from healthy Phase W evidence."
APPROVE_REASON = "Independently approve the bounded Phase X rehearsal authorization envelope."


def _qualified_w(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _completed_v(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_w(data)
    assert requested.status_code == 201, requested.text
    qid = requested.json()["qualification"]["id"]
    qualifier_id, qualifier_headers = _independent_admin(data, slug=f"{slug}-w-qualifier")
    qualified = _qualify_w(data, qid, headers=qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_w_qualification_id"] = qid
    data["phase_w_qualifier_id"] = qualifier_id
    data["phase_w_qualifier_headers"] = qualifier_headers
    return data


def _request_x(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-health-qualifications/{data['phase_w_qualification_id']}/dual-write-rehearsal-authorization",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _approve_x(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_x_authorizes_only_future_bounded_rehearsal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_w(monkeypatch, tmp_path, endpoint, slug="phase-x-happy")
        requested = _request_x(data)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        authorization = body["authorization"]
        authorization_id = authorization["id"]
        assert authorization["phase_w_health_qualification_id"] == data["phase_w_qualification_id"]
        assert authorization["health_state"] == "healthy"
        assert authorization["max_rehearsal_writes"] == 1
        assert authorization["rehearsal_executed"] is False
        assert authorization["dual_write_active"] is False
        assert authorization["durable_write_authority_created"] is False
        assert authorization["read_path_switched"] is False
        assert authorization["write_path_switched"] is False
        assert authorization["document_storage_key_mutated"] is False
        assert authorization["authoritative_storage_changed"] is False
        assert authorization["s3_copy_performed"] is False
        assert authorization["s3_delete_performed"] is False
        assert authorization["local_delete_performed"] is False

        replay = _request_x(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id
        changed = _request_x(data, reason="Request the same Phase X authorization using intentionally changed semantics.")
        assert changed.status_code == 409

        same_requester = _approve_x(data, authorization_id, headers=data["admin_headers"])
        assert same_requester.status_code == 409
        w_qualifier = _approve_x(data, authorization_id, headers=data["phase_w_qualifier_headers"])
        assert w_qualifier.status_code == 409
        v_activator = _approve_x(data, authorization_id, headers=data["phase_v_activator_headers"])
        assert v_activator.status_code == 409
        u_approver = _approve_x(data, authorization_id, headers=data["phase_u_approver_headers"])
        assert u_approver.status_code == 409

        approver_id, approver_headers = _independent_admin(data, slug="phase-x-happy-approver")
        approved = _approve_x(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        approved_auth = approved.json()["authorization"]
        assert approved_auth["approved_by_id"] == str(approver_id)
        assert approved_auth["authorization_expires_at"] is not None
        assert approved_auth["rehearsal_executed"] is False
        assert approved_auth["dual_write_active"] is False
        assert approved_auth["write_path_switched"] is False

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDualWriteRehearsalAuthorization, UUID(authorization_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "approved"
            assert stored.rehearsal_executed is False
            assert stored.dual_write_active is False
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.write_path_switched is False
            assert route.authoritative_storage_changed is False

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-x-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-authorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_x_storage_outage_is_retryable_and_keeps_pending(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_w(monkeypatch, tmp_path, endpoint, slug="phase-x-outage")
        requested = _request_x(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        _, approver_headers = _independent_admin(data, slug="phase-x-outage-approver")
        original_reader = phase_w_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase X storage outage")

        monkeypatch.setattr(phase_w_service, "_read_verified_candidate", unavailable)
        outage = _approve_x(data, authorization_id, headers=approver_headers)
        assert outage.status_code == 503
        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDualWriteRehearsalAuthorization, UUID(authorization_id))
            assert stored is not None and stored.status == "pending_second_approval"
        monkeypatch.setattr(phase_w_service, "_read_verified_candidate", original_reader)

        approved = _approve_x(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
