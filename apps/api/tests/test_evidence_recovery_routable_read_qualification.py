import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_routable_read_cutover_models import (
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathCutoverReceipt,
    EvidenceRecoveryReadPathRoute,
)
from app.modules.documents.recovery_routable_read_qualification_models import (
    EvidenceRecoveryRoutableReadQualification,
    EvidenceRecoveryRoutableReadQualificationReceipt,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant
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


def _two_successful_cycles(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
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
        authorization_id,
    ) = _approved_read_path_authorization(
        monkeypatch,
        tmp_path,
        endpoint,
        slug=slug,
    )
    prepared = _prepare_cutover(
        claim_id,
        document_id,
        authorization_id,
        admin_headers,
    )
    assert prepared.status_code == 201, prepared.text
    first_lease_id = UUID(prepared.json()["lease"]["id"])
    activated = _activate_cutover(
        claim_id,
        document_id,
        str(first_lease_id),
        third_headers,
    )
    assert activated.status_code == 200, activated.text
    rolled_back = _rollback_cutover(
        claim_id,
        document_id,
        str(first_lease_id),
        admin_headers,
    )
    assert rolled_back.status_code == 200, rolled_back.text

    with TestingSessionLocal() as db:
        first = db.get(EvidenceRecoveryReadPathCutoverLease, first_lease_id)
        route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
            organization_id=org_id,
            claim_id=claim_id,
            document_id=document_id,
        ).one()
        assert first is not None
        assert first.activated_by_id is not None
        assert first.rolled_back_by_id is not None
        assert first.rolled_back_at is not None

        second_authorization_id = uuid4()
        second_lease = EvidenceRecoveryReadPathCutoverLease(
            organization_id=org_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=second_authorization_id,
            authorization_approval_receipt_id=uuid4(),
            replica_id=first.replica_id,
            authorization_hash=_digest(f"{slug}-authorization-2"),
            authorization_request_snapshot_hash=_digest(f"{slug}-auth-snapshot-2"),
            authorization_approval_receipt_hash=_digest(f"{slug}-auth-receipt-2"),
            execution_transition_proof_hash=_digest(f"{slug}-execution-proof-2"),
            replica_hash=first.replica_hash,
            source_file_hash=first.source_file_hash,
            source_file_size_bytes=first.source_file_size_bytes,
            recovery_bucket_fingerprint=first.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=first.candidate_storage_key_fingerprint,
            source_authority_fingerprint=first.source_authority_fingerprint,
            candidate_authority_fingerprint=first.candidate_authority_fingerprint,
            configuration_fingerprint=first.configuration_fingerprint,
            lease_snapshot_hash=_digest(f"{slug}-lease-snapshot-2"),
            lease_hash=_digest(f"{slug}-lease-2"),
            status="rolled_back",
            lease_expires_at=first.lease_expires_at,
            authorization_approved_by_id=first.authorization_approved_by_id,
            prepared_by_id=first.prepared_by_id,
            prepared_at=first.rolled_back_at + timedelta(seconds=1),
            preparation_reason="Prepare the second independently governed recovery read cutover.",
            activated_by_id=first.activated_by_id,
            activated_at=first.rolled_back_at + timedelta(seconds=2),
            activation_reason="Activate the second independently governed recovery read cutover.",
            rolled_back_by_id=first.rolled_back_by_id,
            rolled_back_at=first.rolled_back_at + timedelta(seconds=3),
            rollback_reason="Roll the second recovery read cutover back to local authority.",
            routable_authority_created=False,
            read_path_switched=False,
            write_path_switched=False,
            document_storage_key_mutated=False,
            authoritative_storage_changed=False,
            destructive_action_performed=False,
            s3_delete_performed=False,
            local_delete_performed=False,
        )
        db.add(second_lease)
        db.flush()
        activation_version = route.route_version + 1
        rollback_version = route.route_version + 2
        activation = EvidenceRecoveryReadPathCutoverReceipt(
            organization_id=org_id,
            claim_id=claim_id,
            document_id=document_id,
            cutover_lease_id=second_lease.id,
            authorization_id=second_authorization_id,
            phase="activated",
            from_route_class="local_source",
            to_route_class="recovery_replica",
            route_version=activation_version,
            lease_snapshot_hash=second_lease.lease_snapshot_hash,
            lease_hash=second_lease.lease_hash,
            authorization_hash=second_lease.authorization_hash,
            receipt_hash=_digest(f"{slug}-activation-receipt-2"),
            actor_id=second_lease.activated_by_id,
            reason="Activate the second independently governed recovery read cutover.",
            transitioned_at=second_lease.activated_at,
            routable_authority_created=True,
            read_path_switched=True,
            write_path_switched=False,
            document_storage_key_mutated=False,
            authoritative_storage_changed=False,
            destructive_action_performed=False,
        )
        rollback = EvidenceRecoveryReadPathCutoverReceipt(
            organization_id=org_id,
            claim_id=claim_id,
            document_id=document_id,
            cutover_lease_id=second_lease.id,
            authorization_id=second_authorization_id,
            phase="rolled_back",
            from_route_class="recovery_replica",
            to_route_class="local_source",
            route_version=rollback_version,
            lease_snapshot_hash=second_lease.lease_snapshot_hash,
            lease_hash=second_lease.lease_hash,
            authorization_hash=second_lease.authorization_hash,
            receipt_hash=_digest(f"{slug}-rollback-receipt-2"),
            actor_id=second_lease.rolled_back_by_id,
            reason="Roll the second recovery read cutover back to local authority.",
            transitioned_at=second_lease.rolled_back_at,
            routable_authority_created=False,
            read_path_switched=False,
            write_path_switched=False,
            document_storage_key_mutated=False,
            authoritative_storage_changed=False,
            destructive_action_performed=False,
        )
        db.add_all([activation, rollback])
        route.route_version = rollback_version
        route.changed_by_id = second_lease.rolled_back_by_id
        route.changed_at = second_lease.rolled_back_at
        route.route_class = "local_source"
        route.active_lease_id = None
        route.active_replica_id = None
        route.read_path_switched = False
        db.commit()
        second_lease_id = second_lease.id

    return {
        "org_id": org_id,
        "admin_id": admin_id,
        "approver_id": approver_id,
        "activator_id": third_admin_id,
        "manager_id": manager_id,
        "claim_id": claim_id,
        "document_id": document_id,
        "storage_key": storage_key,
        "local_path": local_path,
        "admin_headers": admin_headers,
        "approver_headers": approver_headers,
        "activator_headers": third_headers,
        "first_lease_id": first_lease_id,
        "second_lease_id": second_lease_id,
    }


