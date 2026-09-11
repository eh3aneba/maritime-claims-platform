from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_dual_write_rehearsal_health_service as phase_z_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_dual_write_rehearsal_execution_models import EvidenceRecoveryDualWriteRehearsalExecution
from app.modules.documents.recovery_dual_write_rehearsal_health_models import EvidenceRecoveryDualWriteRehearsalHealthQualification
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_dual_write_rehearsal_execution import _approved_x, _execute_y
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Request independent Phase Z health qualification of the completed rehearsal."
QUALIFY_REASON = "Independently qualify the verified Phase Y rehearsal as healthy."


def _executed_y(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_x(monkeypatch, tmp_path, endpoint, slug=slug)
    executed = _execute_y(data)
    assert executed.status_code == 201, executed.text
    assert executed.json()["outcome"] == "executed"
    data["phase_y_execution_id"] = executed.json()["execution"]["id"]
    data["phase_y_executor_id"] = data["admin_id"]
    return data


def _request_z(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-health-qualification",
        headers=headers or data["admin_headers"],
        json={"execution_id": data["phase_y_execution_id"], "reason": reason},
    )


def _qualify_z(data, health_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-health-qualifications/{health_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_z_independently_qualifies_one_phase_y_rehearsal_and_remains_non_routable(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _executed_y(monkeypatch, tmp_path, endpoint, slug="phase-z-happy")
        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None
            original_storage_key = document.storage_key
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            original_route_version = route.route_version

        requested = _request_z(data)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        q = body["qualification"]
        health_id = q["id"]
        assert q["status"] == "pending_second_approval"
        assert q["health_state"] == "healthy"
        assert q["execution_id"] == data["phase_y_execution_id"]
        assert q["storage_write_performed"] is False
        assert q["routable_dual_write_authority_created"] is False
        assert q["rehearsal_object_routable"] is False
        assert q["dual_write_active"] is False
        assert q["durable_write_authority_created"] is False
        assert q["read_path_switched"] is False
        assert q["write_path_switched"] is False
        assert q["document_storage_key_mutated"] is False
        assert q["authoritative_storage_changed"] is False
        assert q["destructive_action_performed"] is False
        assert q["s3_copy_performed"] is False
        assert q["s3_delete_performed"] is False
        assert q["local_delete_performed"] is False
        assert len(q["integrity_proof_hash"]) == 64
        assert len(q["request_snapshot_hash"]) == 64
        assert len(q["health_qualification_hash"]) == 64

        replay = _request_z(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == health_id

        same_actor = _qualify_z(data, health_id, headers=data["admin_headers"])
        assert same_actor.status_code == 409

        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-z-qualifier")
        assert qualifier_id not in {data["phase_y_executor_id"], data["phase_x_approver_id"]}
        qualified = _qualify_z(data, health_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["status"] == "qualified"
        assert qualified.json()["qualification"]["qualified_by_id"] == str(qualifier_id)

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-health-qualifications/{health_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]
        assert all(item["storage_write_performed"] is False for item in receipts.json())
        assert all(item["routable_dual_write_authority_created"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDualWriteRehearsalHealthQualification, UUID(health_id))
            execution = db.get(EvidenceRecoveryDualWriteRehearsalExecution, UUID(data["phase_y_execution_id"]))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "qualified"
            assert execution is not None and execution.status == "executed"
            assert execution.rehearsal_object_routable is False
            assert document is not None and document.storage_key == original_storage_key
            assert route.route_version == original_route_version
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            assert route.write_path_switched is False
            assert route.authoritative_storage_changed is False

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-z-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-health-qualifications/{health_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_z_storage_outage_during_second_approval_is_retryable(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _executed_y(monkeypatch, tmp_path, endpoint, slug="phase-z-outage")
        requested = _request_z(data)
        assert requested.status_code == 201, requested.text
        health_id = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-z-outage-qualifier")
        original_builder = phase_z_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase Z recovery-storage outage")

        monkeypatch.setattr(phase_z_service, "_build_store", unavailable)
        outage = _qualify_z(data, health_id, headers=qualifier_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            q = db.get(EvidenceRecoveryDualWriteRehearsalHealthQualification, UUID(health_id))
            assert q is not None and q.status == "pending_second_approval"

        monkeypatch.setattr(phase_z_service, "_build_store", original_builder)
        retried = _qualify_z(data, health_id, headers=qualifier_headers)
        assert retried.status_code == 200, retried.text
        assert retried.json()["outcome"] == "qualified"


def test_phase_z_route_drift_invalidates_pending_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _executed_y(monkeypatch, tmp_path, endpoint, slug="phase-z-drift")
        requested = _request_z(data)
        assert requested.status_code == 201, requested.text
        health_id = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-z-drift-qualifier")

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            route.route_version += 1
            db.commit()

        invalidated = _qualify_z(data, health_id, headers=qualifier_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["qualification"]["status"] == "invalidated"
