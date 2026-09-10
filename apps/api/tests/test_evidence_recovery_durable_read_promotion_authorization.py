import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.modules.audit.models import AuditLog
from app.modules.documents import recovery_routable_read_cutover_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_promotion_models import (
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt,
)
from app.modules.documents.recovery_replication_models import EvidenceRecoveryReplica
from app.modules.documents.recovery_routable_read_cutover_models import (
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathRoute,
)
from app.modules.documents.recovery_routable_read_cutover_service import (
    RoutableReadCutoverSnapshot,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)
from tests.test_evidence_recovery_routable_read_cutover import (
    _activate_cutover,
    _approved_read_path_authorization,
    _prepare_cutover,
    _rollback_cutover,
)


def setup_function() -> None:
    reset_database()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _qualified_k_real_j_cycles(
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
        _replicated,
        admin_headers,
        approver_headers,
        third_headers,
        _shadow_id,
        first_authorization_id,
    ) = _approved_read_path_authorization(
        monkeypatch,
        tmp_path,
        endpoint,
        slug=slug,
    )

    first_prepared = _prepare_cutover(
        claim_id,
        document_id,
        first_authorization_id,
        admin_headers,
    )
    assert first_prepared.status_code == 201, first_prepared.text
    first_lease_id = first_prepared.json()["lease"]["id"]
    first_activated = _activate_cutover(
        claim_id,
        document_id,
        first_lease_id,
        third_headers,
    )
    assert first_activated.status_code == 200, first_activated.text
    first_rolled_back = _rollback_cutover(
        claim_id,
        document_id,
        first_lease_id,
        admin_headers,
    )
    assert first_rolled_back.status_code == 200, first_rolled_back.text

    with TestingSessionLocal() as db:
        first = db.get(EvidenceRecoveryReadPathCutoverLease, UUID(first_lease_id))
        assert first is not None
        assert first.authorization_approved_by_id is not None
        second_authorization_id = uuid4()
        second_snapshot = RoutableReadCutoverSnapshot(
            authorization_id=second_authorization_id,
            authorization_approval_receipt_id=uuid4(),
            replica_id=first.replica_id,
            authorization_hash=_digest(f"{slug}-second-j-authorization"),
            authorization_request_snapshot_hash=_digest(f"{slug}-second-j-auth-request"),
            authorization_approval_receipt_hash=_digest(f"{slug}-second-j-auth-receipt"),
            execution_transition_proof_hash=_digest(f"{slug}-second-j-execution-proof"),
            replica_hash=first.replica_hash,
            source_file_hash=first.source_file_hash,
            source_file_size_bytes=first.source_file_size_bytes,
            recovery_bucket_fingerprint=first.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=first.candidate_storage_key_fingerprint,
            source_authority_fingerprint=first.source_authority_fingerprint,
            candidate_authority_fingerprint=first.candidate_authority_fingerprint,
            configuration_fingerprint=first.configuration_fingerprint,
            lease_snapshot_hash=_digest(f"{slug}-second-j-lease-snapshot"),
            authorization_approved_by_id=first.authorization_approved_by_id,
            authorization_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            candidate_payload=local_path.read_bytes(),
        )

    monkeypatch.setattr(
        recovery_routable_read_cutover_service,
        "_load_cutover_snapshot",
        lambda *args, **kwargs: second_snapshot,
    )

    second_prepared = _prepare_cutover(
        claim_id,
        document_id,
        str(second_authorization_id),
        admin_headers,
    )
    assert second_prepared.status_code == 201, second_prepared.text
    second_lease_id = second_prepared.json()["lease"]["id"]
    assert second_lease_id != first_lease_id
    second_activated = _activate_cutover(
        claim_id,
        document_id,
        second_lease_id,
        third_headers,
    )
    assert second_activated.status_code == 200, second_activated.text
    second_rolled_back = _rollback_cutover(
        claim_id,
        document_id,
        second_lease_id,
        admin_headers,
    )
    assert second_rolled_back.status_code == 200, second_rolled_back.text

    requested_k = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-routable-read-qualification",
        headers=admin_headers,
        json={
            "cutover_lease_ids": [first_lease_id, second_lease_id],
            "reason": "Qualify two real reversible Phase J read cutover and rollback cycles.",
        },
    )
    assert requested_k.status_code == 201, requested_k.text
    qualification_id = requested_k.json()["qualification"]["id"]
    qualified_k = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-routable-read-qualifications/{qualification_id}/qualify",
        headers=approver_headers,
        json={
            "reason": "Independently qualify the repeated real Phase J rollback evidence."
        },
    )
    assert qualified_k.status_code == 200, qualified_k.text
    assert qualified_k.json()["outcome"] == "qualified"

    with TestingSessionLocal() as db:
        first = db.get(EvidenceRecoveryReadPathCutoverLease, UUID(first_lease_id))
        assert first is not None
        replica = db.get(EvidenceRecoveryReplica, first.replica_id)
        assert replica is not None
        remote_key = replica.recovery_storage_key
        route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
            organization_id=org_id,
            claim_id=claim_id,
            document_id=document_id,
        ).one()
        assert route.route_class == "local_source"
        assert route.active_lease_id is None
        assert route.active_replica_id is None
        assert route.read_path_switched is False

    return {
        "org_id": org_id,
        "admin_id": admin_id,
        "k_qualifier_id": approver_id,
        "j_activator_id": third_admin_id,
        "manager_id": manager_id,
        "claim_id": claim_id,
        "document_id": document_id,
        "storage_key": storage_key,
        "local_path": local_path,
        "remote_key": remote_key,
        "admin_headers": admin_headers,
        "k_qualifier_headers": approver_headers,
        "j_activator_headers": third_headers,
        "qualification_id": qualification_id,
    }


