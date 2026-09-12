from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_authoritative_storage_ownership_execution_service as phase_ak_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_authoritative_storage_ownership_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization,
)
from app.modules.documents.recovery_authoritative_storage_ownership_authorization_service import (
    RecoveryAuthoritativeStorageOwnershipAuthorizationUnavailable,
)
from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipLease,
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_durable_write_ownership_execution_models import (
    EvidenceRecoveryDurableWriteOwnershipRoute,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_authoritative_storage_ownership_authorization import (
    _approve_aj,
    _qualified_ai,
    _request_aj,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


ACTIVATE_REASON = "Activate one bounded reversible authoritative recovery evidence-storage ownership window."
ROLLBACK_REASON = "Rollback authoritative recovery evidence-storage ownership to the preserved local evidence copy."
RECONCILE_REASON = "Reconcile the bounded authoritative recovery evidence-storage ownership state against fresh evidence."


def _approved_aj(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_ai(monkeypatch, tmp_path, endpoint, slug=slug)
    requester_id, requester_headers = _independent_admin(data, slug=f"{slug}-aj-requester")
    approver_id, approver_headers = _independent_admin(data, slug=f"{slug}-aj-approver")
    requested = _request_aj(data, headers=requester_headers)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approved = _approve_aj(data, authorization_id, headers=approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_aj_authorization_id"] = authorization_id
    data["phase_aj_requester_id"] = requester_id
    data["phase_aj_approver_id"] = approver_id
    return data


def _activate_ak(data, *, headers, reason: str = ACTIVATE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-authoritative-storage-ownership-leases",
        headers=headers,
        json={"authorization_id": data["phase_aj_authorization_id"], "reason": reason},
    )


def test_phase_ak_activation_and_rollback_change_only_authority_control_plane(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aj(monkeypatch, tmp_path, endpoint, slug="phase-ak-happy")
        activator_id, activator_headers = _independent_admin(data, slug="phase-ak-activator")
        _, rollback_headers = _independent_admin(data, slug="phase-ak-rollback")

        denied = _activate_ak(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        forbidden = _activate_ak(data, headers=data["phase_ai_qualifier_headers"])
        assert forbidden.status_code == 409

        with TestingSessionLocal() as db:
            document = db.get(Document, UUID(data["document_id"]))
            assert document is not None
            original_storage_key = document.storage_key
            ah_route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            ah_route_version = ah_route.route_version
            ah_lease_id = ah_route.active_durable_write_ownership_lease_id
            assert ah_route.write_mode == "recovery_primary"

        activated = _activate_ak(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        body = activated.json()
        assert body["outcome"] == "activated"
        lease = body["lease"]
        route = body["route"]
        lease_id = lease["id"]
        assert lease["status"] == "active"
        assert lease["activated_by_id"] == str(activator_id)
        assert lease["ownership_transition_active"] is True
        assert lease["local_authoritative"] is False
        assert lease["recovery_authoritative"] is True
        assert lease["authoritative_storage_changed"] is True
        assert lease["local_evidence_preserved"] is True
        assert lease["physical_disposal_authorized"] is False
        assert lease["storage_write_performed"] is False
        assert lease["document_storage_key_mutated"] is False
        assert lease["s3_put_performed"] is False
        assert lease["s3_copy_performed"] is False
        assert lease["s3_delete_performed"] is False
        assert lease["local_overwrite_performed"] is False
        assert lease["local_move_performed"] is False
        assert lease["local_delete_performed"] is False
        assert route["authority_kind"] == "recovery_storage"
        assert route["active_authority_lease_id"] == lease_id
        assert route["local_authoritative"] is False
        assert route["recovery_authoritative"] is True

        replay = _activate_ak(data, headers=activator_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id

        changed = _activate_ak(data, headers=activator_headers, reason=ACTIVATE_REASON + " Changed.")
        assert changed.status_code == 409

        with TestingSessionLocal() as db:
            document = db.get(Document, UUID(data["document_id"]))
            assert document is not None and document.storage_key == original_storage_key
            ah_route = db.query(EvidenceRecoveryDurableWriteOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert ah_route.write_mode == "recovery_primary"
            assert ah_route.route_version == ah_route_version
            assert ah_route.active_durable_write_ownership_lease_id == ah_lease_id

        rolled_back = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-leases/{lease_id}/rollback",
            headers=rollback_headers,
            json={"reason": ROLLBACK_REASON},
        )
        assert rolled_back.status_code == 200, rolled_back.text
        rolled = rolled_back.json()
        assert rolled["outcome"] == "rolled_back"
        assert rolled["lease"]["status"] == "rolled_back"
        assert rolled["lease"]["ownership_transition_active"] is False
        assert rolled["lease"]["local_authoritative"] is True
        assert rolled["lease"]["recovery_authoritative"] is False
        assert rolled["route"]["authority_kind"] == "local_evidence"
        assert rolled["route"]["active_authority_lease_id"] is None
        assert rolled["route"]["local_authoritative"] is True
        assert rolled["route"]["recovery_authoritative"] is False

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["activated", "rolled_back"]
        assert all(item["local_evidence_preserved"] is True for item in receipts.json())
        assert all(item["physical_disposal_authorized"] is False for item in receipts.json())
        assert all(item["storage_write_performed"] is False for item in receipts.json())

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-ak-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-leases/{lease_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_ak_storage_outage_is_retryable_without_consuming_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aj(monkeypatch, tmp_path, endpoint, slug="phase-ak-outage")
        _, activator_headers = _independent_admin(data, slug="phase-ak-outage-activator")
        original = phase_ak_service._fresh_ai

        def unavailable(*args, **kwargs):
            raise RecoveryAuthoritativeStorageOwnershipAuthorizationUnavailable(
                "simulated Phase AK recovery-storage outage"
            )

        monkeypatch.setattr(phase_ak_service, "_fresh_ai", unavailable)
        outage = _activate_ak(data, headers=activator_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageOwnershipLease).filter_by(
                authorization_id=UUID(data["phase_aj_authorization_id"])
            ).one_or_none() is None
            assert db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=UUID(data["document_id"])
            ).one_or_none() is None

        monkeypatch.setattr(phase_ak_service, "_fresh_ai", original)
        retried = _activate_ak(data, headers=activator_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "activated"


def test_phase_ak_route_drift_reconciles_fail_closed_to_local_authority(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aj(monkeypatch, tmp_path, endpoint, slug="phase-ak-drift")
        _, activator_headers = _independent_admin(data, slug="phase-ak-drift-activator")
        _, reconciler_headers = _independent_admin(data, slug="phase-ak-drift-reconciler")
        activated = _activate_ak(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        lease_id = activated.json()["lease"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=UUID(data["document_id"])
            ).one()
            route.route_version += 1
            db.commit()

        reconciled = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-leases/{lease_id}/reconcile",
            headers=reconciler_headers,
            json={"reason": RECONCILE_REASON},
        )
        assert reconciled.status_code == 200, reconciled.text
        body = reconciled.json()
        assert body["outcome"] == "invalidated"
        assert body["lease"]["status"] == "invalidated"
        assert body["route"]["authority_kind"] == "local_evidence"
        assert body["route"]["local_authoritative"] is True
        assert body["route"]["recovery_authoritative"] is False
        assert body["lease"]["local_evidence_preserved"] is True
        assert body["lease"]["physical_disposal_authorized"] is False


def test_phase_ak_expiry_reconciles_to_local_authority(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aj(monkeypatch, tmp_path, endpoint, slug="phase-ak-expiry")
        _, activator_headers = _independent_admin(data, slug="phase-ak-expiry-activator")
        _, reconciler_headers = _independent_admin(data, slug="phase-ak-expiry-reconciler")
        activated = _activate_ak(data, headers=activator_headers)
        assert activated.status_code == 201, activated.text
        lease_id = UUID(activated.json()["lease"]["id"])

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryAuthoritativeStorageOwnershipLease, lease_id)
            assert lease is not None
            lease.expires_at = lease.activated_at - timedelta(seconds=1)
            db.commit()

        reconciled = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-leases/{lease_id}/reconcile",
            headers=reconciler_headers,
            json={"reason": RECONCILE_REASON},
        )
        assert reconciled.status_code == 200, reconciled.text
        body = reconciled.json()
        assert body["outcome"] == "expired"
        assert body["lease"]["status"] == "expired"
        assert body["route"]["authority_kind"] == "local_evidence"
        assert body["route"]["active_authority_lease_id"] is None


def test_phase_ak_rejects_expired_aj_authorization_before_creating_lease(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_aj(monkeypatch, tmp_path, endpoint, slug="phase-ak-aj-expired")
        _, activator_headers = _independent_admin(data, slug="phase-ak-aj-expired-activator")
        with TestingSessionLocal() as db:
            authorization = db.get(
                EvidenceRecoveryAuthoritativeStorageOwnershipAuthorization,
                UUID(data["phase_aj_authorization_id"]),
            )
            assert authorization is not None and authorization.authorization_expires_at is not None
            authorization.authorization_expires_at = authorization.approved_at - timedelta(seconds=1)
            db.commit()

        response = _activate_ak(data, headers=activator_headers)
        assert response.status_code == 409, response.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageOwnershipLease).filter_by(
                authorization_id=UUID(data["phase_aj_authorization_id"])
            ).one_or_none() is None
