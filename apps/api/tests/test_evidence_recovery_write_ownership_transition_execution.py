from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_write_ownership_transition_execution_service as phase_ae_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import EvidenceRecoveryRoutableDualWriteCanaryRoute
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_write_ownership_transition_execution_models import EvidenceRecoveryWriteOwnershipTransitionLease
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant
from tests.test_evidence_recovery_write_ownership_transition_authorization import _approve_ad, _qualified_ac, _request_ad


def setup_function() -> None:
    reset_database()


ACTIVATE_REASON = "Execute one bounded reversible recovery write-ownership transition from approved Phase AD evidence."
ROLLBACK_REASON = "Explicitly restore exact local-only write routing and preserve local evidence as the rollback source."
RECONCILE_REASON = "Reconcile the expired Phase AE write-routing lease back to exact local-only authority."


def _approved_ad(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_ac(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_ad(data)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approver_id, approver_headers = _independent_admin(data, slug=f"{slug}-ad-approver")
    approved = _approve_ad(data, authorization_id, headers=approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_ad_authorization_id"] = authorization_id
    data["phase_ad_approver_id"] = approver_id
    data["phase_ad_approver_headers"] = approver_headers
    return data


def _activate_ae(data, *, headers, reason: str = ACTIVATE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-write-ownership-transition-authorizations/{data['phase_ad_authorization_id']}/activate",
        headers=headers,
        json={"reason": reason},
    )


def _rollback_ae(data, lease_id: str, *, headers, reason: str = ROLLBACK_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-write-ownership-transition-leases/{lease_id}/rollback",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_ae_executes_one_bounded_transition_and_explicitly_rolls_back(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ad(monkeypatch, tmp_path, endpoint, slug="phase-ae-happy")
        activator_id, activator_headers = _independent_admin(data, slug="phase-ae-activator")
        assert activator_id not in {
            data["admin_id"], data["phase_ad_approver_id"], data["phase_ac_qualifier_id"],
            data["phase_ab_activator_id"], data["phase_aa_approver_id"], data["phase_z_qualifier_id"],
            data["phase_y_executor_id"], data["phase_x_approver_id"],
        }

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None
            original_storage_key = document.storage_key
            original_read_route_version = read_route.route_version
            original_write_route_version = write_route.route_version

        forbidden = _activate_ae(data, headers=data["phase_ad_approver_headers"])
        assert forbidden.status_code == 409

        activated = _activate_ae(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        body = activated.json()
        assert body["outcome"] == "activated"
        lease = body["lease"]
        lease_id = lease["id"]
        assert lease["status"] == "active"
        assert lease["bounded_write_ownership_transition_active"] is True
        assert lease["local_authoritative"] is True
        assert lease["storage_write_performed"] is False
        assert lease["durable_write_authority_created"] is False
        assert lease["read_path_switched"] is False
        assert lease["write_path_switched"] is True
        assert lease["document_storage_key_mutated"] is False
        assert lease["authoritative_storage_changed"] is False
        assert lease["destructive_action_performed"] is False
        assert lease["s3_put_performed"] is False
        assert lease["s3_copy_performed"] is False
        assert lease["s3_delete_performed"] is False
        assert lease["local_overwrite_performed"] is False
        assert lease["local_move_performed"] is False
        assert lease["local_delete_performed"] is False
        assert lease["observed_replica_hash"] == lease["source_file_hash"]
        assert lease["observed_replica_size_bytes"] == lease["source_file_size_bytes"]
        assert lease["write_route_version_before_activation"] == original_write_route_version
        assert lease["write_route_version_after_activation"] == original_write_route_version + 1

        replay = _activate_ae(data, headers=activator_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id

        other_activator_id, other_activator_headers = _independent_admin(data, slug="phase-ae-other-activator")
        assert other_activator_id != activator_id
        duplicate = _activate_ae(data, headers=other_activator_headers)
        assert duplicate.status_code == 409

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None and document.storage_key == original_storage_key
            assert read_route.route_class == "local_source"
            assert read_route.route_authority_kind == "local"
            assert read_route.route_version == original_read_route_version
            assert write_route.write_mode == "recovery_primary"
            assert write_route.active_canary_lease_id is None
            assert write_route.active_write_ownership_transition_lease_id == UUID(lease_id)
            assert write_route.route_version == original_write_route_version + 1
            assert write_route.local_authoritative is True
            assert write_route.write_path_switched is True

        rolled_back = _rollback_ae(data, lease_id, headers=activator_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["lease"]["status"] == "rolled_back"
        assert rolled_back.json()["lease"]["bounded_write_ownership_transition_active"] is False
        assert rolled_back.json()["lease"]["write_path_switched"] is False

        rollback_replay = _rollback_ae(data, lease_id, headers=activator_headers)
        assert rollback_replay.status_code == 200, rollback_replay.text
        assert rollback_replay.json()["outcome"] == "unchanged"

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-write-ownership-transition-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["activated", "rolled_back"]

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None and document.storage_key == original_storage_key
            assert read_route.route_version == original_read_route_version
            assert read_route.route_class == "local_source"
            assert write_route.write_mode == "local_only"
            assert write_route.active_canary_lease_id is None
            assert write_route.active_write_ownership_transition_lease_id is None
            assert write_route.route_version == original_write_route_version + 2
            assert write_route.write_path_switched is False

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-ae-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-write-ownership-transition-leases/{lease_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_ae_recovery_storage_outage_is_retryable_without_consuming_ad(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ad(monkeypatch, tmp_path, endpoint, slug="phase-ae-outage")
        _, activator_headers = _independent_admin(data, slug="phase-ae-outage-activator")
        original_builder = phase_ae_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase AE recovery-storage outage")

        monkeypatch.setattr(phase_ae_service, "_build_store", unavailable)
        outage = _activate_ae(data, headers=activator_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            lease = db.query(EvidenceRecoveryWriteOwnershipTransitionLease).filter_by(
                authorization_id=UUID(data["phase_ad_authorization_id"])
            ).one_or_none()
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert lease is None
            assert route.write_mode == "local_only"
            assert route.active_write_ownership_transition_lease_id is None

        monkeypatch.setattr(phase_ae_service, "_build_store", original_builder)
        retried = _activate_ae(data, headers=activator_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "activated"


def test_phase_ae_expiry_reconciles_to_exact_local_only_route(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ad(monkeypatch, tmp_path, endpoint, slug="phase-ae-expiry")
        _, activator_headers = _independent_admin(data, slug="phase-ae-expiry-activator")
        activated = _activate_ae(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        lease_id = UUID(activated.json()["lease"]["id"])

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryWriteOwnershipTransitionLease, lease_id)
            assert lease is not None
            lease, receipt, outcome = phase_ae_service.reconcile_recovery_write_ownership_transition(
                db,
                organization_id=lease.organization_id,
                claim_id=lease.claim_id,
                document_id=lease.document_id,
                lease_id=lease.id,
                actor_id=data["admin_id"],
                reason=RECONCILE_REASON,
                now=lease.route_expires_at + timedelta(seconds=1),
            )
            assert outcome == "expired"
            assert receipt is not None and receipt.phase == "expired"
            db.commit()

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryWriteOwnershipTransitionLease, lease_id)
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert lease is not None and lease.status == "expired"
            assert lease.bounded_write_ownership_transition_active is False
            assert route.write_mode == "local_only"
            assert route.active_write_ownership_transition_lease_id is None
            assert route.write_path_switched is False


def test_phase_ae_route_drift_fails_closed_and_mutations_require_admin_mfa(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ad(monkeypatch, tmp_path, endpoint, slug="phase-ae-drift")
        _, activator_headers = _independent_admin(data, slug="phase-ae-drift-activator")

        denied = _activate_ae(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        activated = _activate_ae(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        lease_id = activated.json()["lease"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            route.route_version += 1
            db.commit()

        rollback = _rollback_ae(data, lease_id, headers=activator_headers)
        assert rollback.status_code == 409
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryWriteOwnershipTransitionLease, UUID(lease_id))
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert lease is not None and lease.status == "active"
            assert route.write_mode == "recovery_primary"
            assert route.active_write_ownership_transition_lease_id == UUID(lease_id)