REQUEST_REASON = (
    "Request bounded governance approval for a future durable recovery read promotion."
)
APPROVAL_REASON = (
    "Independently approve only the non-routable durable read promotion governance envelope."
)


def _request_l(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-read-qualifications/{data['qualification_id']}/durable-read-promotion-authorization",
        headers=headers or data["j_activator_headers"],
        json={"reason": reason},
    )


def _approve_l(data, authorization_id: str, *, headers=None, reason: str = APPROVAL_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-authorizations/{authorization_id}/approve",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def test_durable_read_promotion_authorization_is_non_routable_and_four_eyes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_k_real_j_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="durable-read-auth-happy",
        )
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]

        requested = _request_l(data)
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "pending_second_approval"
        authorization = requested.json()["authorization"]
        authorization_id = authorization["id"]
        assert authorization["status"] == "pending_second_approval"
        assert authorization["route_version_at_request"] >= 1
        assert authorization["integrity_proof_hash"]
        for field in (
            "routable_authority_created",
            "durable_read_route_created",
            "read_path_switched",
            "write_path_switched",
            "document_storage_key_mutated",
            "authoritative_storage_changed",
            "destructive_action_performed",
            "s3_delete_performed",
            "local_delete_performed",
        ):
            assert authorization[field] is False

        replay = _request_l(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        mismatched_replay = _request_l(
            data,
            reason="Request the same qualification with materially different request semantics.",
        )
        assert mismatched_replay.status_code == 409

        same_requester = _approve_l(
            data,
            authorization_id,
            headers=data["j_activator_headers"],
        )
        assert same_requester.status_code == 409

        k_qualifier = _approve_l(
            data,
            authorization_id,
            headers=data["k_qualifier_headers"],
        )
        assert k_qualifier.status_code == 409

        approved = _approve_l(data, authorization_id)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        assert approved.json()["authorization"]["status"] == "approved"
        assert approved.json()["authorization"]["durable_read_route_created"] is False
        assert approved.json()["authorization"]["read_path_switched"] is False

        approval_replay = _approve_l(data, authorization_id)
        assert approval_replay.status_code == 200, approval_replay.text
        assert approval_replay.json()["outcome"] == "unchanged"

        manager_headers = _headers(data["manager_id"])
        readable = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-authorizations/{authorization_id}",
            headers=manager_headers,
        )
        assert readable.status_code == 200
        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-authorizations/{authorization_id}/receipts",
            headers=manager_headers,
        )
        assert receipts.status_code == 200
        assert [item["phase"] for item in receipts.json()] == ["requested", "approved"]
        assert all(item["read_path_switched"] is False for item in receipts.json())
        assert all(item["durable_read_route_created"] is False for item in receipts.json())

        manager_mutation = _request_l(data, headers=manager_headers)
        assert manager_mutation.status_code == 403

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            stored = db.get(
                EvidenceRecoveryDurableReadPromotionAuthorization,
                UUID(authorization_id),
            )
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"],
                document_id=data["document_id"],
            ).one()
            assert document is not None and stored is not None
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert route.route_class == "local_source"
            assert route.active_lease_id is None
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            assert db.query(EvidenceRecoveryDurableReadPromotionAuthorizationReceipt).count() == 2
            audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.action
                    == "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_APPROVED"
                )
                .one()
            )
            rendered = str(audit.new_values)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered
            assert audit.new_values["routable_authority_created"] is False
            assert audit.new_values["durable_read_route_created"] is False
            assert audit.new_values["read_path_switched"] is False
            assert audit.new_values["write_path_switched"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            assert audit.new_values["destructive_action_performed"] is False

        assert data["local_path"].read_bytes() == local_before
        assert _RecoveryRestoreS3Handler.objects[data["remote_key"]] == remote_before


def test_route_version_drift_invalidates_pending_durable_read_authorization(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_k_real_j_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="durable-read-auth-route-drift",
        )
        requested = _request_l(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"],
                document_id=data["document_id"],
            ).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()

        invalidated = _approve_l(data, authorization_id)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["authorization"]["status"] == "invalidated"
        assert invalidated.json()["authorization"]["read_path_switched"] is False


def test_recovery_candidate_tamper_invalidates_pending_authorization(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_k_real_j_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="durable-read-auth-candidate-tamper",
        )
        requested = _request_l(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        tampered = b"tampered recovery candidate after Phase L request"
        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (
            tampered,
            hashlib.sha256(tampered).hexdigest(),
        )

        invalidated = _approve_l(data, authorization_id)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["authorization"]["status"] == "invalidated"


def test_expired_authorization_fails_closed_without_routing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_k_real_j_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="durable-read-auth-expiry",
        )
        requested = _request_l(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        with TestingSessionLocal() as db:
            stored = db.get(
                EvidenceRecoveryDurableReadPromotionAuthorization,
                UUID(authorization_id),
            )
            assert stored is not None
            stored.authorization_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        expired = _approve_l(data, authorization_id)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["authorization"]["status"] == "expired"
        assert expired.json()["authorization"]["read_path_switched"] is False
        assert expired.json()["authorization"]["durable_read_route_created"] is False


def test_cross_tenant_reads_are_not_found(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_k_real_j_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="durable-read-auth-cross-tenant",
        )
        requested = _request_l(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        other_root = tmp_path / "other-tenant"
        other_root.mkdir(parents=True, exist_ok=True)
        _other_org, other_admin, _other_manager, _other_claim, _other_doc, _other_key, _other_path = _seed_tenant(
            slug="durable-read-auth-other",
            storage_root=other_root,
        )
        other_headers = _headers(other_admin)
        hidden = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-promotion-authorizations/{authorization_id}",
            headers=other_headers,
        )
        assert hidden.status_code == 404
