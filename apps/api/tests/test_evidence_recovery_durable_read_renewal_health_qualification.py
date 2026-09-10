from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents import (
    recovery_durable_read_renewal_health_service,
    recovery_durable_read_renewal_routing_service,
)
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_renewal_health_models import (
    EvidenceRecoveryDurableReadRenewalHealthQualification,
    EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_routing import (
    _activate_p,
    _approved_o,
    _download,
    _prepare_p,
    _rollback_p,
)
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Qualify the completed Phase P durable recovery read renewal window from observed operational evidence."
QUALIFY_REASON = "Independently confirm the completed Phase P renewal window remained healthy and non-destructive."


def _independent_admin(data, *, slug: str):
    with TestingSessionLocal() as db:
        admin = User(
            organization_id=data["org_id"],
            email=f"phase-q-{slug}@example.com",
            full_name=f"Phase Q Admin {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        admin_id = admin.id
    return admin_id, _headers(admin_id)


def _completed_p(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_o(monkeypatch, tmp_path, endpoint, slug=slug)
    prepared = _prepare_p(data)
    assert prepared.status_code == 201, prepared.text
    lease_id = prepared.json()["lease"]["id"]
    activated = _activate_p(data, lease_id)
    assert activated.status_code == 200, activated.text
    assert activated.json()["outcome"] == "activated"
    verified = _download(data)
    assert verified.status_code == 200, verified.text
    assert verified.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica-durable-renewal"
    rolled_back = _rollback_p(data, lease_id)
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"
    data["renewal_lease_id"] = lease_id
    return data


def _request_q(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-health-qualification",
        headers=headers or data["admin_headers"],
        json={"renewal_lease_id": data["renewal_lease_id"], "reason": reason},
    )


def _qualify_q(data, qualification_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-health-qualifications/{qualification_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_completed_phase_p_window_is_independently_qualified_without_new_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_p(monkeypatch, tmp_path, endpoint, slug="renewal-health-happy")
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]
        _, qualifier_headers = _independent_admin(data, slug="happy")

        requested = _request_q(data)
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "pending_second_approval"
        qualification = requested.json()["qualification"]
        qualification_id = qualification["id"]
        assert qualification["renewal_lease_id"] == data["renewal_lease_id"]
        assert qualification["health_state"] == "healthy"
        assert qualification["verified_durable_read_count"] >= 1
        assert qualification["integrity_failure_count"] == 0
        assert qualification["storage_unavailable_count"] == 0
        assert qualification["routable_authority_created"] is False
        assert qualification["durable_read_route_created"] is False
        assert qualification["read_path_switched"] is False
        assert qualification["write_path_switched"] is False
        assert qualification["authoritative_storage_changed"] is False
        assert qualification["destructive_action_performed"] is False

        replay = _request_q(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == qualification_id

        changed_replay = _request_q(data, reason="Use a different Phase Q request reason to prove replay semantics are immutable.")
        assert changed_replay.status_code == 409

        same_requester = _qualify_q(data, qualification_id, headers=data["admin_headers"])
        assert same_requester.status_code == 409
        phase_p_activator = _qualify_q(data, qualification_id, headers=data["renewal_admin_headers"])
        assert phase_p_activator.status_code == 409
        prior_phase_m_activator = _qualify_q(data, qualification_id, headers=data["k_qualifier_headers"])
        assert prior_phase_m_activator.status_code == 409

        qualified = _qualify_q(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["status"] == "qualified"
        assert qualified.json()["qualification"]["routable_authority_created"] is False
        assert qualified.json()["qualification"]["read_path_switched"] is False

        approval_replay = _qualify_q(data, qualification_id, headers=qualifier_headers)
        assert approval_replay.status_code == 200, approval_replay.text
        assert approval_replay.json()["outcome"] == "unchanged"

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-health-qualifications/{qualification_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200, manager_read.text
        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-health-qualifications/{qualification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]
        manager_mutation = _request_q(data, headers=data["manager_headers"])
        assert manager_mutation.status_code == 403

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDurableReadRenewalHealthQualification, UUID(qualification_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert stored is not None and document is not None
            assert stored.status == "qualified"
            assert stored.review_expires_at <= stored.requested_at + timedelta(minutes=10)
            assert document.storage_key == data["storage_key"]
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_durable_renewal_lease_id is None
            assert route.active_replica_id is None
            audit_rows = db.query(AuditLog).filter(
                AuditLog.entity_type == "evidence_recovery_durable_read_renewal_health_qualification"
            ).all()
            rendered = " ".join(str(item.new_values) for item in audit_rows)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered

        assert data["local_path"].read_bytes() == local_before
        assert _RecoveryRestoreS3Handler.objects[data["remote_key"]] == remote_before

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(
            slug="renewal-health-other",
            storage_root=tmp_path / "other",
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-health-qualifications/{qualification_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_q_route_drift_invalidates_fail_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_p(monkeypatch, tmp_path, endpoint, slug="renewal-health-drift")
        _, qualifier_headers = _independent_admin(data, slug="drift")
        requested = _request_q(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()

        invalidated = _qualify_q(data, qualification_id, headers=qualifier_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["qualification"]["status"] == "invalidated"
        assert invalidated.json()["qualification"]["read_path_switched"] is False


def test_phase_q_review_expiry_fails_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_p(monkeypatch, tmp_path, endpoint, slug="renewal-health-expiry")
        _, qualifier_headers = _independent_admin(data, slug="expiry")
        requested = _request_q(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]
        with TestingSessionLocal() as db:
            qualification = db.get(EvidenceRecoveryDurableReadRenewalHealthQualification, UUID(qualification_id))
            assert qualification is not None
            qualification.review_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        expired = _qualify_q(data, qualification_id, headers=qualifier_headers)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["qualification"]["status"] == "expired"
        assert expired.json()["qualification"]["routable_authority_created"] is False


def test_phase_q_storage_outage_is_retryable_and_preserves_pending_record(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_p(monkeypatch, tmp_path, endpoint, slug="renewal-health-outage")
        _, qualifier_headers = _independent_admin(data, slug="outage")
        requested = _request_q(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase Q object-store outage")

        monkeypatch.setattr(
            recovery_durable_read_renewal_health_service,
            "_read_verified_candidate",
            unavailable,
        )
        outage = _qualify_q(data, qualification_id, headers=qualifier_headers)
        assert outage.status_code == 503

        with TestingSessionLocal() as db:
            qualification = db.get(EvidenceRecoveryDurableReadRenewalHealthQualification, UUID(qualification_id))
            assert qualification is not None
            assert qualification.status == "pending_second_approval"
            assert qualification.qualified_by_id is None
            assert qualification.terminal_at is None
            receipts = db.query(EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt).filter_by(
                health_qualification_id=UUID(qualification_id)
            ).all()
            assert [item.phase for item in receipts] == ["requested"]
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert route.route_authority_kind == "local"
            assert route.active_durable_renewal_lease_id is None


def test_phase_q_marks_window_degraded_when_phase_p_had_storage_unavailability(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_o(monkeypatch, tmp_path, endpoint, slug="renewal-health-degraded")
        prepared = _prepare_p(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_p(data, lease_id)
        assert activated.status_code == 200, activated.text

        original_reader = recovery_durable_read_renewal_routing_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase P runtime storage outage")

        monkeypatch.setattr(
            recovery_durable_read_renewal_routing_service,
            "_read_verified_candidate",
            unavailable,
        )
        failed = _download(data)
        assert failed.status_code == 503
        monkeypatch.setattr(
            recovery_durable_read_renewal_routing_service,
            "_read_verified_candidate",
            original_reader,
        )
        verified = _download(data)
        assert verified.status_code == 200, verified.text
        rolled_back = _rollback_p(data, lease_id)
        assert rolled_back.status_code == 200, rolled_back.text
        data["renewal_lease_id"] = lease_id

        _, qualifier_headers = _independent_admin(data, slug="degraded")
        requested = _request_q(data)
        assert requested.status_code == 201, requested.text
        qualification = requested.json()["qualification"]
        assert qualification["health_state"] == "degraded"
        assert qualification["storage_unavailable_count"] >= 1
        qualification_id = qualification["id"]

        degraded = _qualify_q(data, qualification_id, headers=qualifier_headers)
        assert degraded.status_code == 200, degraded.text
        assert degraded.json()["outcome"] == "degraded"
        assert degraded.json()["qualification"]["status"] == "degraded"
        assert degraded.json()["qualification"]["routable_authority_created"] is False
