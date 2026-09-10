from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_routable_read_cutover_models import (
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathCutoverReceipt,
    EvidenceRecoveryReadPathRoute,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_read_path_cutover_authorization import (
    _approve_authorization,
    _request_authorization,
    _rolled_back_execution_chain,
)
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
)


def setup_function() -> None:
    reset_database()


def _approved_read_path_authorization(
    monkeypatch,
    tmp_path: Path,
    endpoint: str,
    *,
    slug: str,
):
    (
        org_id,
        admin_id,
        approver_id,
        third_admin_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        admin_headers,
        approver_headers,
        third_headers,
        shadow_id,
        execution_lease_id,
    ) = _rolled_back_execution_chain(
        monkeypatch,
        tmp_path,
        endpoint,
        slug=slug,
    )
    requested = _request_authorization(
        claim_id,
        document_id,
        execution_lease_id,
        admin_headers,
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approved = _approve_authorization(
        claim_id,
        document_id,
        authorization_id,
        approver_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    return (
        org_id,
        admin_id,
        approver_id,
        third_admin_id,
        manager_id,
        claim_id,
        document_id,
        storage_key,
        local_path,
        replicated,
        admin_headers,
        approver_headers,
        third_headers,
        shadow_id,
        authorization_id,
    )


def _prepare_cutover(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}/cutover-lease",
        headers=headers,
        json={"reason": "Prepare the bounded reversible production recovery read-path cutover."},
    )


def _activate_cutover(
    claim_id: UUID,
    document_id: UUID,
    lease_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}/activate",
        headers=headers,
        json={"reason": "Independently activate the bounded recovery read route for this document."},
    )


def _rollback_cutover(
    claim_id: UUID,
    document_id: UUID,
    lease_id: str,
    headers: dict[str, str],
):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}/rollback",
        headers=headers,
        json={"reason": "Restore the document read route to the retained authoritative local source."},
    )


def _download(claim_id: UUID, document_id: UUID, headers: dict[str, str]):
    return client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/download",
        headers=headers,
    )


def test_routable_read_cutover_downloads_local_then_verified_recovery_then_local(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            manager_id,
            claim_id,
            document_id,
            storage_key,
            local_path,
            replicated,
            admin_headers,
            _approver_headers,
            third_headers,
            _shadow_id,
            authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="routable-read-happy",
        )
        local_bytes = local_path.read_bytes()
        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        remote_before = _RecoveryRestoreS3Handler.objects[remote_key]
        assert remote_before == local_bytes

        before = _download(claim_id, document_id, admin_headers)
        assert before.status_code == 200, before.text
        assert before.content == local_bytes
        assert before.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        prepared = _prepare_cutover(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        assert prepared.status_code == 201, prepared.text
        assert prepared.json()["outcome"] == "prepared"
        lease = prepared.json()["lease"]
        lease_id = lease["id"]
        route = prepared.json()["route"]
        assert route["route_class"] == "local_source"
        assert route["read_path_switched"] is False
        assert lease["write_path_switched"] is False
        assert lease["document_storage_key_mutated"] is False
        assert lease["authoritative_storage_changed"] is False
        assert lease["destructive_action_performed"] is False

        prepared_download = _download(claim_id, document_id, admin_headers)
        assert prepared_download.status_code == 200
        assert prepared_download.content == local_bytes
        assert prepared_download.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        same_preparer = _activate_cutover(
            claim_id,
            document_id,
            lease_id,
            admin_headers,
        )
        assert same_preparer.status_code == 409

        activated = _activate_cutover(
            claim_id,
            document_id,
            lease_id,
            third_headers,
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        assert activated.json()["lease"]["status"] == "activated"
        assert activated.json()["lease"]["read_path_switched"] is True
        assert activated.json()["lease"]["routable_authority_created"] is True
        assert activated.json()["route"]["route_class"] == "recovery_replica"
        assert activated.json()["route"]["read_path_switched"] is True

        during = _download(claim_id, document_id, admin_headers)
        assert during.status_code == 200, during.text
        assert during.content == remote_before
        assert during.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica"

        manager_route = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-route",
            headers=_headers(manager_id),
        )
        assert manager_route.status_code == 200
        assert manager_route.json()["route_class"] == "recovery_replica"

        rolled_back = _rollback_cutover(
            claim_id,
            document_id,
            lease_id,
            admin_headers,
        )
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["lease"]["status"] == "rolled_back"
        assert rolled_back.json()["lease"]["read_path_switched"] is False
        assert rolled_back.json()["lease"]["routable_authority_created"] is False
        assert rolled_back.json()["route"]["route_class"] == "local_source"
        assert rolled_back.json()["route"]["active_lease_id"] is None
        assert rolled_back.json()["route"]["active_replica_id"] is None

        after = _download(claim_id, document_id, admin_headers)
        assert after.status_code == 200, after.text
        assert after.content == local_bytes
        assert after.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        receipts = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}/receipts",
            headers=_headers(manager_id),
        )
        assert receipts.status_code == 200
        assert [item["phase"] for item in receipts.json()] == [
            "prepared",
            "activated",
            "rolled_back",
        ]
        assert receipts.json()[1]["read_path_switched"] is True
        assert receipts.json()[1]["routable_authority_created"] is True
        assert receipts.json()[2]["read_path_switched"] is False

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            stored_lease = db.get(EvidenceRecoveryReadPathCutoverLease, UUID(lease_id))
            stored_route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                document_id=document_id
            ).one()
            assert document is not None and stored_lease is not None
            assert document.storage_key == storage_key
            assert document.deleted_at is None
            assert local_path.exists()
            assert stored_route.route_class == "local_source"
            assert stored_route.active_lease_id is None
            assert stored_route.active_replica_id is None
            assert db.query(EvidenceRecoveryReadPathCutoverReceipt).count() == 3

            activation_audit = (
                db.query(AuditLog)
                .filter(AuditLog.action == "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_ACTIVATED")
                .one()
            )
            rendered = str(activation_audit.new_values)
            assert storage_key not in rendered
            assert remote_key not in rendered
            assert activation_audit.new_values["read_path_switched"] is True
            assert activation_audit.new_values["write_path_switched"] is False
            assert activation_audit.new_values["document_storage_key_mutated"] is False
            assert activation_audit.new_values["authoritative_storage_changed"] is False
            assert activation_audit.new_values["destructive_action_performed"] is False

            recovery_download_audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.action == "DOWNLOAD_DOCUMENT",
                    AuditLog.new_values["read_source"].as_string()
                    == "recovery-replica",
                )
                .one()
            )
            assert recovery_download_audit.new_values["write_path_switched"] is False
            assert recovery_download_audit.new_values["authoritative_storage_changed"] is False

        assert _RecoveryRestoreS3Handler.objects[remote_key] == remote_before


