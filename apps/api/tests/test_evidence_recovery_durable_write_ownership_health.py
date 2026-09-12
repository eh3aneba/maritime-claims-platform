from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_durable_write_ownership_health_service as phase_ai_service
from app.modules.documents.recovery_durable_write_ownership_execution_models import (
    EvidenceRecoveryDurableWriteOwnershipLease,
    EvidenceRecoveryDurableWriteOwnershipRoute,
)
from app.modules.documents.recovery_durable_write_ownership_execution_service import (
    RecoveryDurableWriteOwnershipExecutionUnavailable,
)
from app.modules.documents.recovery_durable_write_ownership_health_models import (
    EvidenceRecoveryDurableWriteOwnershipHealthQualification,
)
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import (
    EvidenceRecoveryRoutableDualWriteCanaryRoute,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_durable_write_ownership_execution import _activate_ah, _approved_ag, _rollback_ah
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Request independent health qualification of the active durable recovery write-ownership route."
QUALIFY_REASON = "Qualify durable recovery write ownership after fresh route, lineage and byte verification."


def _active_ah(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_ag(monkeypatch, tmp_path, endpoint, slug=slug)
    activator_id, activator_headers = _independent_admin(data, slug=f"{slug}-ah-activator")
    activated = _activate_ah(data, headers=activator_headers)
    assert activated.status_code == 201, activated.text
    assert activated.json()["outcome"] == "activated"
    data["phase_ah_lease_id"] = activated.json()["lease"]["id"]
    data["phase_ah_activator_id"] = activator_id
    data["phase_ah_activator_headers"] = activator_headers
    return data


def _request_ai(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-durable-write-ownership-health-qualification",
        headers=headers,
        json={"durable_write_ownership_lease_id": data["phase_ah_lease_id"], "reason": reason},
    )


def _qualify_ai(data, qualification_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-durable-write-ownership-health-qualifications/{qualification_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_ai_qualifies_active_durable_write_ownership_without_route_mutation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ah(monkeypatch, tmp_path, endpoint, slug="phase-ai-happy")
        requester_id, requester_headers = _independent_admin(data, slug="phase-ai-requester")
        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-ai-qualifier")

        denied = _request_ai(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            durable_route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            durable_version = durable_route.route_version
            assert durable_route.write_mode == "recovery_primary"
            assert str(durable_route.active_durable_write_ownership_lease_id) == data["phase_ah_lease_id"]
            experiment_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            experiment_version = experiment_route.route_version
            assert experiment_route.write_mode == "local_only"

        requested = _request_ai(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        q = body["qualification"]
        qualification_id = q["id"]
        assert q["status"] == "pending_second_approval"
        assert q["health_state"] == "healthy"
        assert q["observed_durable_write_mode"] == "recovery_primary"
        assert q["observed_durable_write_ownership_active"] is True
        assert q["local_authoritative"] is True
        assert q["storage_write_performed"] is False
        assert q["route_mutation_performed"] is False
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
        assert q["durable_route_version_at_request"] == durable_version

        replay = _request_ai(data, headers=requester_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == qualification_id

        changed_replay = _request_ai(data, headers=requester_headers, reason=REQUEST_REASON + " Changed.")
        assert changed_replay.status_code == 409

        forbidden = _qualify_ai(data, qualification_id, headers=data["phase_ah_activator_headers"])
        assert forbidden.status_code == 409

        qualified = _qualify_ai(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        qb = qualified.json()
        assert qb["outcome"] == "qualified"
        assert qb["qualification"]["status"] == "qualified"
        assert qb["qualification"]["qualified_by_id"] == str(qualifier_id)

        fetched = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-health-qualifications/{qualification_id}",
            headers=data["manager_headers"],
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["status"] == "qualified"

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-health-qualifications/{qualification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]
        assert all(item["route_mutation_performed"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            durable_route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert durable_route.write_mode == "recovery_primary"
            assert str(durable_route.active_durable_write_ownership_lease_id) == data["phase_ah_lease_id"]
            assert durable_route.route_version == durable_version
            experiment_route = db.query(EvidenceRecoveryRoutableDualWriteCanaryRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert experiment_route.write_mode == "local_only"
            assert experiment_route.route_version == experiment_version
            lease = db.get(EvidenceRecoveryDurableWriteOwnershipLease, UUID(data["phase_ah_lease_id"]))
            assert lease is not None and lease.status == "active"
            assert lease.durable_write_ownership_active is True

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(
            slug="phase-ai-other", storage_root=tmp_path / "other"
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-write-ownership-health-qualifications/{qualification_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404
        assert requester_id != qualifier_id


def test_phase_ai_storage_outage_is_retryable_without_creating_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ah(monkeypatch, tmp_path, endpoint, slug="phase-ai-outage")
        _, requester_headers = _independent_admin(data, slug="phase-ai-outage-requester")
        original = phase_ai_service._fresh_authorization_snapshot

        def unavailable(*args, **kwargs):
            raise RecoveryDurableWriteOwnershipExecutionUnavailable(
                "simulated Phase AI recovery-storage outage"
            )

        monkeypatch.setattr(phase_ai_service, "_fresh_authorization_snapshot", unavailable)
        outage = _request_ai(data, headers=requester_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryDurableWriteOwnershipHealthQualification).filter_by(
                durable_write_ownership_lease_id=UUID(data["phase_ah_lease_id"])
            ).one_or_none() is None

        monkeypatch.setattr(phase_ai_service, "_fresh_authorization_snapshot", original)
        retried = _request_ai(data, headers=requester_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "pending_second_approval"


def test_phase_ai_durable_route_drift_invalidates_pending_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ah(monkeypatch, tmp_path, endpoint, slug="phase-ai-route-drift")
        _, requester_headers = _independent_admin(data, slug="phase-ai-route-drift-requester")
        _, qualifier_headers = _independent_admin(data, slug="phase-ai-route-drift-qualifier")
        requested = _request_ai(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        qualified = _qualify_ai(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "invalidated"
        assert qualified.json()["qualification"]["status"] == "invalidated"


def test_phase_ai_byte_drift_invalidates_pending_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ah(monkeypatch, tmp_path, endpoint, slug="phase-ai-byte-drift")
        _, requester_headers = _independent_admin(data, slug="phase-ai-byte-drift-requester")
        _, qualifier_headers = _independent_admin(data, slug="phase-ai-byte-drift-qualifier")
        requested = _request_ai(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]
        original = phase_ai_service._fresh_authorization_snapshot

        def drifted(*args, **kwargs):
            q, receipt, snapshot = original(*args, **kwargs)
            return q, receipt, replace(snapshot, observed_recovery_hash="0" * 64)

        monkeypatch.setattr(phase_ai_service, "_fresh_authorization_snapshot", drifted)
        qualified = _qualify_ai(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "invalidated"
        assert qualified.json()["qualification"]["status"] == "invalidated"


def test_phase_ai_review_expiry_is_terminal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ah(monkeypatch, tmp_path, endpoint, slug="phase-ai-expiry")
        _, requester_headers = _independent_admin(data, slug="phase-ai-expiry-requester")
        qualifier_id, _ = _independent_admin(data, slug="phase-ai-expiry-qualifier")
        requested = _request_ai(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = UUID(requested.json()["qualification"]["id"])

        with TestingSessionLocal() as db:
            q = db.get(EvidenceRecoveryDurableWriteOwnershipHealthQualification, qualification_id)
            assert q is not None
            q, receipt, outcome = phase_ai_service.qualify_durable_write_ownership_health(
                db,
                organization_id=q.organization_id,
                claim_id=q.claim_id,
                document_id=q.document_id,
                qualification_id=q.id,
                qualified_by_id=qualifier_id,
                reason=QUALIFY_REASON,
                now=q.review_expires_at + timedelta(seconds=1),
            )
            assert outcome == "expired"
            assert receipt is not None and receipt.phase == "expired"
            db.commit()


def test_phase_ai_rejects_rolled_back_ah_lease(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ah(monkeypatch, tmp_path, endpoint, slug="phase-ai-rolled-back")
        _, rollback_headers = _independent_admin(data, slug="phase-ai-rollback-actor")
        rolled_back = _rollback_ah(data, data["phase_ah_lease_id"], headers=rollback_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        _, requester_headers = _independent_admin(data, slug="phase-ai-after-rollback-requester")
        blocked = _request_ai(data, headers=requester_headers)
        assert blocked.status_code == 409, blocked.text
