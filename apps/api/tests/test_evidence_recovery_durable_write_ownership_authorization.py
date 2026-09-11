from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_durable_write_ownership_authorization_service as phase_ag_service
from app.modules.documents.recovery_durable_write_ownership_authorization_models import (
    EvidenceRecoveryDurableWriteOwnershipAuthorization,
)
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import EvidenceRecoveryRoutableDualWriteCanaryRoute
from app.modules.documents.recovery_write_ownership_transition_health_service import RecoveryWriteOwnershipTransitionHealthUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant
from tests.test_evidence_recovery_write_ownership_transition_health import (
    _completed_ae,
    _qualify_af,
    _request_af,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Authorize one later durable recovery write-ownership execution from qualified Phase AF evidence."
APPROVE_REASON = "Approve one short-lived durable-write execution authorization after independent fresh verification."
REJECT_REASON = "Reject durable recovery write-ownership authorization after governance review."


def _qualified_af(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _completed_ae(monkeypatch, tmp_path, endpoint, slug=slug)
    requester_id, requester_headers = _independent_admin(data, slug=f"{slug}-af-requester")
    qualifier_id, qualifier_headers = _independent_admin(data, slug=f"{slug}-af-qualifier")
    requested = _request_af(data, headers=requester_headers)
    assert requested.status_code == 201, requested.text
    health_id = requested.json()["qualification"]["id"]
    qualified = _qualify_af(data, health_id, headers=qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_af_health_id"] = health_id
    data["phase_af_requester_id"] = requester_id
    data["phase_af_requester_headers"] = requester_headers
    data["phase_af_qualifier_id"] = qualifier_id
    data["phase_af_qualifier_headers"] = qualifier_headers
    return data


def _request_ag(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-durable-write-ownership-authorizations",
        headers=headers,
        json={"health_qualification_id": data["phase_af_health_id"], "reason": reason},
    )


def _approve_ag(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-durable-write-ownership-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_ag_authorizes_one_later_execution_without_route_or_storage_mutation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_af(monkeypatch, tmp_path, endpoint, slug="phase-ag-happy")
        requester_id, requester_headers = _independent_admin(data, slug="phase-ag-requester")
        approver_id, approver_headers = _independent_admin(data, slug="phase-ag-approver")
        assert approver_id not in {
            requester_id,
            data["phase_af_requester_id"],
            data["phase_af_qualifier_id"],
            data["phase_ae_activator_id"],
            data["admin_id"],
            data["phase_ad_approver_id"],
            data["phase_ac_qualifier_id"],
            data["phase_ab_activator_id"],
            data["phase_aa_approver_id"],
            data["phase_z_qualifier_id"],
            data["phase_y_executor_id"],
            data["phase_x_approver_id"],
        }

        denied = _request_ag(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            original_version = route.route_version
            assert route.write_mode == "local_only"
            assert route.active_canary_lease_id is None
            assert route.active_write_ownership_transition_lease_id is None

        requested = _request_ag(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        a = body["authorization"]
        authorization_id = a["id"]
        assert a["status"] == "pending_second_approval"
        assert a["health_state"] == "healthy"
        assert a["max_execution_windows"] == 1
        assert a["local_authoritative"] is True
        assert a["storage_write_performed"] is False
        assert a["write_route_lease_created"] is False
        assert a["write_route_reactivated"] is False
        assert a["durable_write_authority_created"] is False
        assert a["read_path_switched"] is False
        assert a["write_path_switched"] is False
        assert a["document_storage_key_mutated"] is False
        assert a["authoritative_storage_changed"] is False
        assert a["destructive_action_performed"] is False
        assert a["s3_put_performed"] is False
        assert a["s3_copy_performed"] is False
        assert a["s3_delete_performed"] is False
        assert a["local_overwrite_performed"] is False
        assert a["local_move_performed"] is False
        assert a["local_delete_performed"] is False
        assert a["observed_local_hash"] == a["source_file_hash"]
        assert a["observed_recovery_hash"] == a["source_file_hash"]

        replay = _request_ag(data, headers=requester_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        forbidden = _approve_ag(data, authorization_id, headers=data["phase_af_qualifier_headers"])
        assert forbidden.status_code == 409

        approved = _approve_ag(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["outcome"] == "approved"
        assert approved_body["authorization"]["status"] == "approved"
        assert approved_body["authorization"]["approved_by_id"] == str(approver_id)
        assert approved_body["authorization"]["authorization_expires_at"] is not None
        assert approved_body["authorization"]["durable_write_authority_created"] is False

        fetched = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-authorizations/{authorization_id}",
            headers=data["manager_headers"],
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["status"] == "approved"

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert route.write_mode == "local_only"
            assert route.active_canary_lease_id is None
            assert route.active_write_ownership_transition_lease_id is None
            assert route.route_version == original_version
            assert route.durable_write_authority_created is False

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-ag-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-authorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_ag_recovery_storage_outage_is_retryable_without_consuming_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_af(monkeypatch, tmp_path, endpoint, slug="phase-ag-outage")
        _, requester_headers = _independent_admin(data, slug="phase-ag-outage-requester")
        original_loader = phase_ag_service._load_af_snapshot

        def unavailable(*args, **kwargs):
            raise RecoveryWriteOwnershipTransitionHealthUnavailable("simulated Phase AG recovery-storage outage")

        monkeypatch.setattr(phase_ag_service, "_load_af_snapshot", unavailable)
        outage = _request_ag(data, headers=requester_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            a = db.query(EvidenceRecoveryDurableWriteOwnershipAuthorization).filter_by(
                phase_af_health_qualification_id=UUID(data["phase_af_health_id"])
            ).one_or_none()
            assert a is None

        monkeypatch.setattr(phase_ag_service, "_load_af_snapshot", original_loader)
        retried = _request_ag(data, headers=requester_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "pending_second_approval"


def test_phase_ag_fresh_route_drift_invalidates_pending_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_af(monkeypatch, tmp_path, endpoint, slug="phase-ag-drift")
        _, requester_headers = _independent_admin(data, slug="phase-ag-drift-requester")
        _, approver_headers = _independent_admin(data, slug="phase-ag-drift-approver")
        requested = _request_ag(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            route.route_version += 1
            db.commit()

        approved = _approve_ag(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "invalidated"
        assert approved.json()["authorization"]["status"] == "invalidated"


def test_phase_ag_review_expiry_is_terminal_and_replay_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_af(monkeypatch, tmp_path, endpoint, slug="phase-ag-expiry")
        requester_id, requester_headers = _independent_admin(data, slug="phase-ag-expiry-requester")
        approver_id, _ = _independent_admin(data, slug="phase-ag-expiry-approver")
        requested = _request_ag(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = UUID(requested.json()["authorization"]["id"])

        with TestingSessionLocal() as db:
            a = db.get(EvidenceRecoveryDurableWriteOwnershipAuthorization, authorization_id)
            assert a is not None
            a, receipt, outcome = phase_ag_service.approve_durable_write_ownership_authorization(
                db,
                organization_id=a.organization_id,
                claim_id=a.claim_id,
                document_id=a.document_id,
                authorization_id=a.id,
                approved_by_id=approver_id,
                reason=APPROVE_REASON,
                now=a.review_expires_at + timedelta(seconds=1),
            )
            assert outcome == "expired"
            assert receipt is not None and receipt.phase == "expired"
            db.commit()

        replay = _request_ag(data, headers=requester_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["status"] == "expired"
        assert requester_id != approver_id


def test_phase_ag_requires_qualified_af(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ae(monkeypatch, tmp_path, endpoint, slug="phase-ag-unqualified")
        _, af_requester_headers = _independent_admin(data, slug="phase-ag-unqualified-af-requester")
        requested_af = _request_af(data, headers=af_requester_headers)
        assert requested_af.status_code == 201, requested_af.text
        data["phase_af_health_id"] = requested_af.json()["qualification"]["id"]
        _, ag_requester_headers = _independent_admin(data, slug="phase-ag-unqualified-requester")

        blocked = _request_ag(data, headers=ag_requester_headers)
        assert blocked.status_code == 409
