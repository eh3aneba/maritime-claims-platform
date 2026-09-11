from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_routable_dual_write_canary_health_service as phase_ac_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import (
    EvidenceRecoveryRoutableDualWriteCanaryRoute,
)
from app.modules.documents.recovery_routable_dual_write_canary_health_models import (
    EvidenceRecoveryRoutableDualWriteCanaryHealthQualification,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant
from tests.test_evidence_recovery_routable_dual_write_canary_execution import (
    _approved_aa,
    _execute_ab,
    _rollback_ab,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Independently qualify the completed Phase AB canary after exact local-only rollback."
QUALIFY_REASON = "Independent Phase AC review confirms healthy lineage, routes and byte integrity."


def _completed_ab(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_aa(monkeypatch, tmp_path, endpoint, slug=slug)
    activator_id, activator_headers = _independent_admin(data, slug=f"{slug}-ab-activator")
    activated = _execute_ab(data, headers=activator_headers)
    assert activated.status_code == 201, activated.text
    lease_id = activated.json()["lease"]["id"]
    data["phase_ab_lease_id"] = lease_id
    data["phase_ab_activator_id"] = activator_id
    data["phase_ab_activator_headers"] = activator_headers
    return data


def _rollback_completed_ab(data):
    rolled_back = _rollback_ab(
        data,
        data["phase_ab_lease_id"],
        headers=data["phase_ab_activator_headers"],
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"
    return rolled_back


def _request_ac(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-health-qualification",
        headers=headers or data["admin_headers"],
        json={"canary_lease_id": data["phase_ab_lease_id"], "reason": reason},
    )


def _qualify_ac(data, health_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-health-qualifications/{health_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_ac_requires_terminal_ab_then_independently_qualifies_healthy_window(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ab(monkeypatch, tmp_path, endpoint, slug="phase-ac-happy")

        active_request = _request_ac(data)
        assert active_request.status_code == 409

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None
            original_storage_key = document.storage_key
            original_read_route_version = read_route.route_version

        _rollback_completed_ab(data)
        requested = _request_ac(data)
        assert requested.status_code == 201, requested.text
        request_body = requested.json()
        assert request_body["outcome"] == "pending_second_approval"
        q = request_body["qualification"]
        health_id = q["id"]
        assert q["health_state"] == "healthy"
        assert q["status"] == "pending_second_approval"
        assert q["local_authoritative"] is True
        assert q["storage_write_performed"] is False
        assert q["canary_reactivated"] is False
        assert q["routable_dual_write_active"] is False
        assert q["durable_write_authority_created"] is False
        assert q["read_path_switched"] is False
        assert q["write_path_switched"] is False
        assert q["document_storage_key_mutated"] is False
        assert q["authoritative_storage_changed"] is False
        assert q["destructive_action_performed"] is False
        assert q["s3_put_performed"] is False
        assert q["s3_copy_performed"] is False
        assert q["s3_delete_performed"] is False
        assert q["local_delete_performed"] is False
        assert len(q["activation_receipt_hash"]) == 64
        assert len(q["terminal_receipt_hash"]) == 64
        assert len(q["integrity_proof_hash"]) == 64
        assert q["write_route_version_at_request"] >= 2

        replay = _request_ac(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == health_id

        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-ac-qualifier")
        assert qualifier_id not in {
            data["admin_id"],
            data["phase_ab_activator_id"],
            data["phase_aa_approver_id"],
            data["phase_z_qualifier_id"],
            data["phase_y_executor_id"],
            data["phase_x_approver_id"],
        }
        activated_actor_attempt = _qualify_ac(data, health_id, headers=data["phase_ab_activator_headers"])
        assert activated_actor_attempt.status_code == 409

        qualified = _qualify_ac(data, health_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["status"] == "qualified"
        assert qualified.json()["qualification"]["qualified_by_id"] == str(qualifier_id)

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-health-qualifications/{health_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]
        assert all(item["storage_write_performed"] is False for item in receipts.json())
        assert all(item["s3_put_performed"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryRoutableDualWriteCanaryHealthQualification, UUID(health_id))
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            document = db.get(Document, data["document_id"])
            assert stored is not None and stored.status == "qualified"
            assert write_route.write_mode == "local_only"
            assert write_route.active_canary_lease_id is None
            assert write_route.local_authoritative is True
            assert read_route.route_version == original_read_route_version
            assert read_route.route_class == "local_source"
            assert read_route.route_authority_kind == "local"
            assert read_route.active_replica_id is None
            assert document is not None and document.storage_key == original_storage_key

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-ac-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-health-qualifications/{health_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_ac_storage_outage_during_second_review_is_retryable(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ab(monkeypatch, tmp_path, endpoint, slug="phase-ac-outage")
        _rollback_completed_ab(data)
        requested = _request_ac(data)
        assert requested.status_code == 201, requested.text
        health_id = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-ac-outage-qualifier")
        original_builder = phase_ac_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase AC recovery-storage outage")

        monkeypatch.setattr(phase_ac_service, "_build_store", unavailable)
        outage = _qualify_ac(data, health_id, headers=qualifier_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            q = db.get(EvidenceRecoveryRoutableDualWriteCanaryHealthQualification, UUID(health_id))
            assert q is not None and q.status == "pending_second_approval"

        monkeypatch.setattr(phase_ac_service, "_build_store", original_builder)
        retried = _qualify_ac(data, health_id, headers=qualifier_headers)
        assert retried.status_code == 200, retried.text
        assert retried.json()["outcome"] == "qualified"


def test_phase_ac_terminal_write_route_drift_invalidates_pending_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ab(monkeypatch, tmp_path, endpoint, slug="phase-ac-drift")
        _rollback_completed_ab(data)
        requested = _request_ac(data)
        assert requested.status_code == 201, requested.text
        health_id = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-ac-drift-qualifier")

        with TestingSessionLocal() as db:
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            write_route.route_version += 1
            db.commit()

        response = _qualify_ac(data, health_id, headers=qualifier_headers)
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == "invalidated"
        assert response.json()["qualification"]["status"] == "invalidated"
        with TestingSessionLocal() as db:
            q = db.get(EvidenceRecoveryRoutableDualWriteCanaryHealthQualification, UUID(health_id))
            assert q is not None and q.status == "invalidated"