def _request(data, *, headers=None):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-read-qualification",
        headers=headers or data["admin_headers"],
        json={
            "cutover_lease_ids": [
                str(data["second_lease_id"]),
                str(data["first_lease_id"]),
            ],
            "reason": "Qualify two independently governed recovery read cutover and rollback cycles.",
        },
    )


def _qualify(data, qualification_id: str, headers):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-read-qualifications/{qualification_id}/qualify",
        headers=headers,
        json={"reason": "Independently confirm repeated reversible recovery read cutover qualification."},
    )


def test_repeated_cutovers_require_four_eyes_and_create_only_non_routable_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _two_successful_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-qualification-happy",
        )
        requested = _request(data)
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "pending_second_approval"
        qualification = requested.json()["qualification"]
        qualification_id = qualification["id"]
        assert qualification["successful_cycle_count"] == 2
        assert qualification["status"] == "pending_second_approval"
        for field in (
            "routable_authority_created",
            "read_path_switched",
            "write_path_switched",
            "document_storage_key_mutated",
            "authoritative_storage_changed",
            "destructive_action_performed",
            "s3_delete_performed",
            "local_delete_performed",
        ):
            assert qualification[field] is False

        replay = _request(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == qualification_id

        same_requester = _qualify(data, qualification_id, data["admin_headers"])
        assert same_requester.status_code == 409
        activator = _qualify(data, qualification_id, data["activator_headers"])
        assert activator.status_code == 409

        manager_headers = _headers(data["manager_id"])
        manager_mutation = _qualify(data, qualification_id, manager_headers)
        assert manager_mutation.status_code == 403

        approved = _qualify(data, qualification_id, data["approver_headers"])
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "qualified"
        assert approved.json()["qualification"]["status"] == "qualified"
        assert approved.json()["qualification"]["read_path_switched"] is False

        readable = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-read-qualifications/{qualification_id}",
            headers=manager_headers,
        )
        assert readable.status_code == 200
        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-read-qualifications/{qualification_id}/receipts",
            headers=manager_headers,
        )
        assert receipts.status_code == 200
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]
        assert all(item["read_path_switched"] is False for item in receipts.json())

        _other_org, _other_admin, other_manager, _other_claim, _other_doc, _other_key, _other_path = _seed_tenant(
            slug="read-qualification-other",
            storage_root=tmp_path / "other",
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-read-qualifications/{qualification_id}",
            headers=_headers(other_manager),
        )
        assert cross_tenant.status_code == 404

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            stored = db.get(EvidenceRecoveryRoutableReadQualification, UUID(qualification_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert document is not None and stored is not None
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert data["local_path"].exists()
            assert route.route_class == "local_source"
            assert route.active_lease_id is None
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            assert db.query(EvidenceRecoveryRoutableReadQualificationReceipt).count() == 2
            audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.action
                    == "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_APPROVED"
                )
                .one()
            )
            rendered = str(audit.new_values)
            assert data["storage_key"] not in rendered
            assert audit.new_values["routable_authority_created"] is False
            assert audit.new_values["read_path_switched"] is False
            assert audit.new_values["write_path_switched"] is False
            assert audit.new_values["authoritative_storage_changed"] is False
            assert audit.new_values["destructive_action_performed"] is False


def test_qualification_fails_closed_when_route_changes_after_request(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _two_successful_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-qualification-route-drift",
        )
        requested = _request(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]
        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()

        invalidated = _qualify(data, qualification_id, data["approver_headers"])
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["qualification"]["status"] == "invalidated"
        assert invalidated.json()["qualification"]["read_path_switched"] is False


def test_qualification_rejects_mixed_lineage_and_duplicate_cycle(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _two_successful_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-qualification-lineage",
        )
        duplicate = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-routable-read-qualification",
            headers=data["admin_headers"],
            json={
                "cutover_lease_ids": [
                    str(data["first_lease_id"]),
                    str(data["first_lease_id"]),
                ],
                "reason": "Duplicate cycles must never satisfy repeated cutover qualification.",
            },
        )
        assert duplicate.status_code == 422

        with TestingSessionLocal() as db:
            second = db.get(
                EvidenceRecoveryReadPathCutoverLease,
                data["second_lease_id"],
            )
            assert second is not None
            second.configuration_fingerprint = _digest("drifted-configuration")
            db.commit()
        mixed = _request(data)
        assert mixed.status_code == 409
