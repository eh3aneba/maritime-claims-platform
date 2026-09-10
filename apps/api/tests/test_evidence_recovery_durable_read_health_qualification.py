import hashlib
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents import recovery_durable_read_routing_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_health_models import (
    EvidenceRecoveryDurableReadHealthQualification,
    EvidenceRecoveryDurableReadHealthQualificationReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_routing import (
    _activate_m,
    _approved_l,
    _download,
    _prepare_m,
    _rollback_m,
)
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Request independent qualification of the completed durable recovery read operational evidence."
QUALIFY_REASON = "Independently confirm the durable recovery read window met the bounded health criteria."


def _request_n(data, lease_id: str, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualification",
        headers=headers or data["admin_headers"],
        json={"durable_lease_id": lease_id, "reason": reason},
    )


def _qualify_n(data, qualification_id: str, *, headers=None, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{qualification_id}/qualify",
        headers=headers or data["j_activator_headers"],
        json={"reason": reason},
    )


def _terminal_healthy_m(data) -> str:
    prepared = _prepare_m(data)
    assert prepared.status_code == 201, prepared.text
    lease_id = prepared.json()["lease"]["id"]
    activated = _activate_m(data, lease_id)
    assert activated.status_code == 200, activated.text
    assert activated.json()["outcome"] == "activated"
    during = _download(data)
    assert during.status_code == 200, during.text
    assert during.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica-durable"
    rolled_back = _rollback_m(data, lease_id)
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["outcome"] == "rolled_back"
    return lease_id


def test_healthy_completed_durable_read_window_is_four_eyes_qualified_without_authority_change(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-health-happy")
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]
        lease_id = _terminal_healthy_m(data)

        requested = _request_n(data, lease_id)
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "pending_second_approval"
        qualification = requested.json()["qualification"]
        qualification_id = qualification["id"]
        assert qualification["status"] == "pending_second_approval"
        assert qualification["health_state"] == "healthy"
        assert qualification["verified_durable_read_count"] >= 1
        assert qualification["integrity_failure_count"] == 0
        assert qualification["storage_unavailable_count"] == 0
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
            assert qualification[field] is False

        replay = _request_n(data, lease_id)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["qualification"]["id"] == qualification_id

        same_requester = _qualify_n(data, qualification_id, headers=data["admin_headers"])
        assert same_requester.status_code == 409
        phase_m_activator = _qualify_n(
            data,
            qualification_id,
            headers=data["k_qualifier_headers"],
        )
        assert phase_m_activator.status_code == 409

        qualified = _qualify_n(data, qualification_id)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["status"] == "qualified"
        assert qualified.json()["qualification"]["health_state"] == "healthy"

        qualify_replay = _qualify_n(data, qualification_id)
        assert qualify_replay.status_code == 200, qualify_replay.text
        assert qualify_replay.json()["outcome"] == "unchanged"

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{qualification_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200, manager_read.text
        manager_receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{qualification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert manager_receipts.status_code == 200, manager_receipts.text
        assert [item["phase"] for item in manager_receipts.json()] == ["requested", "qualified"]

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDurableReadHealthQualification, UUID(qualification_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            receipts = db.query(EvidenceRecoveryDurableReadHealthQualificationReceipt).filter_by(
                health_qualification_id=UUID(qualification_id)
            ).all()
            assert stored is not None and document is not None
            assert stored.status == "qualified"
            assert stored.health_state == "healthy"
            assert [item.phase for item in receipts] == ["requested", "qualified"]
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            audits = db.query(AuditLog).filter(
                AuditLog.entity_type == "evidence_recovery_durable_read_health_qualification"
            ).all()
            assert audits
            rendered = " ".join(str(item.new_values) for item in audits)
            assert data["storage_key"] not in rendered
            assert data["remote_key"] not in rendered

        assert data["local_path"].read_bytes() == local_before
        assert _RecoveryRestoreS3Handler.objects[data["remote_key"]] == remote_before


def test_storage_unavailability_is_preserved_as_degraded_health_not_silent_qualification(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-health-outage")
        prepared = _prepare_m(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_m(data, lease_id)
        assert activated.status_code == 200, activated.text
        first_read = _download(data)
        assert first_read.status_code == 200, first_read.text

        original_reader = recovery_durable_read_routing_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated recovery object-store outage")

        monkeypatch.setattr(
            recovery_durable_read_routing_service,
            "_read_verified_candidate",
            unavailable,
        )
        outage = _download(data)
        assert outage.status_code == 503
        monkeypatch.setattr(
            recovery_durable_read_routing_service,
            "_read_verified_candidate",
            original_reader,
        )

        rolled_back = _rollback_m(data, lease_id)
        assert rolled_back.status_code == 200, rolled_back.text

        requested = _request_n(data, lease_id)
        assert requested.status_code == 201, requested.text
        qualification = requested.json()["qualification"]
        assert qualification["health_state"] == "degraded"
        assert qualification["verified_durable_read_count"] >= 1
        assert qualification["storage_unavailable_count"] == 1
        assert qualification["integrity_failure_count"] == 0

        with TestingSessionLocal() as db:
            failures = db.query(AuditLog).filter(
                AuditLog.action == "DOWNLOAD_DOCUMENT_RECOVERY_FAILED"
            ).all()
            failure = next(
                item
                for item in failures
                if item.new_values
                and item.new_values.get("recovery_durable_lease_id") == lease_id
            )
            assert failure.new_values["failure_class"] == "storage_unavailable"
            assert data["remote_key"] not in str(failure.new_values)
            assert "simulated recovery object-store outage" not in str(failure.new_values)

        assessed = _qualify_n(data, qualification["id"])
        assert assessed.status_code == 200, assessed.text
        assert assessed.json()["outcome"] == "degraded"
        assert assessed.json()["qualification"]["status"] == "degraded"
        assert assessed.json()["qualification"]["status"] != "qualified"


def test_historical_integrity_failure_makes_completed_window_failed_and_non_qualifiable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-health-tamper")
        prepared = _prepare_m(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_m(data, lease_id)
        assert activated.status_code == 200, activated.text
        first_read = _download(data)
        assert first_read.status_code == 200, first_read.text

        original_payload, original_digest = _RecoveryRestoreS3Handler.objects[data["remote_key"]]
        tampered = bytes((byte ^ 0x01) for byte in original_payload)
        assert len(tampered) == len(original_payload)
        assert hashlib.sha256(tampered).hexdigest() != original_digest
        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (tampered, original_digest)
        failed = _download(data)
        assert failed.status_code == 409
        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (
            original_payload,
            original_digest,
        )

        rolled_back = _rollback_m(data, lease_id)
        assert rolled_back.status_code == 200, rolled_back.text

        requested = _request_n(data, lease_id)
        assert requested.status_code == 201, requested.text
        qualification = requested.json()["qualification"]
        assert qualification["health_state"] == "failed"
        assert qualification["verified_durable_read_count"] >= 1
        assert qualification["integrity_failure_count"] == 1

        assessed = _qualify_n(data, qualification["id"])
        assert assessed.status_code == 200, assessed.text
        assert assessed.json()["outcome"] == "degraded"
        assert assessed.json()["qualification"]["status"] == "degraded"
        assert assessed.json()["qualification"]["health_state"] == "failed"


def test_activation_without_verified_durable_read_cannot_create_health_qualification(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-health-zero-read")
        prepared = _prepare_m(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        activated = _activate_m(data, lease_id)
        assert activated.status_code == 200, activated.text
        rolled_back = _rollback_m(data, lease_id)
        assert rolled_back.status_code == 200, rolled_back.text

        requested = _request_n(data, lease_id)
        assert requested.status_code == 409
        with TestingSessionLocal() as db:
            count = db.query(EvidenceRecoveryDurableReadHealthQualification).count()
            assert count == 0


def test_durable_read_health_is_tenant_scoped_and_claims_manager_is_read_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _approved_l(monkeypatch, tmp_path, endpoint, slug="durable-health-tenant")
        lease_id = _terminal_healthy_m(data)
        requested = _request_n(data, lease_id)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{qualification_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200
        manager_receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{qualification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert manager_receipts.status_code == 200
        manager_mutation = _qualify_n(
            data,
            qualification_id,
            headers=data["manager_headers"],
        )
        assert manager_mutation.status_code == 403

        _, other_admin_id, _, other_claim_id, other_document_id, _, _ = _seed_tenant(
            slug="durable-health-other",
            storage_root=tmp_path / "other",
        )
        other_headers = _headers(other_admin_id)
        cross_tenant_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{qualification_id}",
            headers=other_headers,
        )
        assert cross_tenant_read.status_code == 404
        cross_tenant_receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{qualification_id}/receipts",
            headers=other_headers,
        )
        assert cross_tenant_receipts.status_code == 404
        owner_into_other_claim = client.get(
            f"/api/v1/claims/{other_claim_id}/documents/{other_document_id}/recovery-durable-read-health-qualifications/{qualification_id}",
            headers=data["admin_headers"],
        )
        assert owner_into_other_claim.status_code == 404
