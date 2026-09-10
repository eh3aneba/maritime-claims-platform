import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents import recovery_durable_read_routing_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_routing_models import (
    EvidenceRecoveryDurableReadPromotionLease,
    EvidenceRecoveryDurableReadPromotionReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_promotion_authorization import (
    _approve_l,
    _qualified_k_real_j_cycles,
    _request_l,
)
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    reset_database()


PREPARE_REASON = "Prepare the bounded durable recovery read routing lease after Phase L approval."
ACTIVATE_REASON = "Activate the bounded durable recovery read route under independent Admin control."
ROLLBACK_REASON = "Roll the durable recovery read route back to the intact local evidence source."
RECONCILE_REASON = "Reconcile the bounded durable recovery read route against its operational expiry."


def _approved_l(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_k_real_j_cycles(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_l(data)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approved = _approve_l(data, authorization_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["authorization_id"] = authorization_id
    data["manager_headers"] = _headers(data["manager_id"])
    return data


def _prepare_m(data, *, headers=None, reason: str = PREPARE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-authorizations/{data['authorization_id']}/durable-read-routing-lease",
        headers=headers or data["j_activator_headers"],
        json={"reason": reason},
    )


def _activate_m(data, lease_id: str, *, headers=None, reason: str = ACTIVATE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-leases/{lease_id}/activate",
        headers=headers or data["k_qualifier_headers"],
        json={"reason": reason},
    )


def _rollback_m(data, lease_id: str, *, headers=None, reason: str = ROLLBACK_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-leases/{lease_id}/rollback",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _reconcile_m(data, lease_id: str, *, headers=None):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-leases/{lease_id}/reconcile",
        headers=headers or data["admin_headers"],
        json={"reason": RECONCILE_REASON},
    )


def _download(data, *, headers=None):
    return client.get(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
        headers=headers or data["manager_headers"],
    )


def test_durable_route_reads_verified_replica_and_rolls_back_without_changing_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-route-happy")
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]

        before = _download(data)
        assert before.status_code == 200, before.text
        assert before.content == local_before
        assert before.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        prepared = _prepare_m(data)
        assert prepared.status_code == 201, prepared.text
        assert prepared.json()["outcome"] == "prepared"
        lease_id = prepared.json()["lease"]["id"]
        assert prepared.json()["route"]["route_authority_kind"] == "local"
        assert prepared.json()["lease"]["route_expires_at"] is None

        prepare_replay = _prepare_m(data)
        assert prepare_replay.status_code == 201, prepare_replay.text
        assert prepare_replay.json()["outcome"] == "unchanged"
        assert prepare_replay.json()["lease"]["id"] == lease_id

        same_preparer = _activate_m(data, lease_id, headers=data["j_activator_headers"])
        assert same_preparer.status_code == 409
        phase_l_approver = _activate_m(data, lease_id, headers=data["admin_headers"])
        assert phase_l_approver.status_code == 409

        activated = _activate_m(data, lease_id)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        assert activated.json()["lease"]["durable_read_route_created"] is True
        assert activated.json()["lease"]["read_path_switched"] is True
        assert activated.json()["lease"]["write_path_switched"] is False
        assert activated.json()["lease"]["authoritative_storage_changed"] is False
        assert activated.json()["route"]["route_class"] == "recovery_replica"
        assert activated.json()["route"]["route_authority_kind"] == "durable_promotion"
        assert activated.json()["route"]["active_lease_id"] is None
        assert activated.json()["route"]["active_durable_lease_id"] == lease_id

        activation_replay = _activate_m(data, lease_id)
        assert activation_replay.status_code == 200, activation_replay.text
        assert activation_replay.json()["outcome"] == "unchanged"

        during = _download(data)
        assert during.status_code == 200, during.text
        assert during.content == local_before
        assert during.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica-durable"

        healthy = _reconcile_m(data, lease_id)
        assert healthy.status_code == 200, healthy.text
        assert healthy.json()["outcome"] == "unchanged"
        assert healthy.json()["route"]["route_authority_kind"] == "durable_promotion"

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadPromotionLease, UUID(lease_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"],
                document_id=data["document_id"],
            ).one()
            assert lease is not None and document is not None
            assert lease.route_expires_at is not None
            assert lease.route_expires_at <= lease.activated_at + timedelta(hours=24)
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert route.durable_authority_active is True
            assert route.active_durable_lease_id == lease.id
            assert route.active_lease_id is None
            audit = db.query(AuditLog).filter(AuditLog.action == "DOWNLOAD_DOCUMENT").order_by(AuditLog.created_at.desc()).first()
            assert audit is not None
            assert audit.new_values["read_source"] == "recovery-replica-durable"
            assert audit.new_values["read_path_switched"] is True
            assert audit.new_values["write_path_switched"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            rendered = str(audit.new_values)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered
            lease.route_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        rollback = _rollback_m(data, lease_id)
        assert rollback.status_code == 200, rollback.text
        assert rollback.json()["outcome"] == "rolled_back"
        assert rollback.json()["route"]["route_class"] == "local_source"
        assert rollback.json()["route"]["route_authority_kind"] == "local"
        assert rollback.json()["route"]["active_durable_lease_id"] is None

        rollback_replay = _rollback_m(data, lease_id)
        assert rollback_replay.status_code == 200, rollback_replay.text
        assert rollback_replay.json()["outcome"] == "unchanged"

        after = _download(data)
        assert after.status_code == 200, after.text
        assert after.content == local_before
        assert after.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        with TestingSessionLocal() as db:
            receipts = db.query(EvidenceRecoveryDurableReadPromotionReceipt).filter_by(
                durable_lease_id=UUID(lease_id)
            ).all()
            assert [item.phase for item in receipts] == ["prepared", "activated", "rolled_back"]
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert document is not None
            assert document.storage_key == data["storage_key"]
            assert route.route_class == "local_source"
            assert route.durable_authority_active is False
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_replica_id is None

        assert data["local_path"].read_bytes() == local_before
        assert _RecoveryRestoreS3Handler.objects[data["remote_key"]] == remote_before


def test_active_durable_route_tamper_and_storage_outage_fail_closed_without_local_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-route-fail-closed")
        prepared = _prepare_m(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_m(data, lease_id)
        assert activated.status_code == 200, activated.text

        original_payload, original_digest = _RecoveryRestoreS3Handler.objects[data["remote_key"]]
        tampered = bytes((byte ^ 0x01) for byte in original_payload)
        assert len(tampered) == len(original_payload)
        assert hashlib.sha256(tampered).hexdigest() != original_digest
        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (tampered, original_digest)

        failed = _download(data)
        assert failed.status_code == 409
        assert failed.content != data["local_path"].read_bytes()

        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (original_payload, original_digest)

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated recovery object-store outage")

        monkeypatch.setattr(recovery_durable_read_routing_service, "_read_verified_candidate", unavailable)
        outage = _download(data)
        assert outage.status_code == 503

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadPromotionLease, UUID(lease_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert lease is not None
            assert lease.status == "activated"
            assert route.route_class == "recovery_replica"
            assert route.durable_authority_active is True
            assert route.active_durable_lease_id == lease.id
            assert data["local_path"].exists()


def test_expired_durable_route_reconciles_atomically_to_local_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-route-expiry")
        prepared = _prepare_m(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_m(data, lease_id)
        assert activated.status_code == 200, activated.text

        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryDurableReadPromotionLease, UUID(lease_id))
            assert lease is not None
            lease.route_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        expired_read = _download(data)
        assert expired_read.status_code == 409

        reconciled = _reconcile_m(data, lease_id)
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["outcome"] == "expired"
        assert reconciled.json()["lease"]["status"] == "expired"
        assert reconciled.json()["route"]["route_class"] == "local_source"
        assert reconciled.json()["route"]["route_authority_kind"] == "local"

        replay = _reconcile_m(data, lease_id)
        assert replay.status_code == 200, replay.text
        assert replay.json()["outcome"] == "unchanged"

        after = _download(data)
        assert after.status_code == 200, after.text
        assert after.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        with TestingSessionLocal() as db:
            receipts = db.query(EvidenceRecoveryDurableReadPromotionReceipt).filter_by(
                durable_lease_id=UUID(lease_id)
            ).all()
            assert [item.phase for item in receipts] == ["prepared", "activated", "expired"]
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert route.durable_authority_active is False
            assert route.active_durable_lease_id is None
            assert route.active_replica_id is None


def test_durable_route_is_tenant_scoped_and_claims_manager_is_read_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-route-tenant")
        prepared = _prepare_m(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-leases/{lease_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200
        manager_receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert manager_receipts.status_code == 200
        assert [item["phase"] for item in manager_receipts.json()] == ["prepared"]
        manager_mutation = _activate_m(data, lease_id, headers=data["manager_headers"])
        assert manager_mutation.status_code == 403

        _, other_admin_id, _, other_claim_id, other_document_id, _, _ = _seed_tenant(
            slug="durable-route-other",
            storage_root=tmp_path / "other",
        )
        other_headers = _headers(other_admin_id)
        wrong_tenant_lease = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-leases/{lease_id}",
            headers=other_headers,
        )
        assert wrong_tenant_lease.status_code == 404
        wrong_tenant_receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-leases/{lease_id}/receipts",
            headers=other_headers,
        )
        assert wrong_tenant_receipts.status_code == 404
        wrong_claim_download = client.get(
            f"/api/v1/claims/{other_claim_id}/documents/{other_document_id}/download",
            headers=data["manager_headers"],
        )
        assert wrong_claim_download.status_code == 404
