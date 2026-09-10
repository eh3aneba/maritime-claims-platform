import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents import recovery_durable_read_renewal_routing_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_renewal_routing_models import (
    EvidenceRecoveryDurableReadRenewalLease,
    EvidenceRecoveryDurableReadRenewalReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_authorization import (
    _approve_o,
    _qualified_n,
    _request_o,
)
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    reset_database()


PREPARE_REASON = "Prepare one bounded durable recovery read renewal lease from the approved Phase O envelope."
ACTIVATE_REASON = "Activate the independently controlled durable recovery read renewal route."
ROLLBACK_REASON = "Return the durable recovery read renewal route to the authoritative local source."
RECONCILE_REASON = "Reconcile the durable recovery read renewal lease against its bounded operational window."


def _approved_o(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_n(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_o(data)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approved = _approve_o(data, authorization_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"

    with TestingSessionLocal() as db:
        renewal_admin = User(
            organization_id=data["org_id"],
            email=f"renewal-{slug}@example.com",
            full_name=f"Renewal Admin {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(renewal_admin)
        db.commit()
        renewal_admin_id = renewal_admin.id

    data["renewal_authorization_id"] = authorization_id
    data["renewal_admin_id"] = renewal_admin_id
    data["renewal_admin_headers"] = _headers(renewal_admin_id)
    return data


def _prepare_p(data, *, headers=None, reason: str = PREPARE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-authorizations/{data['renewal_authorization_id']}/durable-read-renewal-lease",
        headers=headers or data["j_activator_headers"],
        json={"reason": reason},
    )


def _activate_p(data, lease_id: str, *, headers=None, reason: str = ACTIVATE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-leases/{lease_id}/activate",
        headers=headers or data["renewal_admin_headers"],
        json={"reason": reason},
    )


def _rollback_p(data, lease_id: str, *, headers=None, reason: str = ROLLBACK_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-leases/{lease_id}/rollback",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _reconcile_p(data, lease_id: str, *, headers=None, reason: str = RECONCILE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-leases/{lease_id}/reconcile",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _download(data, *, headers=None):
    return client.get(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
        headers=headers or data["manager_headers"],
    )


def test_approved_phase_o_executes_independent_bounded_renewal_and_rolls_back_cleanly(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_o(monkeypatch, tmp_path, endpoint, slug="renewal-route-happy")
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]

        before = _download(data)
        assert before.status_code == 200, before.text
        assert before.content == local_before
        assert before.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        prepared = _prepare_p(data)
        assert prepared.status_code == 201, prepared.text
        assert prepared.json()["outcome"] == "prepared"
        lease_id = prepared.json()["lease"]["id"]
        assert prepared.json()["route"]["route_authority_kind"] == "local"
        assert prepared.json()["route"]["active_durable_renewal_lease_id"] is None
        assert prepared.json()["lease"]["verified_durable_read_count"] >= 1
        assert prepared.json()["lease"]["integrity_failure_count"] == 0
        assert prepared.json()["lease"]["storage_unavailable_count"] == 0

        replay = _prepare_p(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id

        same_preparer = _activate_p(data, lease_id, headers=data["j_activator_headers"])
        assert same_preparer.status_code == 409
        phase_o_approver = _activate_p(data, lease_id, headers=data["admin_headers"])
        assert phase_o_approver.status_code == 409
        prior_m_activator = _activate_p(data, lease_id, headers=data["k_qualifier_headers"])
        assert prior_m_activator.status_code == 409

        activated = _activate_p(data, lease_id)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        assert activated.json()["lease"]["status"] == "activated"
        assert activated.json()["lease"]["routable_authority_created"] is True
        assert activated.json()["lease"]["durable_read_route_created"] is True
        assert activated.json()["lease"]["read_path_switched"] is True
        assert activated.json()["lease"]["write_path_switched"] is False
        assert activated.json()["lease"]["authoritative_storage_changed"] is False
        assert activated.json()["route"]["route_class"] == "recovery_replica"
        assert activated.json()["route"]["route_authority_kind"] == "durable_renewal"
        assert activated.json()["route"]["active_durable_lease_id"] is None
        assert activated.json()["route"]["active_durable_renewal_lease_id"] == lease_id

        activation_replay = _activate_p(data, lease_id)
        assert activation_replay.status_code == 200, activation_replay.text
        assert activation_replay.json()["outcome"] == "unchanged"

        during = _download(data)
        assert during.status_code == 200, during.text
        assert during.content == local_before
        assert during.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica-durable-renewal"

        healthy = _reconcile_p(data, lease_id)
        assert healthy.status_code == 200, healthy.text
        assert healthy.json()["outcome"] == "unchanged"
        assert healthy.json()["route"]["route_authority_kind"] == "durable_renewal"

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-leases/{lease_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200, manager_read.text
        manager_receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert manager_receipts.status_code == 200, manager_receipts.text
        assert [item["phase"] for item in manager_receipts.json()] == ["prepared", "activated"]
        manager_mutation = _prepare_p(data, headers=data["manager_headers"])
        assert manager_mutation.status_code == 403

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadRenewalLease, UUID(lease_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert lease is not None and document is not None
            assert lease.route_expires_at is not None
            assert lease.route_expires_at <= lease.activated_at + timedelta(hours=24)
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert route.route_authority_kind == "durable_renewal"
            assert route.active_durable_lease_id is None
            assert route.active_durable_renewal_lease_id == lease.id
            audits = db.query(AuditLog).filter(
                AuditLog.action == "DOWNLOAD_DOCUMENT"
            ).all()
            audit = next(
                item for item in audits
                if item.new_values
                and item.new_values.get("read_source") == "recovery-replica-durable-renewal"
            )
            assert audit.new_values["recovery_durable_renewal_lease_id"] == lease_id
            rendered = str(audit.new_values)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered
            assert audit.new_values["write_path_switched"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            assert audit.new_values["destructive_action_performed"] is False

        rolled_back = _rollback_p(data, lease_id)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["route"]["route_class"] == "local_source"
        assert rolled_back.json()["route"]["route_authority_kind"] == "local"
        assert rolled_back.json()["route"]["active_durable_renewal_lease_id"] is None

        rollback_replay = _rollback_p(data, lease_id)
        assert rollback_replay.status_code == 200, rollback_replay.text
        assert rollback_replay.json()["outcome"] == "unchanged"

        after = _download(data)
        assert after.status_code == 200, after.text
        assert after.content == local_before
        assert after.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        with TestingSessionLocal() as db:
            receipts = db.query(EvidenceRecoveryDurableReadRenewalReceipt).filter_by(
                renewal_lease_id=UUID(lease_id)
            ).all()
            assert [item.phase for item in receipts] == ["prepared", "activated", "rolled_back"]
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_durable_renewal_lease_id is None
            assert route.active_replica_id is None

        assert data["local_path"].read_bytes() == local_before
        assert _RecoveryRestoreS3Handler.objects[data["remote_key"]] == remote_before


def test_active_renewal_tamper_and_storage_outage_fail_closed_without_local_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_o(monkeypatch, tmp_path, endpoint, slug="renewal-route-fail-closed")
        prepared = _prepare_p(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_p(data, lease_id)
        assert activated.status_code == 200, activated.text

        original_payload, original_digest = _RecoveryRestoreS3Handler.objects[data["remote_key"]]
        tampered = bytes((value ^ 0x01) for value in original_payload)
        assert hashlib.sha256(tampered).hexdigest() != original_digest
        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (tampered, original_digest)

        failed = _download(data)
        assert failed.status_code == 409
        assert failed.content != data["local_path"].read_bytes()

        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (original_payload, original_digest)

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable(
                "simulated Phase P recovery object-store outage"
            )

        monkeypatch.setattr(
            recovery_durable_read_renewal_routing_service,
            "_read_verified_candidate",
            unavailable,
        )
        outage = _download(data)
        assert outage.status_code == 503
        assert outage.content != data["local_path"].read_bytes()

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadRenewalLease, UUID(lease_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert lease is not None
            assert lease.status == "activated"
            assert route.route_authority_kind == "durable_renewal"
            assert route.active_durable_renewal_lease_id == lease.id
            failures = db.query(AuditLog).filter(
                AuditLog.action == "DOWNLOAD_DOCUMENT_RECOVERY_FAILED"
            ).all()
            renewal_failures = [
                item for item in failures
                if item.new_values
                and item.new_values.get("recovery_durable_renewal_lease_id") == lease_id
            ]
            assert {item.new_values["failure_class"] for item in renewal_failures} == {
                "integrity_or_lineage",
                "storage_unavailable",
            }
            rendered = " ".join(str(item.new_values) for item in renewal_failures)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered
            assert "simulated Phase P" not in rendered


def test_activation_outage_is_retryable_and_route_drift_invalidates_prepared_renewal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_o(monkeypatch, tmp_path, endpoint, slug="renewal-route-preflight")
        prepared = _prepare_p(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]

        original_reader = recovery_durable_read_renewal_routing_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable(
                "simulated Phase P activation storage outage"
            )

        monkeypatch.setattr(
            recovery_durable_read_renewal_routing_service,
            "_read_verified_candidate",
            unavailable,
        )
        outage = _activate_p(data, lease_id)
        assert outage.status_code == 503

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadRenewalLease, UUID(lease_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert lease is not None
            assert lease.status == "prepared"
            assert db.query(EvidenceRecoveryDurableReadRenewalReceipt).filter_by(
                renewal_lease_id=UUID(lease_id)
            ).count() == 1
            assert route.route_authority_kind == "local"
            assert route.active_durable_renewal_lease_id is None

        monkeypatch.setattr(
            recovery_durable_read_renewal_routing_service,
            "_read_verified_candidate",
            original_reader,
        )
        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()

        invalidated = _activate_p(data, lease_id)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["lease"]["status"] == "invalidated"
        assert invalidated.json()["lease"]["read_path_switched"] is False
        assert invalidated.json()["route"]["route_authority_kind"] == "local"


def test_renewal_activation_expiry_and_tenant_scope_fail_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_o(monkeypatch, tmp_path, endpoint, slug="renewal-route-expiry")
        prepared = _prepare_p(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadRenewalLease, UUID(lease_id))
            assert lease is not None
            lease.activation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        expired = _activate_p(data, lease_id)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["lease"]["status"] == "expired"
        assert expired.json()["lease"]["read_path_switched"] is False
        assert expired.json()["route"]["route_authority_kind"] == "local"

        _, other_admin_id, _, other_claim_id, other_document_id, _, _ = _seed_tenant(
            slug="renewal-route-other",
            storage_root=tmp_path / "other",
        )
        other_headers = _headers(other_admin_id)
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-leases/{lease_id}",
            headers=other_headers,
        )
        assert cross_tenant.status_code == 404
        owner_into_other_claim = client.get(
            f"/api/v1/claims/{other_claim_id}/documents/{other_document_id}/recovery-durable-read-renewal-leases/{lease_id}",
            headers=data["admin_headers"],
        )
        assert owner_into_other_claim.status_code == 404
