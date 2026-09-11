from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_routable_dual_write_canary_health_service as phase_ac_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import EvidenceRecoveryRoutableDualWriteCanaryRoute
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_write_ownership_transition_authorization_models import (
    EvidenceRecoveryWriteOwnershipTransitionAuthorization,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant
from tests.test_evidence_recovery_routable_dual_write_canary_health import (
    _completed_ab,
    _qualify_ac,
    _request_ac,
    _rollback_completed_ab,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Authorize one later bounded recovery write-ownership transition from qualified Phase AC evidence."
APPROVE_REASON = "Independent Phase AD review approves only the bounded future transition authorization."


def _qualified_ac(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _completed_ab(monkeypatch, tmp_path, endpoint, slug=slug)
    _rollback_completed_ab(data)
    requested = _request_ac(data)
    assert requested.status_code == 201, requested.text
    health_id = requested.json()["qualification"]["id"]
    qualifier_id, qualifier_headers = _independent_admin(data, slug=f"{slug}-ac-qualifier")
    qualified = _qualify_ac(data, health_id, headers=qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_ac_health_id"] = health_id
    data["phase_ac_qualifier_id"] = qualifier_id
    data["phase_ac_qualifier_headers"] = qualifier_headers
    return data


def _request_ad(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-write-ownership-transition-authorization",
        headers=headers or data["admin_headers"],
        json={"health_qualification_id": data["phase_ac_health_id"], "reason": reason},
    )


def _approve_ad(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-write-ownership-transition-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_ad_authorizes_future_transition_without_mutating_storage_or_routes(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ac(monkeypatch, tmp_path, endpoint, slug="phase-ad-happy")

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None
            original_storage_key = document.storage_key
            original_read_route_version = read_route.route_version
            original_write_route_version = write_route.route_version

        requested = _request_ad(data)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        a = body["authorization"]
        authorization_id = a["id"]
        assert a["status"] == "pending_second_approval"
        assert a["health_state"] == "healthy"
        assert a["max_transition_windows"] == 1
        assert a["local_authoritative"] is True
        assert a["storage_write_performed"] is False
        assert a["write_route_lease_created"] is False
        assert a["routable_dual_write_active"] is False
        assert a["durable_write_authority_created"] is False
        assert a["read_path_switched"] is False
        assert a["write_path_switched"] is False
        assert a["document_storage_key_mutated"] is False
        assert a["authoritative_storage_changed"] is False
        assert a["destructive_action_performed"] is False
        assert a["s3_put_performed"] is False
        assert a["s3_copy_performed"] is False
        assert a["s3_delete_performed"] is False
        assert a["local_delete_performed"] is False

        replay = _request_ad(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        forbidden = _approve_ad(data, authorization_id, headers=data["phase_ac_qualifier_headers"])
        assert forbidden.status_code == 409

        approver_id, approver_headers = _independent_admin(data, slug="phase-ad-approver")
        assert approver_id not in {
            data["admin_id"],
            data["phase_ac_qualifier_id"],
            data["phase_ab_activator_id"],
            data["phase_aa_approver_id"],
            data["phase_z_qualifier_id"],
            data["phase_y_executor_id"],
            data["phase_x_approver_id"],
        }
        approved = _approve_ad(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        assert approved.json()["authorization"]["status"] == "approved"
        assert approved.json()["authorization"]["approved_by_id"] == str(approver_id)
        assert approved.json()["authorization"]["authorization_expires_at"] is not None

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-write-ownership-transition-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        assert all(item["storage_write_performed"] is False for item in receipts.json())
        assert all(item["write_route_lease_created"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryWriteOwnershipTransitionAuthorization, UUID(authorization_id))
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "approved"
            assert document is not None and document.storage_key == original_storage_key
            assert read_route.route_class == "local_source"
            assert read_route.route_authority_kind == "local"
            assert read_route.route_version == original_read_route_version
            assert write_route.write_mode == "local_only"
            assert write_route.active_canary_lease_id is None
            assert write_route.route_version == original_write_route_version

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-ad-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-write-ownership-transition-authorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_ad_storage_outage_during_second_review_is_retryable(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ac(monkeypatch, tmp_path, endpoint, slug="phase-ad-outage")
        requested = _request_ad(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        _, approver_headers = _independent_admin(data, slug="phase-ad-outage-approver")
        original_builder = phase_ac_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase AD recovery-storage outage")

        monkeypatch.setattr(phase_ac_service, "_build_store", unavailable)
        outage = _approve_ad(data, authorization_id, headers=approver_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            a = db.get(EvidenceRecoveryWriteOwnershipTransitionAuthorization, UUID(authorization_id))
            assert a is not None and a.status == "pending_second_approval"

        monkeypatch.setattr(phase_ac_service, "_build_store", original_builder)
        retried = _approve_ad(data, authorization_id, headers=approver_headers)
        assert retried.status_code == 200, retried.text
        assert retried.json()["outcome"] == "approved"


def test_phase_ad_route_drift_invalidates_pending_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ac(monkeypatch, tmp_path, endpoint, slug="phase-ad-drift")
        requested = _request_ad(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        _, approver_headers = _independent_admin(data, slug="phase-ad-drift-approver")

        with TestingSessionLocal() as db:
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            write_route.route_version += 1
            db.commit()

        response = _approve_ad(data, authorization_id, headers=approver_headers)
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == "invalidated"
        assert response.json()["authorization"]["status"] == "invalidated"


def test_phase_ad_requires_admin_mfa_for_mutation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ac(monkeypatch, tmp_path, endpoint, slug="phase-ad-rbac")
        denied = _request_ad(data, headers=data["manager_headers"])
        assert denied.status_code == 403
