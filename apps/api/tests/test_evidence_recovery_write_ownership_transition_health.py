from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_write_ownership_transition_health_service as phase_af_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_replication_service import RecoveryReplicationUnavailable
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import EvidenceRecoveryRoutableDualWriteCanaryRoute
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_write_ownership_transition_health_models import (
    EvidenceRecoveryWriteOwnershipTransitionHealthQualification,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant
from tests.test_evidence_recovery_write_ownership_transition_execution import (
    _activate_ae,
    _approved_ad,
    _rollback_ae,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Independently verify the completed Phase AE transition and exact local-only restoration."
QUALIFY_REASON = "Confirm fresh local and recovery integrity plus exact post-transition route health."


def _completed_ae(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_ad(monkeypatch, tmp_path, endpoint, slug=slug)
    activator_id, activator_headers = _independent_admin(data, slug=f"{slug}-ae-activator")
    activated = _activate_ae(data, headers=activator_headers)
    assert activated.status_code == 201, activated.text
    lease_id = activated.json()["lease"]["id"]
    rolled_back = _rollback_ae(data, lease_id, headers=activator_headers)
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"
    data["phase_ae_lease_id"] = lease_id
    data["phase_ae_activator_id"] = activator_id
    data["phase_ae_activator_headers"] = activator_headers
    return data


def _request_af(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-write-ownership-transition-health-qualification",
        headers=headers,
        json={"transition_lease_id": data["phase_ae_lease_id"], "reason": reason},
    )


def _qualify_af(data, health_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-write-ownership-transition-health-qualifications/{health_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_af_independently_qualifies_completed_ae_without_route_or_storage_mutation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ae(monkeypatch, tmp_path, endpoint, slug="phase-af-happy")
        requester_id, requester_headers = _independent_admin(data, slug="phase-af-requester")
        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-af-qualifier")
        assert qualifier_id not in {
            requester_id,
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

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None
            original_storage_key = document.storage_key
            original_read_version = read_route.route_version
            original_write_version = write_route.route_version
            assert write_route.write_mode == "local_only"
            assert write_route.active_write_ownership_transition_lease_id is None

        denied = _request_af(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        requested = _request_af(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        q = body["qualification"]
        health_id = q["id"]
        assert q["status"] == "pending_second_approval"
        assert q["health_state"] == "healthy"
        assert q["local_authoritative"] is True
        assert q["storage_write_performed"] is False
        assert q["write_route_reactivated"] is False
        assert q["durable_write_authority_created"] is False
        assert q["read_path_switched"] is False
        assert q["write_path_switched"] is False
        assert q["document_storage_key_mutated"] is False
        assert q["authoritative_storage_changed"] is False
        assert q["destructive_action_performed"] is False
        assert q["s3_put_performed"] is False
        assert q["s3_copy_performed"] is False
        assert q["s3_delete_performed"] is False
        assert q["local_overwrite_performed"] is False
        assert q["local_move_performed"] is False
        assert q["local_delete_performed"] is False
        assert q["observed_local_hash"] == q["source_file_hash"]
        assert q["observed_recovery_hash"] == q["source_file_hash"]
        assert q["observed_local_size_bytes"] == q["source_file_size_bytes"]
        assert q["observed_recovery_size_bytes"] == q["source_file_size_bytes"]
        assert q["read_route_version_at_request"] == original_read_version
        assert q["write_route_version_at_request"] == original_write_version

        replay = _request_af(data, headers=requester_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == health_id

        forbidden = _qualify_af(data, health_id, headers=data["phase_ae_activator_headers"])
        assert forbidden.status_code == 409

        qualified = _qualify_af(data, health_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["status"] == "qualified"
        assert qualified.json()["qualification"]["qualified_by_id"] == str(qualifier_id)

        fetched = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-write-ownership-transition-health-qualifications/{health_id}",
            headers=data["manager_headers"],
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["status"] == "qualified"

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-write-ownership-transition-health-qualifications/{health_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            read_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            write_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None and document.storage_key == original_storage_key
            assert read_route.route_class == "local_source"
            assert read_route.route_version == original_read_version
            assert write_route.write_mode == "local_only"
            assert write_route.active_canary_lease_id is None
            assert write_route.active_write_ownership_transition_lease_id is None
            assert write_route.route_version == original_write_version

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-af-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-write-ownership-transition-health-qualifications/{health_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_af_recovery_storage_outage_is_retryable_without_consuming_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ae(monkeypatch, tmp_path, endpoint, slug="phase-af-outage")
        _, requester_headers = _independent_admin(data, slug="phase-af-outage-requester")
        original_builder = phase_af_service._build_store

        def unavailable():
            raise RecoveryReplicationUnavailable("simulated Phase AF recovery-storage outage")

        monkeypatch.setattr(phase_af_service, "_build_store", unavailable)
        outage = _request_af(data, headers=requester_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            q = db.query(EvidenceRecoveryWriteOwnershipTransitionHealthQualification).filter_by(
                transition_lease_id=UUID(data["phase_ae_lease_id"])
            ).one_or_none()
            assert q is None

        monkeypatch.setattr(phase_af_service, "_build_store", original_builder)
        retried = _request_af(data, headers=requester_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "pending_second_approval"


def test_phase_af_fresh_route_drift_invalidates_pending_review(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ae(monkeypatch, tmp_path, endpoint, slug="phase-af-drift")
        _, requester_headers = _independent_admin(data, slug="phase-af-drift-requester")
        _, qualifier_headers = _independent_admin(data, slug="phase-af-drift-qualifier")
        requested = _request_af(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        health_id = requested.json()["qualification"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(document_id=data["document_id"]).one()
            route.route_version += 1
            db.commit()

        qualified = _qualify_af(data, health_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "invalidated"
        assert qualified.json()["qualification"]["status"] == "invalidated"


def test_phase_af_review_expiry_is_terminal_and_replay_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_ae(monkeypatch, tmp_path, endpoint, slug="phase-af-terminal")
        requester_id, requester_headers = _independent_admin(data, slug="phase-af-terminal-requester")
        reviewer_id, _ = _independent_admin(data, slug="phase-af-terminal-reviewer")
        requested = _request_af(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        health_id = UUID(requested.json()["qualification"]["id"])

        with TestingSessionLocal() as db:
            q = db.get(EvidenceRecoveryWriteOwnershipTransitionHealthQualification, health_id)
            assert q is not None
            q, receipt, outcome = phase_af_service.qualify_write_ownership_transition_health(
                db,
                organization_id=q.organization_id,
                claim_id=q.claim_id,
                document_id=q.document_id,
                health_qualification_id=q.id,
                qualified_by_id=reviewer_id,
                reason=QUALIFY_REASON,
                now=q.review_expires_at + timedelta(seconds=1),
            )
            assert outcome == "expired"
            assert receipt is not None and receipt.phase == "expired"
            db.commit()

        requested_again = _request_af(data, headers=requester_headers)
        assert requested_again.status_code == 201, requested_again.text
        assert requested_again.json()["outcome"] == "unchanged"
        assert requested_again.json()["qualification"]["status"] == "expired"
        assert requested_again.json()["qualification"]["id"] == str(health_id)
        assert requester_id != reviewer_id


def test_phase_af_cannot_start_from_active_ae_window(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_ad(monkeypatch, tmp_path, endpoint, slug="phase-af-active")
        _, activator_headers = _independent_admin(data, slug="phase-af-active-activator")
        activated = _activate_ae(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        data["phase_ae_lease_id"] = activated.json()["lease"]["id"]
        _, requester_headers = _independent_admin(data, slug="phase-af-active-requester")

        blocked = _request_af(data, headers=requester_headers)
        assert blocked.status_code == 409
