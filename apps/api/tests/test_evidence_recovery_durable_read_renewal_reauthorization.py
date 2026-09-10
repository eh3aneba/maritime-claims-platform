from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents import recovery_durable_read_renewal_health_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_renewal_reauthorization_models import (
    EvidenceRecoveryDurableReadRenewalReauthorization,
    EvidenceRecoveryDurableReadRenewalReauthorizationReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import (
    _completed_p,
    _independent_admin,
    _qualify_q,
    _request_q,
)
from tests.test_evidence_recovery_restore_rehearsal import _RecoveryRestoreS3Handler, _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Authorize one additional bounded durable recovery read renewal from qualified Phase Q evidence."
APPROVE_REASON = "Independently approve one bounded follow-on durable read renewal authorization."


def _qualified_q(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _completed_p(monkeypatch, tmp_path, endpoint, slug=slug)
    q_qualifier_id, q_qualifier_headers = _independent_admin(data, slug=f"{slug}-q-qualifier")
    requested = _request_q(data)
    assert requested.status_code == 201, requested.text
    q_id = requested.json()["qualification"]["id"]
    qualified = _qualify_q(data, q_id, headers=q_qualifier_headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    data["phase_q_health_qualification_id"] = q_id
    data["phase_q_qualifier_id"] = q_qualifier_id
    data["phase_q_qualifier_headers"] = q_qualifier_headers
    return data


def _request_r(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-health-qualifications/{data['phase_q_health_qualification_id']}/renewal-reauthorization",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _approve_r(data, authorization_id: str, *, headers, reason: str = APPROVE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-reauthorizations/{authorization_id}/approve",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_r_qualified_q_creates_only_bounded_non_routable_reauthorization(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_q(monkeypatch, tmp_path, endpoint, slug="reauth-happy")
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]
        _, approver_headers = _independent_admin(data, slug="reauth-approver")

        requested = _request_r(data)
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "pending_second_approval"
        authorization = requested.json()["authorization"]
        authorization_id = authorization["id"]
        assert authorization["phase_q_health_qualification_id"] == data["phase_q_health_qualification_id"]
        assert authorization["health_state"] == "healthy"
        assert authorization["verified_durable_read_count"] >= 1
        assert authorization["integrity_failure_count"] == 0
        assert authorization["storage_unavailable_count"] == 0
        assert authorization["authorization_expires_at"] is None
        assert authorization["routable_authority_created"] is False
        assert authorization["durable_read_route_created"] is False
        assert authorization["read_path_switched"] is False
        assert authorization["write_path_switched"] is False
        assert authorization["document_storage_key_mutated"] is False
        assert authorization["authoritative_storage_changed"] is False
        assert authorization["destructive_action_performed"] is False

        replay = _request_r(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id
        changed = _request_r(data, reason="Use changed Phase R semantics and prove the immutable request replay rejects them.")
        assert changed.status_code == 409

        same_requester = _approve_r(data, authorization_id, headers=data["admin_headers"])
        assert same_requester.status_code == 409
        q_qualifier = _approve_r(data, authorization_id, headers=data["phase_q_qualifier_headers"])
        assert q_qualifier.status_code == 409
        phase_p_activator = _approve_r(data, authorization_id, headers=data["renewal_admin_headers"])
        assert phase_p_activator.status_code == 409

        approved = _approve_r(data, authorization_id, headers=approver_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        approved_auth = approved.json()["authorization"]
        assert approved_auth["status"] == "approved"
        assert approved_auth["authorization_expires_at"] is not None
        assert approved_auth["routable_authority_created"] is False
        assert approved_auth["read_path_switched"] is False

        approval_replay = _approve_r(data, authorization_id, headers=approver_headers)
        assert approval_replay.status_code == 200, approval_replay.text
        assert approval_replay.json()["outcome"] == "unchanged"

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-reauthorizations/{authorization_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200, manager_read.text
        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-reauthorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        manager_mutation = _request_r(data, headers=data["manager_headers"])
        assert manager_mutation.status_code == 403

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDurableReadRenewalReauthorization, UUID(authorization_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert stored is not None and document is not None
            assert stored.status == "approved"
            assert stored.approved_at is not None and stored.authorization_expires_at is not None
            assert stored.authorization_expires_at <= stored.approved_at + timedelta(minutes=10)
            assert stored.review_expires_at <= stored.requested_at + timedelta(minutes=10)
            assert document.storage_key == data["storage_key"]
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_durable_renewal_lease_id is None
            assert route.active_replica_id is None
            audit_rows = db.query(AuditLog).filter(
                AuditLog.entity_type == "evidence_recovery_durable_read_renewal_reauthorization"
            ).all()
            rendered = " ".join(str(item.new_values) for item in audit_rows)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered

        assert data["local_path"].read_bytes() == local_before
        assert _RecoveryRestoreS3Handler.objects[data["remote_key"]] == remote_before

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="reauth-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-reauthorizations/{authorization_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_r_requires_terminal_qualified_q_evidence(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_p(monkeypatch, tmp_path, endpoint, slug="reauth-pending-q")
        requested_q = _request_q(data)
        assert requested_q.status_code == 201, requested_q.text
        data["phase_q_health_qualification_id"] = requested_q.json()["qualification"]["id"]
        denied = _request_r(data)
        assert denied.status_code == 409


def test_phase_r_route_drift_invalidates_at_second_approval(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_q(monkeypatch, tmp_path, endpoint, slug="reauth-drift")
        _, approver_headers = _independent_admin(data, slug="reauth-drift-approver")
        requested = _request_r(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()
        invalidated = _approve_r(data, authorization_id, headers=approver_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["authorization"]["status"] == "invalidated"
        assert invalidated.json()["authorization"]["authorization_expires_at"] is None
        assert invalidated.json()["authorization"]["read_path_switched"] is False


def test_phase_r_review_expiry_fails_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_q(monkeypatch, tmp_path, endpoint, slug="reauth-expiry")
        _, approver_headers = _independent_admin(data, slug="reauth-expiry-approver")
        requested = _request_r(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]
        with TestingSessionLocal() as db:
            authorization = db.get(EvidenceRecoveryDurableReadRenewalReauthorization, UUID(authorization_id))
            assert authorization is not None
            authorization.review_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired = _approve_r(data, authorization_id, headers=approver_headers)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["authorization"]["status"] == "expired"
        assert expired.json()["authorization"]["authorization_expires_at"] is None
        assert expired.json()["authorization"]["routable_authority_created"] is False


def test_phase_r_storage_outage_is_retryable_and_preserves_pending(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_q(monkeypatch, tmp_path, endpoint, slug="reauth-outage")
        _, approver_headers = _independent_admin(data, slug="reauth-outage-approver")
        requested = _request_r(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase R object-store outage")

        monkeypatch.setattr(recovery_durable_read_renewal_health_service, "_read_verified_candidate", unavailable)
        outage = _approve_r(data, authorization_id, headers=approver_headers)
        assert outage.status_code == 503

        with TestingSessionLocal() as db:
            authorization = db.get(EvidenceRecoveryDurableReadRenewalReauthorization, UUID(authorization_id))
            assert authorization is not None
            assert authorization.status == "pending_second_approval"
            assert authorization.approved_by_id is None
            assert authorization.authorization_expires_at is None
            receipts = db.query(EvidenceRecoveryDurableReadRenewalReauthorizationReceipt).filter_by(
                reauthorization_id=UUID(authorization_id)
            ).all()
            assert [item.phase for item in receipts] == ["requested"]
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert route.route_authority_kind == "local"
            assert route.active_durable_renewal_lease_id is None
