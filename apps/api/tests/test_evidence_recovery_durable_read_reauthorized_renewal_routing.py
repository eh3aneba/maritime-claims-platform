from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents import recovery_durable_read_reauthorized_renewal_routing_service as phase_s_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    EvidenceRecoveryDurableReadReauthorizedRenewalReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_reauthorization import (
    _approve_r,
    _qualified_q,
    _request_r,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    reset_database()


PREPARE_REASON = "Prepare one bounded Phase S reauthorized durable recovery read renewal."
ACTIVATE_REASON = "Independently activate the bounded Phase S recovery read renewal."
ROLLBACK_REASON = "Return the Phase S recovery read route to authoritative local evidence."
RECONCILE_REASON = "Reconcile the bounded Phase S recovery read route after its expiry."


def _approved_r(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_q(monkeypatch, tmp_path, endpoint, slug=slug)
    r_approver_id, r_approver_headers = _independent_admin(data, slug=f"{slug}-r-approver")
    requested = _request_r(data)
    assert requested.status_code == 201, requested.text
    reauthorization_id = requested.json()["authorization"]["id"]
    approved = _approve_r(data, reauthorization_id, headers=r_approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_r_reauthorization_id"] = reauthorization_id
    data["phase_r_approver_id"] = r_approver_id
    data["phase_r_approver_headers"] = r_approver_headers
    return data


def _prepare_s(data, *, headers=None, reason: str = PREPARE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-reauthorizations/{data['phase_r_reauthorization_id']}/reauthorized-renewal-lease",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _activate_s(data, lease_id: str, *, headers, reason: str = ACTIVATE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/activate",
        headers=headers,
        json={"reason": reason},
    )


def _rollback_s(data, lease_id: str, *, headers, reason: str = ROLLBACK_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/rollback",
        headers=headers,
        json={"reason": reason},
    )


def _activate_happy_s(data, *, slug: str):
    prepared = _prepare_s(data)
    assert prepared.status_code == 201, prepared.text
    assert prepared.json()["outcome"] == "prepared"
    lease_id = prepared.json()["lease"]["id"]
    activator_id, activator_headers = _independent_admin(data, slug=f"{slug}-s-activator")
    activated = _activate_s(data, lease_id, headers=activator_headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["outcome"] == "activated"
    data["phase_s_lease_id"] = lease_id
    data["phase_s_activator_id"] = activator_id
    data["phase_s_activator_headers"] = activator_headers
    return lease_id, activator_headers


def test_phase_s_happy_path_is_one_time_reversible_and_read_only(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-s-happy")
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]

        prepared = _prepare_s(data)
        assert prepared.status_code == 201, prepared.text
        assert prepared.json()["outcome"] == "prepared"
        lease = prepared.json()["lease"]
        lease_id = lease["id"]
        assert lease["reauthorization_id"] == data["phase_r_reauthorization_id"]
        assert lease["verified_durable_read_count"] >= 1
        assert lease["integrity_failure_count"] == 0
        assert lease["storage_unavailable_count"] == 0
        assert lease["read_path_switched"] is False
        assert lease["write_path_switched"] is False
        assert lease["document_storage_key_mutated"] is False
        assert lease["authoritative_storage_changed"] is False
        assert lease["destructive_action_performed"] is False

        replay = _prepare_s(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id
        changed = _prepare_s(data, reason="Use different Phase S preparation semantics for the same R authorization.")
        assert changed.status_code == 409

        same_preparer = _activate_s(data, lease_id, headers=data["admin_headers"])
        assert same_preparer.status_code == 409
        r_approver = _activate_s(data, lease_id, headers=data["phase_r_approver_headers"])
        assert r_approver.status_code == 409
        q_qualifier = _activate_s(data, lease_id, headers=data["phase_q_qualifier_headers"])
        assert q_qualifier.status_code == 409
        p_activator = _activate_s(data, lease_id, headers=data["renewal_admin_headers"])
        assert p_activator.status_code == 409

        s_activator_id, s_activator_headers = _independent_admin(data, slug="phase-s-happy-activator")
        activated = _activate_s(data, lease_id, headers=s_activator_headers)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        active = activated.json()
        assert active["route"]["route_authority_kind"] == "durable_reauthorized_renewal"
        assert active["route"]["active_durable_reauthorized_renewal_lease_id"] == lease_id
        assert active["lease"]["route_expires_at"] is not None
        assert active["lease"]["read_path_switched"] is True
        assert active["lease"]["write_path_switched"] is False

        download = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert download.status_code == 200, download.text
        assert download.content == local_before
        assert download.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica-durable-reauthorized-renewal"

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200, manager_read.text
        manager_mutation = _prepare_s(data, headers=data["manager_headers"])
        assert manager_mutation.status_code == 403

        rolled_back = _rollback_s(data, lease_id, headers=s_activator_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["route"]["route_authority_kind"] == "local"
        assert rolled_back.json()["route"]["active_durable_reauthorized_renewal_lease_id"] is None

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["prepared", "activated", "rolled_back"]

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDurableReadReauthorizedRenewalLease, UUID(lease_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert stored is not None and document is not None
            assert stored.status == "rolled_back"
            assert stored.activated_by_id == s_activator_id
            assert document.storage_key == data["storage_key"]
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_durable_renewal_lease_id is None
            assert route.active_durable_reauthorized_renewal_lease_id is None
            audit_rows = db.query(AuditLog).filter(
                AuditLog.entity_id == data["document_id"],
                AuditLog.action == "DOWNLOAD_DOCUMENT",
            ).all()
            s_reads = [
                item for item in audit_rows
                if (item.new_values or {}).get("read_source")
                == "recovery-replica-durable-reauthorized-renewal"
            ]
            assert s_reads
            assert (s_reads[-1].new_values or {}).get(
                "recovery_durable_reauthorized_renewal_lease_id"
            ) == lease_id
            rendered = " ".join(str(item.new_values) for item in audit_rows)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered

        assert data["local_path"].read_bytes() == local_before
        assert _RecoveryRestoreS3Handler.objects[data["remote_key"]] == remote_before

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(
            slug="phase-s-other", storage_root=tmp_path / "other"
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_s_activation_outage_is_retryable_and_route_drift_invalidates(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-s-activation-outage")
        prepared = _prepare_s(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-s-outage-activator")
        original_reader = phase_s_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase S storage outage")

        monkeypatch.setattr(phase_s_service, "_read_verified_candidate", unavailable)
        outage = _activate_s(data, lease_id, headers=activator_headers)
        assert outage.status_code == 503
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadReauthorizedRenewalLease, UUID(lease_id))
            assert lease is not None and lease.status == "prepared"
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert route.route_authority_kind == "local"
        monkeypatch.setattr(phase_s_service, "_read_verified_candidate", original_reader)
        activated = _activate_s(data, lease_id, headers=activator_headers)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        assert _rollback_s(data, lease_id, headers=activator_headers).status_code == 200


def test_phase_s_route_drift_before_activation_invalidates(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-s-drift")
        prepared = _prepare_s(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-s-drift-activator")
        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()
        invalidated = _activate_s(data, lease_id, headers=activator_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["lease"]["status"] == "invalidated"
        assert invalidated.json()["route"]["route_authority_kind"] == "local"


def test_phase_s_active_tamper_and_outage_fail_closed_without_local_fallback(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-s-read-failclosed")
        lease_id, activator_headers = _activate_happy_s(data, slug="phase-s-read-failclosed")
        original_remote = _RecoveryRestoreS3Handler.objects[data["remote_key"]]

        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (
            b"tampered-phase-s-payload",
            original_remote[1],
        )
        tampered = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert tampered.status_code == 409
        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = original_remote

        original_reader = phase_s_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase S active-read outage")

        monkeypatch.setattr(phase_s_service, "_read_verified_candidate", unavailable)
        outage = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert outage.status_code == 503
        monkeypatch.setattr(phase_s_service, "_read_verified_candidate", original_reader)

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert route.route_authority_kind == "durable_reauthorized_renewal"
            failures = db.query(AuditLog).filter(
                AuditLog.entity_id == data["document_id"],
                AuditLog.action == "DOWNLOAD_DOCUMENT_RECOVERY_FAILED",
            ).all()
            s_failures = [
                item for item in failures
                if (item.new_values or {}).get("recovery_durable_reauthorized_renewal_lease_id") == lease_id
            ]
            assert {item.new_values.get("failure_class") for item in s_failures} >= {
                "integrity_or_lineage", "storage_unavailable"
            }
            rendered = " ".join(str(item.new_values) for item in s_failures)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered
        assert _rollback_s(data, lease_id, headers=activator_headers).status_code == 200


def test_phase_s_activation_and_route_expiry_fail_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-s-activation-expiry")
        prepared = _prepare_s(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-s-expired-activator")
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadReauthorizedRenewalLease, UUID(lease_id))
            assert lease is not None
            lease.activation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired = _activate_s(data, lease_id, headers=activator_headers)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["route"]["route_authority_kind"] == "local"


def test_phase_s_active_route_expiry_reconciles_to_local(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-s-route-expiry")
        lease_id, activator_headers = _activate_happy_s(data, slug="phase-s-route-expiry")
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadReauthorizedRenewalLease, UUID(lease_id))
            assert lease is not None
            lease.route_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert expired_read.status_code == 409
        reconciled = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/reconcile",
            headers=activator_headers,
            json={"reason": RECONCILE_REASON},
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["outcome"] == "expired"
        assert reconciled.json()["route"]["route_authority_kind"] == "local"
        assert reconciled.json()["route"]["active_durable_reauthorized_renewal_lease_id"] is None
        with TestingSessionLocal() as db:
            receipts = db.query(EvidenceRecoveryDurableReadReauthorizedRenewalReceipt).filter_by(
                reauthorized_renewal_lease_id=UUID(lease_id)
            ).all()
            assert [item.phase for item in receipts] == ["prepared", "activated", "expired"]
