from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_durable_write_ownership_execution_service as phase_ah_service
from app.modules.documents.recovery_durable_write_ownership_authorization_service import (
    RecoveryDurableWriteOwnershipAuthorizationUnavailable,
)
from app.modules.documents.recovery_durable_write_ownership_execution_models import (
    EvidenceRecoveryDurableWriteOwnershipLease,
    EvidenceRecoveryDurableWriteOwnershipRoute,
)
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import (
    EvidenceRecoveryRoutableDualWriteCanaryRoute,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_durable_write_ownership_authorization import (
    _approve_ag,
    _qualified_af,
    _request_ag,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


ACTIVATION_REASON = "Activate one reversible durable recovery write-ownership lease from approved Phase AG authority."
ROLLBACK_REASON = "Rollback durable recovery write ownership to exact local-only routing after controlled verification."
RECONCILE_REASON = "Reconcile the durable recovery write-ownership route against its exact active lease."


def _approved_ag(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_af(monkeypatch, tmp_path, endpoint, slug=slug)
    requester_id, requester_headers = _independent_admin(data, slug=f"{slug}-ag-requester")
    approver_id, approver_headers = _independent_admin(data, slug=f"{slug}-ag-approver")
    requested = _request_ag(data, headers=requester_headers)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approved = _approve_ag(data, authorization_id, headers=approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_ag_authorization_id"] = authorization_id
    data["phase_ag_requester_id"] = requester_id
    data["phase_ag_requester_headers"] = requester_headers
    data["phase_ag_approver_id"] = approver_id
    data["phase_ag_approver_headers"] = approver_headers
    return data


def _activate_ah(data, *, headers, reason: str = ACTIVATION_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-durable-write-ownership-leases",
        headers=headers,
        json={"authorization_id": data["phase_ag_authorization_id"], "reason": reason},
    )


def _rollback_ah(data, lease_id: str, *, headers, reason: str = ROLLBACK_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-durable-write-ownership-leases/{lease_id}/rollback",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_ah_activates_independent_durable_route_and_rolls_back(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ag(monkeypatch, tmp_path, endpoint, slug="phase-ah-happy")
        activator_id, activator_headers = _independent_admin(data, slug="phase-ah-activator")
        rollback_id, rollback_headers = _independent_admin(data, slug="phase-ah-rollback")
        assert activator_id not in {
            data["phase_ag_requester_id"],
            data["phase_ag_approver_id"],
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

        denied = _activate_ah(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            experiment_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            experiment_version = experiment_route.route_version
            assert experiment_route.write_mode == "local_only"
            assert experiment_route.active_canary_lease_id is None
            assert experiment_route.active_write_ownership_transition_lease_id is None
            assert db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one_or_none() is None

        activated = _activate_ah(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        body = activated.json()
        assert body["outcome"] == "activated"
        lease = body["lease"]
        route = body["route"]
        lease_id = lease["id"]
        assert lease["status"] == "active"
        assert lease["durable_write_ownership_active"] is True
        assert lease["durable_write_authority_created"] is True
        assert lease["write_path_switched"] is True
        assert lease["local_authoritative"] is True
        assert lease["storage_write_performed"] is False
        assert lease["read_path_switched"] is False
        assert lease["document_storage_key_mutated"] is False
        assert lease["authoritative_storage_changed"] is False
        assert lease["destructive_action_performed"] is False
        assert lease["s3_put_performed"] is False
        assert lease["s3_copy_performed"] is False
        assert lease["s3_delete_performed"] is False
        assert lease["local_overwrite_performed"] is False
        assert lease["local_move_performed"] is False
        assert lease["local_delete_performed"] is False
        assert route["write_mode"] == "recovery_primary"
        assert route["active_durable_write_ownership_lease_id"] == lease_id
        assert route["durable_write_authority_created"] is True
        assert route["write_path_switched"] is True
        assert route["local_authoritative"] is True
        assert route["route_version"] == 1

        replay = _activate_ah(data, headers=activator_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id

        changed = _activate_ah(data, headers=activator_headers, reason=ACTIVATION_REASON + " Changed.")
        assert changed.status_code == 409

        with TestingSessionLocal() as db:
            experiment_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert experiment_route.write_mode == "local_only"
            assert experiment_route.route_version == experiment_version
            assert experiment_route.active_canary_lease_id is None
            assert experiment_route.active_write_ownership_transition_lease_id is None

        fetched = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-leases/{lease_id}",
            headers=data["manager_headers"],
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["status"] == "active"

        fetched_route = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            "recovery-durable-write-ownership-route",
            headers=data["manager_headers"],
        )
        assert fetched_route.status_code == 200, fetched_route.text
        assert fetched_route.json()["write_mode"] == "recovery_primary"

        reconciled = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-leases/{lease_id}/reconcile",
            headers=rollback_headers,
            json={"reason": RECONCILE_REASON},
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["outcome"] == "unchanged"

        rolled_back = _rollback_ah(data, lease_id, headers=rollback_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        rb = rolled_back.json()
        assert rb["outcome"] == "rolled_back"
        assert rb["lease"]["status"] == "rolled_back"
        assert rb["lease"]["durable_write_ownership_active"] is False
        assert rb["lease"]["durable_write_authority_created"] is False
        assert rb["lease"]["write_path_switched"] is False
        assert rb["route"]["write_mode"] == "local_only"
        assert rb["route"]["active_durable_write_ownership_lease_id"] is None
        assert rb["route"]["durable_write_authority_created"] is False
        assert rb["route"]["write_path_switched"] is False
        assert rb["route"]["route_version"] == 2

        rollback_replay = _rollback_ah(data, lease_id, headers=rollback_headers)
        assert rollback_replay.status_code == 200, rollback_replay.text
        assert rollback_replay.json()["outcome"] == "unchanged"

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["activated", "rolled_back"]

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(
            slug="phase-ah-other", storage_root=tmp_path / "other"
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-leases/{lease_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404
        assert rollback_id != activator_id


def test_phase_ah_rejects_governance_actor_and_changed_replay(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ag(monkeypatch, tmp_path, endpoint, slug="phase-ah-actors")
        forbidden = _activate_ah(data, headers=data["phase_ag_approver_headers"])
        assert forbidden.status_code == 409

        activator_id, activator_headers = _independent_admin(data, slug="phase-ah-actors-activator")
        activated = _activate_ah(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        assert activated.json()["outcome"] == "activated"

        other_id, other_headers = _independent_admin(data, slug="phase-ah-actors-other")
        conflict = _activate_ah(data, headers=other_headers)
        assert conflict.status_code == 409
        assert other_id != activator_id


def test_phase_ah_recovery_storage_outage_is_retryable_without_consuming_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ag(monkeypatch, tmp_path, endpoint, slug="phase-ah-outage")
        _, activator_headers = _independent_admin(data, slug="phase-ah-outage-activator")
        original = phase_ah_service._fresh_af

        def unavailable(*args, **kwargs):
            raise RecoveryDurableWriteOwnershipAuthorizationUnavailable(
                "simulated Phase AH recovery-storage outage"
            )

        monkeypatch.setattr(phase_ah_service, "_fresh_af", unavailable)
        outage = _activate_ah(data, headers=activator_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryDurableWriteOwnershipLease).filter_by(
                authorization_id=UUID(data["phase_ag_authorization_id"])
            ).one_or_none() is None
            assert db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one_or_none() is None

        monkeypatch.setattr(phase_ah_service, "_fresh_af", original)
        retried = _activate_ah(data, headers=activator_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "activated"


def test_phase_ah_experimental_route_drift_blocks_activation_without_consumption(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ag(monkeypatch, tmp_path, endpoint, slug="phase-ah-drift")
        _, activator_headers = _independent_admin(data, slug="phase-ah-drift-activator")
        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        blocked = _activate_ah(data, headers=activator_headers)
        assert blocked.status_code == 409, blocked.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryDurableWriteOwnershipLease).filter_by(
                authorization_id=UUID(data["phase_ag_authorization_id"])
            ).one_or_none() is None
            assert db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one_or_none() is None


def test_phase_ah_expired_ag_authorization_cannot_be_consumed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ag(monkeypatch, tmp_path, endpoint, slug="phase-ah-expired")
        _, activator_headers = _independent_admin(data, slug="phase-ah-expired-activator")
        with TestingSessionLocal() as db:
            from app.modules.documents.recovery_durable_write_ownership_authorization_models import (
                EvidenceRecoveryDurableWriteOwnershipAuthorization,
            )

            authorization = db.get(
                EvidenceRecoveryDurableWriteOwnershipAuthorization,
                UUID(data["phase_ag_authorization_id"]),
            )
            assert authorization is not None
            expired_at = authorization.authorization_expires_at
            assert expired_at is not None

        monkeypatch.setattr(
            phase_ah_service,
            "_utc_now",
            lambda: expired_at + __import__("datetime").timedelta(seconds=1),
        )
        blocked = _activate_ah(data, headers=activator_headers)
        assert blocked.status_code == 409, blocked.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryDurableWriteOwnershipLease).filter_by(
                authorization_id=UUID(data["phase_ag_authorization_id"])
            ).one_or_none() is None
