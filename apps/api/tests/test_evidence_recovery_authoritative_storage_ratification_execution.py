from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_authoritative_storage_ratification_execution_service as phase_an_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipLease,
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_authoritative_storage_ownership_execution_service import (
    reconcile_authoritative_storage_ownership,
)
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageRatificationAuthorization,
)
from app.modules.documents.recovery_authoritative_storage_ratification_execution_models import (
    EvidenceRecoveryAuthoritativeStorageRatification,
)
from app.modules.documents.recovery_authoritative_storage_ratification_execution_service import (
    RecoveryAuthoritativeStorageRatificationExecutionUnavailable,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_authoritative_storage_ratification_authorization import (
    _approve_am,
    _qualified_al,
    _request_am,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


EXECUTE_REASON = "Ratify the healthy bounded recovery-storage authority as durable authoritative storage."


def _approved_am(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_al(monkeypatch, tmp_path, endpoint, slug=slug)
    requester_id, requester_headers = _independent_admin(data, slug=f"{slug}-am-requester")
    approver_id, approver_headers = _independent_admin(data, slug=f"{slug}-am-approver")
    requested = _request_am(data, headers=requester_headers)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approved = _approve_am(data, authorization_id, headers=approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_am_authorization_id"] = authorization_id
    data["phase_am_requester_id"] = requester_id
    data["phase_am_requester_headers"] = requester_headers
    data["phase_am_approver_id"] = approver_id
    data["phase_am_approver_headers"] = approver_headers
    return data


def _execute_an(data, *, headers, reason: str = EXECUTE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-authoritative-storage-ratifications",
        headers=headers,
        json={"authorization_id": data["phase_am_authorization_id"], "reason": reason},
    )


def test_phase_an_ratifies_bounded_authority_without_mutating_evidence_bytes(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_am(monkeypatch, tmp_path, endpoint, slug="phase-an-happy")
        executor_id, executor_headers = _independent_admin(data, slug="phase-an-executor")

        denied = _execute_an(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None
            original_storage_key = document.storage_key
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            before_version = route.route_version
            assert route.authority_kind == "recovery_storage"
            assert route.authority_tenure == "bounded_recovery"
            assert str(route.active_authority_lease_id) == data["phase_ak_lease_id"]
            assert route.durable_ratification_id is None

        forbidden = _execute_an(data, headers=data["phase_am_approver_headers"])
        assert forbidden.status_code == 409

        executed = _execute_an(data, headers=executor_headers)
        assert executed.status_code == 201, executed.text
        body = executed.json()
        assert body["outcome"] == "ratified"
        ratification = body["ratification"]
        ratification_id = ratification["id"]
        assert ratification["executed_by_id"] == str(executor_id)
        assert ratification["status"] == "ratified"
        assert ratification["authority_kind"] == "recovery_storage"
        assert ratification["authority_tenure"] == "durable_recovery"
        assert ratification["ratification_active"] is True
        assert ratification["durable_authority_created"] is True
        assert ratification["local_authoritative"] is False
        assert ratification["recovery_authoritative"] is True
        assert ratification["authoritative_storage_changed"] is True
        assert ratification["local_evidence_preserved"] is True
        assert ratification["storage_write_performed"] is False
        assert ratification["route_mutation_performed"] is True
        assert ratification["ownership_mutation_performed"] is True
        assert ratification["read_path_switched"] is False
        assert ratification["write_path_switched"] is False
        assert ratification["document_storage_key_mutated"] is False
        assert ratification["destructive_action_performed"] is False
        assert ratification["physical_disposal_authorized"] is False
        assert ratification["s3_put_performed"] is False
        assert ratification["s3_copy_performed"] is False
        assert ratification["s3_delete_performed"] is False
        assert ratification["local_overwrite_performed"] is False
        assert ratification["local_move_performed"] is False
        assert ratification["local_delete_performed"] is False

        route_body = body["route"]
        assert route_body["authority_kind"] == "recovery_storage"
        assert route_body["authority_tenure"] == "durable_recovery"
        assert route_body["active_authority_lease_id"] is None
        assert route_body["durable_ratification_id"] == ratification_id
        assert route_body["route_version"] == before_version + 1
        assert route_body["local_evidence_preserved"] is True
        assert route_body["physical_disposal_authorized"] is False

        receipt = body["receipt"]
        assert receipt["phase"] == "ratified"
        assert receipt["from_authority_tenure"] == "bounded_recovery"
        assert receipt["to_authority_tenure"] == "durable_recovery"
        assert receipt["route_mutation_performed"] is True
        assert receipt["ownership_mutation_performed"] is True
        assert receipt["storage_write_performed"] is False
        assert receipt["physical_disposal_authorized"] is False

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None and document.storage_key == original_storage_key
            lease = db.get(EvidenceRecoveryAuthoritativeStorageOwnershipLease, UUID(data["phase_ak_lease_id"]))
            assert lease is not None
            assert lease.status == "ratified"
            assert lease.ownership_transition_active is False
            assert lease.local_authoritative is False
            assert lease.recovery_authoritative is True
            assert lease.authoritative_storage_changed is True
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert route.authority_tenure == "durable_recovery"
            assert str(route.durable_ratification_id) == ratification_id

            lease.expires_at = lease.activated_at - timedelta(seconds=1)
            db.commit()
            lease, reconcile_receipt, outcome = reconcile_authoritative_storage_ownership(
                db,
                organization_id=lease.organization_id,
                claim_id=lease.claim_id,
                document_id=lease.document_id,
                lease_id=lease.id,
                actor_id=executor_id,
                reason="Verify ratified authority no longer auto-expires with the bounded AK window.",
            )
            assert outcome == "unchanged"
            assert reconcile_receipt is None
            assert lease.status == "ratified"
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert route.authority_kind == "recovery_storage"
            assert route.authority_tenure == "durable_recovery"
            assert route.route_version == before_version + 1

        replay = _execute_an(data, headers=executor_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["ratification"]["id"] == ratification_id
        assert replay.json()["route"]["route_version"] == before_version + 1

        changed = _execute_an(data, headers=executor_headers, reason=EXECUTE_REASON + " Changed.")
        assert changed.status_code == 409

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ratifications/{ratification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["ratified"]

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-an-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ratifications/{ratification_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_an_expired_am_authorization_cannot_execute(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_am(monkeypatch, tmp_path, endpoint, slug="phase-an-expired-auth")
        _, executor_headers = _independent_admin(data, slug="phase-an-expired-executor")
        with TestingSessionLocal() as db:
            a = db.get(EvidenceRecoveryAuthoritativeStorageRatificationAuthorization, UUID(data["phase_am_authorization_id"]))
            assert a is not None
            a.authorization_expires_at = a.approved_at - timedelta(seconds=1)
            db.commit()

        response = _execute_an(data, headers=executor_headers)
        assert response.status_code == 409
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageRatification).filter_by(
                authorization_id=UUID(data["phase_am_authorization_id"])
            ).one_or_none() is None


def test_phase_an_storage_outage_is_retryable_without_consuming_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_am(monkeypatch, tmp_path, endpoint, slug="phase-an-outage")
        _, executor_headers = _independent_admin(data, slug="phase-an-outage-executor")
        original = phase_an_service._fresh_am

        def unavailable(*args, **kwargs):
            raise RecoveryAuthoritativeStorageRatificationExecutionUnavailable(
                "simulated Phase AN recovery-storage outage"
            )

        monkeypatch.setattr(phase_an_service, "_fresh_am", unavailable)
        outage = _execute_an(data, headers=executor_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageRatification).filter_by(
                authorization_id=UUID(data["phase_am_authorization_id"])
            ).one_or_none() is None

        monkeypatch.setattr(phase_an_service, "_fresh_am", original)
        retried = _execute_an(data, headers=executor_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "ratified"


def test_phase_an_route_drift_fails_closed_before_ratification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_am(monkeypatch, tmp_path, endpoint, slug="phase-an-drift")
        _, executor_headers = _independent_admin(data, slug="phase-an-drift-executor")
        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        response = _execute_an(data, headers=executor_headers)
        assert response.status_code == 409
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageRatification).filter_by(
                authorization_id=UUID(data["phase_am_authorization_id"])
            ).one_or_none() is None
