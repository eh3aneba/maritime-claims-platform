from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_authoritative_storage_ownership_authorization_service as phase_aj_service
from app.modules.documents.recovery_authoritative_storage_ownership_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization,
)
from app.modules.documents.recovery_durable_write_ownership_execution_models import (
    EvidenceRecoveryDurableWriteOwnershipLease,
    EvidenceRecoveryDurableWriteOwnershipRoute,
)
from app.modules.documents.recovery_durable_write_ownership_health_service import (
    RecoveryDurableWriteOwnershipHealthUnavailable,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_durable_write_ownership_health import _active_ah, _qualify_ai, _request_ai
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Request Four-Eyes authorization for one future authoritative recovery evidence-storage ownership execution."
APPROVE_REASON = "Approve one bounded future authoritative recovery evidence-storage ownership execution after fresh verification."


def _qualified_ai(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _active_ah(monkeypatch, tmp_path, endpoint, slug=slug)
    requester_id, requester_headers = _independent_admin(data, slug=f"{slug}-ai-requester")
    qualifier_id, qualifier_headers = _independent_admin(data, slug=f"{slug}-ai-qualifier")
    requested = _request_ai(data, headers=requester_headers)
    assert requested.status_code == 201, requested.text
    qualification_id = requested.json()["qualification"]["id"]
    qualified = _qualify_ai(data, qualification_id, headers=qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_ai_health_qualification_id"] = qualification_id
    data["phase_ai_requester_id"] = requester_id
    data["phase_ai_requester_headers"] = requester_headers
    data["phase_ai_qualifier_id"] = qualifier_id
    data["phase_ai_qualifier_headers"] = qualifier_headers
    return data


def _request_aj(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-authoritative-storage-ownership-authorizations",
        headers=headers,
        json={"health_qualification_id": data["phase_ai_health_qualification_id"], "reason": reason},
    )


def _approve_aj(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-authoritative-storage-ownership-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_aj_approves_governance_authorization_without_storage_or_route_mutation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ai(monkeypatch, tmp_path, endpoint, slug="phase-aj-happy")
        requester_id, requester_headers = _independent_admin(data, slug="phase-aj-requester")
        approver_id, approver_headers = _independent_admin(data, slug="phase-aj-approver")

        denied = _request_aj(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route_version = route.route_version
            assert route.write_mode == "recovery_primary"
            assert str(route.active_durable_write_ownership_lease_id) == data["phase_ah_lease_id"]

        requested = _request_aj(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        a = body["authorization"]
        authorization_id = a["id"]
        assert a["status"] == "pending_second_approval"
        assert a["current_authority_kind"] == "local_evidence"
        assert a["target_authority_kind"] == "recovery_storage"
        assert a["max_execution_windows"] == 1
        assert a["local_authoritative"] is True
        assert a["storage_write_performed"] is False
        assert a["route_mutation_performed"] is False
        assert a["document_storage_key_mutated"] is False
        assert a["authoritative_storage_changed"] is False
        assert a["destructive_action_performed"] is False
        assert a["physical_disposal_authorized"] is False
        assert a["s3_put_performed"] is False
        assert a["s3_copy_performed"] is False
        assert a["s3_delete_performed"] is False
        assert a["local_overwrite_performed"] is False
        assert a["local_move_performed"] is False
        assert a["local_delete_performed"] is False

        replay = _request_aj(data, headers=requester_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        changed = _request_aj(data, headers=requester_headers, reason=REQUEST_REASON + " Changed.")
        assert changed.status_code == 409

        forbidden = _approve_aj(data, authorization_id, headers=data["phase_ai_qualifier_headers"])
        assert forbidden.status_code == 409

        approved = _approve_aj(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["outcome"] == "approved"
        assert approved_body["authorization"]["status"] == "approved"
        assert approved_body["authorization"]["approved_by_id"] == str(approver_id)
        assert approved_body["authorization"]["authorization_expires_at"] is not None
        assert approved_body["authorization"]["authoritative_storage_changed"] is False
        assert approved_body["authorization"]["physical_disposal_authorized"] is False

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert route.write_mode == "recovery_primary"
            assert route.route_version == route_version
            assert str(route.active_durable_write_ownership_lease_id) == data["phase_ah_lease_id"]
            lease = db.get(EvidenceRecoveryDurableWriteOwnershipLease, UUID(data["phase_ah_lease_id"]))
            assert lease is not None and lease.status == "active"
            assert lease.local_authoritative is True

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        assert all(item["authoritative_storage_changed"] is False for item in receipts.json())
        assert all(item["physical_disposal_authorized"] is False for item in receipts.json())

        fetched = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-authorizations/{authorization_id}",
            headers=data["manager_headers"],
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["status"] == "approved"

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-aj-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-authorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404
        assert requester_id != approver_id


def test_phase_aj_recovery_storage_outage_is_retryable_without_creating_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ai(monkeypatch, tmp_path, endpoint, slug="phase-aj-outage")
        _, requester_headers = _independent_admin(data, slug="phase-aj-outage-requester")
        original = phase_aj_service._active_ah_snapshot

        def unavailable(*args, **kwargs):
            raise RecoveryDurableWriteOwnershipHealthUnavailable("simulated Phase AJ recovery-storage outage")

        monkeypatch.setattr(phase_aj_service, "_active_ah_snapshot", unavailable)
        outage = _request_aj(data, headers=requester_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization).filter_by(
                phase_ai_health_qualification_id=UUID(data["phase_ai_health_qualification_id"])
            ).one_or_none() is None

        monkeypatch.setattr(phase_aj_service, "_active_ah_snapshot", original)
        retried = _request_aj(data, headers=requester_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "pending_second_approval"


def test_phase_aj_durable_route_drift_invalidates_pending_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ai(monkeypatch, tmp_path, endpoint, slug="phase-aj-drift")
        _, requester_headers = _independent_admin(data, slug="phase-aj-drift-requester")
        _, approver_headers = _independent_admin(data, slug="phase-aj-drift-approver")
        requested = _request_aj(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        approved = _approve_aj(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "invalidated"
        assert approved.json()["authorization"]["status"] == "invalidated"
        assert approved.json()["authorization"]["authoritative_storage_changed"] is False


def test_phase_aj_review_expiry_is_terminal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_ai(monkeypatch, tmp_path, endpoint, slug="phase-aj-expiry")
        _, requester_headers = _independent_admin(data, slug="phase-aj-expiry-requester")
        approver_id, _ = _independent_admin(data, slug="phase-aj-expiry-approver")
        requested = _request_aj(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = UUID(requested.json()["authorization"]["id"])

        with TestingSessionLocal() as db:
            a = db.get(EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization, authorization_id)
            assert a is not None
            a, receipt, outcome = phase_aj_service.approve_authoritative_storage_ownership_authorization(
                db,
                organization_id=a.organization_id,
                claim_id=a.claim_id,
                document_id=a.document_id,
                authorization_id=a.id,
                approved_by_id=approver_id,
                reason=APPROVE_REASON,
                now=a.review_expires_at + timedelta(seconds=1),
            )
            assert outcome == "expired"
            assert a.status == "expired"
            assert receipt is not None and receipt.phase == "expired"
            db.commit()


def test_phase_aj_requires_qualified_ai_artifact(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ah(monkeypatch, tmp_path, endpoint, slug="phase-aj-ai-pending")
        _, ai_requester_headers = _independent_admin(data, slug="phase-aj-ai-pending-requester")
        requested_ai = _request_ai(data, headers=ai_requester_headers)
        assert requested_ai.status_code == 201, requested_ai.text
        data["phase_ai_health_qualification_id"] = requested_ai.json()["qualification"]["id"]
        _, requester_headers = _independent_admin(data, slug="phase-aj-requester")
        blocked = _request_aj(data, headers=requester_headers)
        assert blocked.status_code == 409, blocked.text
