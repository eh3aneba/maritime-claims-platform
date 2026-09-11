from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_dual_write_rehearsal_health_service as phase_z_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_routable_dual_write_canary_authorization_models import EvidenceRecoveryRoutableDualWriteCanaryAuthorization
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_dual_write_rehearsal_health_qualification import _executed_y, _qualify_z, _request_z
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Request one bounded Phase AA authorization for a future routable dual-write canary."
APPROVE_REASON = "Independently approve one bounded future routable dual-write canary window."


def _qualified_z(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _executed_y(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_z(data)
    assert requested.status_code == 201, requested.text
    health_id = requested.json()["qualification"]["id"]
    qualifier_id, qualifier_headers = _independent_admin(data, slug=f"{slug}-z-qualifier")
    qualified = _qualify_z(data, health_id, headers=qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_z_health_id"] = health_id
    data["phase_z_qualifier_id"] = qualifier_id
    return data


def _request_aa(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-authorization",
        headers=headers or data["admin_headers"],
        json={"health_qualification_id": data["phase_z_health_id"], "reason": reason},
    )


def _approve_aa(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_aa_authorizes_one_future_canary_without_creating_live_write_authority(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_z(monkeypatch, tmp_path, endpoint, slug="phase-aa-happy")
        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None
            original_storage_key = document.storage_key
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            original_route_version = route.route_version

        requested = _request_aa(data)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        a = body["authorization"]
        authorization_id = a["id"]
        assert a["status"] == "pending_second_approval"
        assert a["health_state"] == "healthy"
        assert a["max_canary_windows"] == 1
        assert a["authorization_expires_at"] is None
        assert a["storage_write_performed"] is False
        assert a["canary_executed"] is False
        assert a["routable_dual_write_active"] is False
        assert a["durable_write_authority_created"] is False
        assert a["rehearsal_object_routable"] is False
        assert a["read_path_switched"] is False
        assert a["write_path_switched"] is False
        assert a["document_storage_key_mutated"] is False
        assert a["authoritative_storage_changed"] is False
        assert a["destructive_action_performed"] is False
        assert a["s3_copy_performed"] is False
        assert a["s3_delete_performed"] is False
        assert a["local_delete_performed"] is False
        assert len(a["request_snapshot_hash"]) == 64
        assert len(a["authorization_hash"]) == 64

        replay = _request_aa(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        same_actor = _approve_aa(data, authorization_id, headers=data["admin_headers"])
        assert same_actor.status_code == 409

        approver_id, approver_headers = _independent_admin(data, slug="phase-aa-approver")
        assert approver_id not in {
            data["admin_id"],
            data["phase_z_qualifier_id"],
            data["phase_y_executor_id"],
            data["phase_x_approver_id"],
        }
        approved = _approve_aa(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        approved_auth = approved.json()["authorization"]
        assert approved_auth["status"] == "approved"
        assert approved_auth["approved_by_id"] == str(approver_id)
        assert approved_auth["authorization_expires_at"] is not None
        assert approved_auth["routable_dual_write_active"] is False
        assert approved_auth["canary_executed"] is False

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        assert all(item["storage_write_performed"] is False for item in receipts.json())
        assert all(item["routable_dual_write_active"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryRoutableDualWriteCanaryAuthorization, UUID(authorization_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "approved"
            assert stored.max_canary_windows == 1
            assert document is not None and document.storage_key == original_storage_key
            assert route.route_version == original_route_version
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            assert route.write_path_switched is False
            assert route.authoritative_storage_changed is False

        manager_mutation = _request_aa(data, headers=data["manager_headers"])
        assert manager_mutation.status_code in {401, 403}

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-aa-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-dual-write-canary-authorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_aa_storage_outage_during_approval_is_retryable(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_z(monkeypatch, tmp_path, endpoint, slug="phase-aa-outage")
        requested = _request_aa(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        _, approver_headers = _independent_admin(data, slug="phase-aa-outage-approver")
        original_builder = phase_z_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase AA fresh-verification storage outage")

        monkeypatch.setattr(phase_z_service, "_build_store", unavailable)
        outage = _approve_aa(data, authorization_id, headers=approver_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            a = db.get(EvidenceRecoveryRoutableDualWriteCanaryAuthorization, UUID(authorization_id))
            assert a is not None and a.status == "pending_second_approval"
            assert a.authorization_expires_at is None

        monkeypatch.setattr(phase_z_service, "_build_store", original_builder)
        retried = _approve_aa(data, authorization_id, headers=approver_headers)
        assert retried.status_code == 200, retried.text
        assert retried.json()["outcome"] == "approved"


def test_phase_aa_route_drift_invalidates_pending_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_z(monkeypatch, tmp_path, endpoint, slug="phase-aa-drift")
        requested = _request_aa(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        _, approver_headers = _independent_admin(data, slug="phase-aa-drift-approver")

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            route.route_version += 1
            db.commit()

        invalidated = _approve_aa(data, authorization_id, headers=approver_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["authorization"]["status"] == "invalidated"
