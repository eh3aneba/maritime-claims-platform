from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_authoritative_storage_ownership_health_service as phase_al_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipLease,
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_authoritative_storage_ownership_execution_service import (
    RecoveryAuthoritativeStorageOwnershipExecutionUnavailable,
)
from app.modules.documents.recovery_authoritative_storage_ownership_health_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_authoritative_storage_ownership_execution import (
    _activate_ak,
    _approved_aj,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Independently qualify the active authoritative recovery evidence-storage ownership window."
QUALIFY_REASON = "Independent health review confirms the bounded authoritative recovery storage window is healthy."
REJECT_REASON = "Independent health review rejects the authoritative recovery storage window."


def _active_ak(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_aj(monkeypatch, tmp_path, endpoint, slug=slug)
    activator_id, activator_headers = _independent_admin(data, slug=f"{slug}-ak-activator")
    activated = _activate_ak(data, headers=activator_headers)
    assert activated.status_code == 201, activated.text
    assert activated.json()["outcome"] == "activated"
    data["phase_ak_lease_id"] = activated.json()["lease"]["id"]
    data["phase_ak_activator_id"] = activator_id
    data["phase_ak_activator_headers"] = activator_headers
    return data


def _request_al(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-authoritative-storage-ownership-health-qualification",
        headers=headers,
        json={"authoritative_storage_ownership_lease_id": data["phase_ak_lease_id"], "reason": reason},
    )


def _qualify_al(data, qualification_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-authoritative-storage-ownership-health-qualifications/{qualification_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_al_qualifies_active_ak_without_mutating_authority_or_storage(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ak(monkeypatch, tmp_path, endpoint, slug="phase-al-happy")
        requester_id, requester_headers = _independent_admin(data, slug="phase-al-requester")
        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-al-qualifier")

        denied = _request_al(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None
            original_storage_key = document.storage_key
            ak_route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route_version = ak_route.route_version
            assert ak_route.authority_kind == "recovery_storage"
            assert str(ak_route.active_authority_lease_id) == data["phase_ak_lease_id"]

        requested = _request_al(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        request_body = requested.json()
        assert request_body["outcome"] == "pending_second_approval"
        q = request_body["qualification"]
        qualification_id = q["id"]
        assert q["requested_by_id"] == str(requester_id)
        assert q["observed_authority_kind"] == "recovery_storage"
        assert q["observed_ownership_transition_active"] is True
        assert q["observed_local_authoritative"] is False
        assert q["observed_recovery_authoritative"] is True
        assert q["observed_authoritative_storage_changed"] is True
        assert q["local_evidence_preserved"] is True
        assert q["storage_write_performed"] is False
        assert q["route_mutation_performed"] is False
        assert q["ownership_mutation_performed"] is False
        assert q["physical_disposal_authorized"] is False

        replay = _request_al(data, headers=requester_headers)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == qualification_id

        changed = _request_al(data, headers=requester_headers, reason=REQUEST_REASON + " Changed.")
        assert changed.status_code == 409

        forbidden = _qualify_al(data, qualification_id, headers=data["phase_ak_activator_headers"])
        assert forbidden.status_code == 409

        qualified = _qualify_al(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        qualified_body = qualified.json()
        assert qualified_body["outcome"] == "qualified"
        assert qualified_body["qualification"]["qualified_by_id"] == str(qualifier_id)
        assert qualified_body["qualification"]["status"] == "qualified"
        assert qualified_body["qualification"]["local_evidence_preserved"] is True
        assert qualified_body["qualification"]["route_mutation_performed"] is False
        assert qualified_body["qualification"]["ownership_mutation_performed"] is False
        assert qualified_body["qualification"]["destructive_action_performed"] is False

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-health-qualifications/{qualification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]
        assert all(item["local_evidence_preserved"] is True for item in receipts.json())
        assert all(item["route_mutation_performed"] is False for item in receipts.json())
        assert all(item["ownership_mutation_performed"] is False for item in receipts.json())
        assert all(item["physical_disposal_authorized"] is False for item in receipts.json())

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None and document.storage_key == original_storage_key
            lease = db.get(EvidenceRecoveryAuthoritativeStorageOwnershipLease, UUID(data["phase_ak_lease_id"]))
            assert lease is not None and lease.status == "active"
            ak_route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert ak_route.authority_kind == "recovery_storage"
            assert ak_route.route_version == route_version
            assert str(ak_route.active_authority_lease_id) == data["phase_ak_lease_id"]

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-al-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-health-qualifications/{qualification_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_al_storage_outage_is_retryable_without_consuming_health_artifact(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ak(monkeypatch, tmp_path, endpoint, slug="phase-al-outage")
        _, requester_headers = _independent_admin(data, slug="phase-al-outage-requester")
        original = phase_al_service._fresh_authorization

        def unavailable(*args, **kwargs):
            raise RecoveryAuthoritativeStorageOwnershipExecutionUnavailable(
                "simulated Phase AL recovery-storage outage"
            )

        monkeypatch.setattr(phase_al_service, "_fresh_authorization", unavailable)
        outage = _request_al(data, headers=requester_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification).filter_by(
                authoritative_storage_ownership_lease_id=UUID(data["phase_ak_lease_id"])
            ).one_or_none() is None

        monkeypatch.setattr(phase_al_service, "_fresh_authorization", original)
        retried = _request_al(data, headers=requester_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "pending_second_approval"


def test_phase_al_route_drift_invalidates_pending_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ak(monkeypatch, tmp_path, endpoint, slug="phase-al-drift")
        _, requester_headers = _independent_admin(data, slug="phase-al-drift-requester")
        _, qualifier_headers = _independent_admin(data, slug="phase-al-drift-qualifier")
        requested = _request_al(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        qualified = _qualify_al(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "invalidated"
        assert qualified.json()["qualification"]["status"] == "invalidated"
        assert qualified.json()["qualification"]["local_evidence_preserved"] is True
        assert qualified.json()["qualification"]["physical_disposal_authorized"] is False


def test_phase_al_review_expiry_is_terminal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ak(monkeypatch, tmp_path, endpoint, slug="phase-al-expiry")
        _, requester_headers = _independent_admin(data, slug="phase-al-expiry-requester")
        _, qualifier_headers = _independent_admin(data, slug="phase-al-expiry-qualifier")
        requested = _request_al(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = UUID(requested.json()["qualification"]["id"])

        with TestingSessionLocal() as db:
            q = db.get(EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification, qualification_id)
            assert q is not None
            q.review_expires_at = q.requested_at - timedelta(seconds=1)
            db.commit()

        expired = _qualify_al(data, str(qualification_id), headers=qualifier_headers)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["qualification"]["status"] == "expired"


def test_phase_al_rejection_is_four_eyes_and_terminal(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _active_ak(monkeypatch, tmp_path, endpoint, slug="phase-al-reject")
        _, requester_headers = _independent_admin(data, slug="phase-al-reject-requester")
        _, reviewer_headers = _independent_admin(data, slug="phase-al-reject-reviewer")
        requested = _request_al(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        self_reject = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-health-qualifications/{qualification_id}/reject",
            headers=requester_headers,
            json={"reason": REJECT_REASON},
        )
        assert self_reject.status_code == 409

        rejected = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-authoritative-storage-ownership-health-qualifications/{qualification_id}/reject",
            headers=reviewer_headers,
            json={"reason": REJECT_REASON},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["outcome"] == "rejected"
        assert rejected.json()["qualification"]["status"] == "rejected"
