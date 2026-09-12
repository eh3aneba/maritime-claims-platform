from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_authoritative_storage_ratification_authorization_service as phase_am_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipLease,
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_authoritative_storage_ownership_health_service import (
    RecoveryAuthoritativeStorageOwnershipHealthUnavailable,
)
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageRatificationAuthorization,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_authoritative_storage_ownership_health import (
    _active_ak,
    _qualify_al,
    _request_al,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Authorize one later durable authoritative recovery evidence-storage ratification execution."
APPROVE_REASON = "Independent governance review approves one bounded ratification execution window."
REJECT_REASON = "Independent governance review rejects durable authoritative storage ratification."


def _qualified_al(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _active_ak(monkeypatch, tmp_path, endpoint, slug=slug)
    requester_id, requester_headers = _independent_admin(data, slug=f"{slug}-al-requester")
    qualifier_id, qualifier_headers = _independent_admin(data, slug=f"{slug}-al-qualifier")
    requested = _request_al(data, headers=requester_headers)
    assert requested.status_code == 201, requested.text
    qualification_id = requested.json()["qualification"]["id"]
    qualified = _qualify_al(data, qualification_id, headers=qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_al_health_id"] = qualification_id
    data["phase_al_requester_id"] = requester_id
    data["phase_al_requester_headers"] = requester_headers
    data["phase_al_qualifier_id"] = qualifier_id
    data["phase_al_qualifier_headers"] = qualifier_headers
    return data


def _request_am(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-authoritative-storage-ratification-authorizations",
        headers=headers,
        json={"health_qualification_id": data["phase_al_health_id"], "reason": reason},
    )


def _approve_am(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-authoritative-storage-ratification-authorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_am_approves_ratification_authorization_without_mutating_authority_or_storage(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_al(monkeypatch, tmp_path, endpoint, slug="phase-am-happy")
        requester_id, requester_headers = _independent_admin(data, slug="phase-am-requester")
        approver_id, approver_headers = _independent_admin(data, slug="phase-am-approver")

        denied = _request_am(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None
            original_storage_key = document.storage_key
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route_version = route.route_version
            assert route.authority_kind == "recovery_storage"
            assert str(route.active_authority_lease_id) == data["phase_ak_lease_id"]

        requested = _request_am(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        a = body["authorization"]
        authorization_id = a["id"]
        assert a["requested_by_id"] == str(requester_id)
        assert a["current_authority_kind"] == "recovery_storage"
        assert a["target_ratification_kind"] == "durable_recovery_storage"
        assert a["observed_local_authoritative"] is False
        assert a["observed_recovery_authoritative"] is True
        assert a["observed_authoritative_storage_changed"] is True
        assert a["ratification_authorized"] is False
        assert a["local_evidence_preserved"] is True
        assert a["storage_write_performed"] is False
        assert a["route_mutation_performed"] is False
        assert a["ownership_mutation_performed"] is False
        assert a["physical_disposal_authorized"] is False
        assert a["max_execution_windows"] == 1

        replay = _request_am(data, headers=requester_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        changed = _request_am(data, headers=requester_headers, reason=REQUEST_REASON + " Changed.")
        assert changed.status_code == 409

        forbidden = _approve_am(data, authorization_id, headers=data["phase_al_qualifier_headers"])
        assert forbidden.status_code == 409

        approved = _approve_am(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["outcome"] == "approved"
        approved_a = approved_body["authorization"]
        assert approved_a["approved_by_id"] == str(approver_id)
        assert approved_a["status"] == "approved"
        assert approved_a["ratification_authorized"] is True
        assert approved_a["authorization_expires_at"] is not None
        assert approved_a["local_evidence_preserved"] is True
        assert approved_a["route_mutation_performed"] is False
        assert approved_a["ownership_mutation_performed"] is False
        assert approved_a["destructive_action_performed"] is False
        assert approved_a["physical_disposal_authorized"] is False

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ratification-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        items = receipts.json()
        assert [item["phase"] for item in items] == ["requested", "approved"]
        assert items[0]["ratification_authorized"] is False
        assert items[1]["ratification_authorized"] is True
        assert all(item["local_evidence_preserved"] is True for item in items)
        assert all(item["route_mutation_performed"] is False for item in items)
        assert all(item["ownership_mutation_performed"] is False for item in items)
        assert all(item["physical_disposal_authorized"] is False for item in items)

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None and document.storage_key == original_storage_key
            lease = db.get(EvidenceRecoveryAuthoritativeStorageOwnershipLease, UUID(data["phase_ak_lease_id"]))
            assert lease is not None and lease.status == "active"
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert route.authority_kind == "recovery_storage"
            assert route.route_version == route_version
            assert str(route.active_authority_lease_id) == data["phase_ak_lease_id"]

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-am-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ratification-authorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_am_storage_outage_is_retryable_without_consuming_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_al(monkeypatch, tmp_path, endpoint, slug="phase-am-outage")
        _, requester_headers = _independent_admin(data, slug="phase-am-outage-requester")
        original = phase_am_service._active_ak_snapshot

        def unavailable(*args, **kwargs):
            raise RecoveryAuthoritativeStorageOwnershipHealthUnavailable(
                "simulated Phase AM recovery-storage outage"
            )

        monkeypatch.setattr(phase_am_service, "_active_ak_snapshot", unavailable)
        outage = _request_am(data, headers=requester_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageRatificationAuthorization).filter_by(
                phase_al_health_qualification_id=UUID(data["phase_al_health_id"])
            ).one_or_none() is None

        monkeypatch.setattr(phase_am_service, "_active_ak_snapshot", original)
        retried = _request_am(data, headers=requester_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "pending_second_approval"


def test_phase_am_route_drift_invalidates_pending_authorization(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_al(monkeypatch, tmp_path, endpoint, slug="phase-am-drift")
        _, requester_headers = _independent_admin(data, slug="phase-am-drift-requester")
        _, approver_headers = _independent_admin(data, slug="phase-am-drift-approver")
        requested = _request_am(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        approved = _approve_am(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "invalidated"
        assert approved.json()["authorization"]["status"] == "invalidated"
        assert approved.json()["authorization"]["ratification_authorized"] is False
        assert approved.json()["authorization"]["physical_disposal_authorized"] is False


def test_phase_am_review_expiry_is_terminal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_al(monkeypatch, tmp_path, endpoint, slug="phase-am-expiry")
        _, requester_headers = _independent_admin(data, slug="phase-am-expiry-requester")
        _, approver_headers = _independent_admin(data, slug="phase-am-expiry-approver")
        requested = _request_am(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = UUID(requested.json()["authorization"]["id"])

        with TestingSessionLocal() as db:
            a = db.get(EvidenceRecoveryAuthoritativeStorageRatificationAuthorization, authorization_id)
            assert a is not None
            a.review_expires_at = a.requested_at - timedelta(seconds=1)
            db.commit()

        expired = _approve_am(data, str(authorization_id), headers=approver_headers)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["authorization"]["status"] == "expired"
        assert expired.json()["authorization"]["ratification_authorized"] is False


def test_phase_am_rejection_is_independent_and_terminal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_al(monkeypatch, tmp_path, endpoint, slug="phase-am-reject")
        _, requester_headers = _independent_admin(data, slug="phase-am-reject-requester")
        _, reviewer_headers = _independent_admin(data, slug="phase-am-reject-reviewer")
        requested = _request_am(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        self_reject = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ratification-authorizations/{authorization_id}/reject",
            headers=requester_headers,
            json={"reason": REJECT_REASON},
        )
        assert self_reject.status_code == 409

        rejected = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ratification-authorizations/{authorization_id}/reject",
            headers=reviewer_headers,
            json={"reason": REJECT_REASON},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["outcome"] == "rejected"
        assert rejected.json()["authorization"]["status"] == "rejected"
        assert rejected.json()["authorization"]["ratification_authorized"] is False
