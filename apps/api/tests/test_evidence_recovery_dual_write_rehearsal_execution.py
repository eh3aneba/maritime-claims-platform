from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_dual_write_rehearsal_execution_service as phase_y_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_dual_write_rehearsal_authorization_models import EvidenceRecoveryDualWriteRehearsalAuthorization
from app.modules.documents.recovery_dual_write_rehearsal_execution_models import EvidenceRecoveryDualWriteRehearsalExecution
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_dual_write_rehearsal_authorization import _approve_x, _qualified_w, _request_x
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


EXECUTE_REASON = "Execute one bounded non-routable Phase Y recovery write rehearsal."


def _approved_x(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_w(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_x(data)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approver_id, approver_headers = _independent_admin(data, slug=f"{slug}-x-approver")
    approved = _approve_x(data, authorization_id, headers=approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_x_authorization_id"] = authorization_id
    data["phase_x_approver_id"] = approver_id
    return data


def _execute_y(data, *, headers=None, reason: str = EXECUTE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-authorizations/{data['phase_x_authorization_id']}/execute",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def test_phase_y_executes_one_isolated_verified_rehearsal_and_keeps_local_authority(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_x(monkeypatch, tmp_path, endpoint, slug="phase-y-happy")
        with TestingSessionLocal() as db:
            before = db.get(Document, UUID(data["document_id"]))
            assert before is not None
            original_storage_key = before.storage_key

        executed = _execute_y(data)
        assert executed.status_code == 201, executed.text
        body = executed.json()
        assert body["outcome"] == "executed"
        execution = body["execution"]
        execution_id = execution["id"]
        assert execution["status"] == "executed"
        assert execution["max_rehearsal_writes"] == 1
        assert execution["rehearsal_executed"] is True
        assert execution["rehearsal_write_verified"] is True
        assert execution["rehearsal_object_routable"] is False
        assert execution["dual_write_active"] is False
        assert execution["durable_write_authority_created"] is False
        assert execution["read_path_switched"] is False
        assert execution["write_path_switched"] is False
        assert execution["document_storage_key_mutated"] is False
        assert execution["authoritative_storage_changed"] is False
        assert execution["destructive_action_performed"] is False
        assert execution["s3_copy_performed"] is False
        assert execution["s3_delete_performed"] is False
        assert execution["local_delete_performed"] is False
        assert execution["rehearsal_object_key_fingerprint"] != execution["candidate_storage_key_fingerprint"]
        assert len(execution["rehearsal_object_key_fingerprint"]) == 64

        replay = _execute_y(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["execution"]["id"] == execution_id

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-executions/{execution_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert len(receipts.json()) == 1
        assert receipts.json()[0]["phase"] == "executed"
        assert receipts.json()[0]["rehearsal_object_routable"] is False

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDualWriteRehearsalExecution, UUID(execution_id))
            phase_x = db.get(EvidenceRecoveryDualWriteRehearsalAuthorization, UUID(data["phase_x_authorization_id"]))
            document = db.get(Document, UUID(data["document_id"]))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "executed"
            assert phase_x is not None and phase_x.rehearsal_executed is False
            assert phase_x.dual_write_active is False
            assert document is not None and document.storage_key == original_storage_key
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            assert route.write_path_switched is False
            assert route.authoritative_storage_changed is False

        manager_mutation = _execute_y(data, headers=data["manager_headers"])
        assert manager_mutation.status_code in {401, 403}

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-y-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-dual-write-rehearsal-executions/{execution_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_y_storage_outage_is_retryable_without_consuming_execution(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_x(monkeypatch, tmp_path, endpoint, slug="phase-y-outage")
        original_builder = phase_y_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase Y recovery-storage outage")

        monkeypatch.setattr(phase_y_service, "_build_store", unavailable)
        outage = _execute_y(data)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            count = db.query(EvidenceRecoveryDualWriteRehearsalExecution).filter_by(
                phase_x_authorization_id=UUID(data["phase_x_authorization_id"])
            ).count()
            assert count == 0
            phase_x = db.get(EvidenceRecoveryDualWriteRehearsalAuthorization, UUID(data["phase_x_authorization_id"]))
            assert phase_x is not None and phase_x.status == "approved"
            assert phase_x.rehearsal_executed is False

        monkeypatch.setattr(phase_y_service, "_build_store", original_builder)
        retried = _execute_y(data)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "executed"


def test_phase_y_rejects_unapproved_phase_x(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_w(monkeypatch, tmp_path, endpoint, slug="phase-y-unapproved")
        requested = _request_x(data)
        assert requested.status_code == 201, requested.text
        data["phase_x_authorization_id"] = requested.json()["authorization"]["id"]
        response = _execute_y(data)
        assert response.status_code == 409
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryDualWriteRehearsalExecution).count() == 0