def test_authorization_approver_cannot_activate_routable_read_cutover(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            approver_headers,
            _third_headers,
            _shadow_id,
            authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="routable-read-approver-split",
        )
        prepared = _prepare_cutover(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        assert prepared.status_code == 201
        blocked = _activate_cutover(
            claim_id,
            document_id,
            prepared.json()["lease"]["id"],
            approver_headers,
        )
        assert blocked.status_code == 409


def test_routable_read_cutover_expiry_fails_closed_before_activation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            _approver_headers,
            third_headers,
            _shadow_id,
            authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="routable-read-expiry",
        )
        prepared = _prepare_cutover(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        assert prepared.status_code == 201
        lease_id = UUID(prepared.json()["lease"]["id"])
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryReadPathCutoverLease, lease_id)
            assert lease is not None
            lease.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        expired = _activate_cutover(
            claim_id,
            document_id,
            str(lease_id),
            third_headers,
        )
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["route"]["route_class"] == "local_source"


def test_active_routable_read_expiry_blocks_download_but_rollback_restores_local(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            local_path,
            _replicated,
            admin_headers,
            _approver_headers,
            third_headers,
            _shadow_id,
            authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="routable-read-active-expiry",
        )
        local_bytes = local_path.read_bytes()
        prepared = _prepare_cutover(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_cutover(
            claim_id,
            document_id,
            lease_id,
            third_headers,
        )
        assert activated.status_code == 200
        with TestingSessionLocal() as db:
            lease = db.get(EvidenceRecoveryReadPathCutoverLease, UUID(lease_id))
            assert lease is not None
            lease.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        blocked = _download(claim_id, document_id, admin_headers)
        assert blocked.status_code == 409
        assert "rollback" in blocked.json()["detail"].lower()

        rolled_back = _rollback_cutover(
            claim_id,
            document_id,
            lease_id,
            admin_headers,
        )
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        restored = _download(claim_id, document_id, admin_headers)
        assert restored.status_code == 200
        assert restored.content == local_bytes
        assert restored.headers["X-MCRI-Evidence-Read-Source"] == "local-source"


def test_remote_tamper_blocks_active_recovery_download_and_rollback_remains_available(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            _manager_id,
            claim_id,
            document_id,
            _storage_key,
            local_path,
            replicated,
            admin_headers,
            _approver_headers,
            third_headers,
            _shadow_id,
            authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="routable-read-remote-tamper",
        )
        local_bytes = local_path.read_bytes()
        prepared = _prepare_cutover(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_cutover(
            claim_id,
            document_id,
            lease_id,
            third_headers,
        )
        assert activated.status_code == 200

        remote_key = replicated.json()["replica"]["recovery_storage_key"]
        _RecoveryRestoreS3Handler.objects[remote_key] = b"tampered remote recovery evidence"
        blocked = _download(claim_id, document_id, admin_headers)
        assert blocked.status_code == 409

        rolled_back = _rollback_cutover(
            claim_id,
            document_id,
            lease_id,
            admin_headers,
        )
        assert rolled_back.status_code == 200
        restored = _download(claim_id, document_id, admin_headers)
        assert restored.status_code == 200
        assert restored.content == local_bytes
        assert restored.headers["X-MCRI-Evidence-Read-Source"] == "local-source"


def test_claims_manager_can_read_but_cannot_mutate_routable_read_cutover(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        (
            _org_id,
            _admin_id,
            _approver_id,
            _third_admin_id,
            manager_id,
            claim_id,
            document_id,
            _storage_key,
            _local_path,
            _replicated,
            admin_headers,
            _approver_headers,
            _third_headers,
            _shadow_id,
            authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="routable-read-rbac",
        )
        prepared = _prepare_cutover(
            claim_id,
            document_id,
            authorization_id,
            admin_headers,
        )
        assert prepared.status_code == 201
        lease_id = prepared.json()["lease"]["id"]
        manager_headers = _headers(manager_id)

        lease_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}",
            headers=manager_headers,
        )
        route_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-read-path-route",
            headers=manager_headers,
        )
        assert lease_read.status_code == 200
        assert route_read.status_code == 200

        forbidden = _activate_cutover(
            claim_id,
            document_id,
            lease_id,
            manager_headers,
        )
        assert forbidden.status_code == 403
