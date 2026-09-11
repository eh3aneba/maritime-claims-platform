from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_routable_dual_write_canary_execution_service as phase_ab_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import (
    EvidenceRecoveryRoutableDualWriteCanaryLease,
    EvidenceRecoveryRoutableDualWriteCanaryRoute,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant
from tests.test_evidence_recovery_routable_dual_write_canary_authorization import (
    _approve_aa,
    _qualified_z,
    _request_aa,
)


def setup_function() -> None:
    reset_database()


EXECUTE_REASON = "Execute one bounded Phase AB secondary recovery canary while local remains authoritative."
ROLLBACK_REASON = "Restore the bounded Phase AB write route to exact local-only authority."


def _approved_aa(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_z(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_aa(data)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approver_id, approver_headers = _independent_admin(data, slug=f"{slug}-aa-approver")
    approved = _approve_aa(data, authorization_id, headers=approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_aa_authorization_id"] = authorization_id
    data["phase_aa_approver_id"] = approver_id
    return data


def _execute_ab(data, *, headers=None, reason: str = EXECUTE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-authorizations/{data['phase_aa_authorization_id']}/execute",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _rollback_ab(data, lease_id: str, *, headers=None, reason: str = ROLLBACK_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-leases/{lease_id}/rollback",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def test_phase_ab_executes_one_verified_secondary_canary_and_rolls_back_cleanly(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aa(monkeypatch, tmp_path, endpoint, slug="phase-ab-happy")
        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None
            original_storage_key = document.storage_key
            original_read_route_version = read_route.route_version

        activator_id, activator_headers = _independent_admin(data, slug="phase-ab-activator")
        assert activator_id not in {
            data["admin_id"],
            data["phase_aa_approver_id"],
            data["phase_z_qualifier_id"],
            data["phase_y_executor_id"],
            data["phase_x_approver_id"],
        }
        activated = _execute_ab(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        body = activated.json()
        assert body["outcome"] == "activated"
        lease = body["lease"]
        lease_id = lease["id"]
        assert lease["status"] == "active"
        assert lease["max_canary_writes"] == 1
        assert lease["canary_executed"] is True
        assert lease["canary_write_verified"] is True
        assert lease["routable_dual_write_active"] is True
        assert lease["local_authoritative"] is True
        assert lease["durable_write_authority_created"] is False
        assert lease["rehearsal_object_routable"] is False
        assert lease["read_path_switched"] is False
        assert lease["write_path_switched"] is False
        assert lease["document_storage_key_mutated"] is False
        assert lease["authoritative_storage_changed"] is False
        assert lease["destructive_action_performed"] is False
        assert lease["s3_copy_performed"] is False
        assert lease["s3_delete_performed"] is False
        assert lease["local_delete_performed"] is False
        assert len(lease["canary_object_key_fingerprint"]) == 64
        assert len(lease["verification_hash"]) == 64
        assert len(lease["lease_hash"]) == 64

        replay = _execute_ab(data, headers=activator_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["activated"]
        assert receipts.json()[0]["to_write_mode"] == "local_plus_recovery_canary"
        assert receipts.json()[0]["routable_dual_write_active"] is True

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryRoutableDualWriteCanaryLease, UUID(lease_id))
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "active"
            assert write_route.write_mode == "local_plus_recovery_canary"
            assert write_route.active_canary_lease_id == UUID(lease_id)
            assert write_route.local_authoritative is True
            assert write_route.write_path_switched is False
            assert document is not None and document.storage_key == original_storage_key
            assert read_route.route_version == original_read_route_version
            assert read_route.route_class == "local_source"
            assert read_route.route_authority_kind == "local"
            assert read_route.active_replica_id is None
            assert read_route.read_path_switched is False
            assert read_route.write_path_switched is False
            assert read_route.authoritative_storage_changed is False

        rolled_back = _rollback_ab(data, lease_id, headers=activator_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["lease"]["status"] == "rolled_back"
        assert rolled_back.json()["lease"]["routable_dual_write_active"] is False

        receipts_after = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts_after.status_code == 200, receipts_after.text
        assert [item["phase"] for item in receipts_after.json()] == ["activated", "rolled_back"]
        assert receipts_after.json()[-1]["to_write_mode"] == "local_only"
        assert receipts_after.json()[-1]["routable_dual_write_active"] is False

        with TestingSessionLocal() as db:
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert write_route.write_mode == "local_only"
            assert write_route.active_canary_lease_id is None
            assert write_route.local_authoritative is True
            assert document is not None and document.storage_key == original_storage_key
            assert read_route.route_version == original_read_route_version
            assert read_route.route_class == "local_source"
            assert read_route.route_authority_kind == "local"

        manager_mutation = _execute_ab(data, headers=data["manager_headers"])
        assert manager_mutation.status_code in {401, 403}

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-ab-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-leases/{lease_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_ab_storage_outage_is_retryable_without_consuming_canary(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aa(monkeypatch, tmp_path, endpoint, slug="phase-ab-outage")
        _, activator_headers = _independent_admin(data, slug="phase-ab-outage-activator")
        original_builder = phase_ab_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase AB recovery-storage outage")

        monkeypatch.setattr(phase_ab_service, "_build_store", unavailable)
        outage = _execute_ab(data, headers=activator_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryRoutableDualWriteCanaryLease).count() == 0
            assert db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).count() == 0

        monkeypatch.setattr(phase_ab_service, "_build_store", original_builder)
        retried = _execute_ab(data, headers=activator_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "activated"


def test_phase_ab_rejects_unapproved_phase_aa(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_z(monkeypatch, tmp_path, endpoint, slug="phase-ab-unapproved")
        requested = _request_aa(data)
        assert requested.status_code == 201, requested.text
        data["phase_aa_authorization_id"] = requested.json()["authorization"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-ab-unapproved-activator")
        response = _execute_ab(data, headers=activator_headers)
        assert response.status_code == 409
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryRoutableDualWriteCanaryLease).count() == 0


def test_phase_ab_read_route_drift_fails_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aa(monkeypatch, tmp_path, endpoint, slug="phase-ab-drift")
        _, activator_headers = _independent_admin(data, slug="phase-ab-drift-activator")
        with TestingSessionLocal() as db:
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            read_route.route_version += 1
            db.commit()
        response = _execute_ab(data, headers=activator_headers)
        assert response.status_code == 409
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryRoutableDualWriteCanaryLease).count() == 0
            assert db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).count() == 0
