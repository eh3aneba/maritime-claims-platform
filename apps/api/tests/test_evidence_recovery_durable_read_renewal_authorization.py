from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.documents import recovery_durable_read_health_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_health_models import (
    EvidenceRecoveryDurableReadHealthQualification,
)
from app.modules.documents.recovery_durable_read_renewal_models import (
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadRenewalAuthorizationReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_health_qualification import (
    _qualify_n,
    _request_n,
    _terminal_healthy_m,
)
from tests.test_evidence_recovery_durable_read_routing import _approved_l
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
    _headers,
    _seed_tenant,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = (
    "Request bounded governance authorization for a future healthy durable recovery read renewal."
)
APPROVAL_REASON = (
    "Independently approve only the non-routable bounded durable recovery read renewal envelope."
)


def _qualified_n(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_l(monkeypatch, tmp_path, endpoint, slug=slug)
    lease_id = _terminal_healthy_m(data)
    requested = _request_n(data, lease_id)
    assert requested.status_code == 201, requested.text
    health_qualification_id = requested.json()["qualification"]["id"]
    qualified = _qualify_n(data, health_qualification_id)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] == "qualified"
    assert qualified.json()["qualification"]["health_state"] == "healthy"
    data["durable_lease_id"] = lease_id
    data["health_qualification_id"] = health_qualification_id
    return data


def _request_o(data, *, headers=None, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-health-qualifications/{data['health_qualification_id']}/renewal-authorization",
        headers=headers or data["j_activator_headers"],
        json={"reason": reason},
    )


def _approve_o(data, authorization_id: str, *, headers=None, reason: str = APPROVAL_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-authorizations/{authorization_id}/approve",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def test_healthy_phase_n_can_authorize_bounded_renewal_without_routing_or_ownership_change(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_n(monkeypatch, tmp_path, endpoint, slug="durable-renewal-happy")
        local_before = data["local_path"].read_bytes()
        remote_before = _RecoveryRestoreS3Handler.objects[data["remote_key"]]

        requested = _request_o(data)
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "pending_second_approval"
        authorization = requested.json()["authorization"]
        authorization_id = authorization["id"]
        assert authorization["status"] == "pending_second_approval"
        assert authorization["health_state"] == "healthy"
        assert authorization["verified_durable_read_count"] >= 1
        assert authorization["integrity_failure_count"] == 0
        assert authorization["storage_unavailable_count"] == 0
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

        replay = _request_o(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["authorization"]["id"] == authorization_id

        mismatched_replay = _request_o(
            data,
            reason="Request a materially different renewal authorization for the same health evidence.",
        )
        assert mismatched_replay.status_code == 409

        same_requester = _approve_o(
            data,
            authorization_id,
            headers=data["j_activator_headers"],
        )
        assert same_requester.status_code == 409

        prior_m_activator = _approve_o(
            data,
            authorization_id,
            headers=data["k_qualifier_headers"],
        )
        assert prior_m_activator.status_code == 409

        approved = _approve_o(data, authorization_id)
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "approved"
        assert approved.json()["authorization"]["status"] == "approved"
        assert approved.json()["authorization"]["durable_read_route_created"] is False
        assert approved.json()["authorization"]["read_path_switched"] is False

        approval_replay = _approve_o(data, authorization_id)
        assert approval_replay.status_code == 200, approval_replay.text
        assert approval_replay.json()["outcome"] == "unchanged"

        manager_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-authorizations/{authorization_id}",
            headers=data["manager_headers"],
        )
        assert manager_read.status_code == 200, manager_read.text
        manager_receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-authorizations/{authorization_id}/receipts",
            headers=data["manager_headers"],
        )
        assert manager_receipts.status_code == 200, manager_receipts.text
        assert [item["phase"] for item in manager_receipts.json()] == ["requested", "approved"]
        assert all(item["read_path_switched"] is False for item in manager_receipts.json())

        manager_mutation = _request_o(data, headers=data["manager_headers"])
        assert manager_mutation.status_code == 403

        _, other_admin_id, _, other_claim_id, other_document_id, _, _ = _seed_tenant(
            slug="durable-renewal-other",
            storage_root=tmp_path / "other",
        )
        other_headers = _headers(other_admin_id)
        cross_tenant_read = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-durable-read-renewal-authorizations/{authorization_id}",
            headers=other_headers,
        )
        assert cross_tenant_read.status_code == 404
        owner_into_other_claim = client.get(
            f"/api/v1/claims/{other_claim_id}/documents/{other_document_id}/recovery-durable-read-renewal-authorizations/{authorization_id}",
            headers=data["admin_headers"],
        )
        assert owner_into_other_claim.status_code == 404

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDurableReadRenewalAuthorization, UUID(authorization_id))
            document = db.get(Document, data["document_id"])
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            receipts = db.query(EvidenceRecoveryDurableReadRenewalAuthorizationReceipt).filter_by(
                authorization_id=UUID(authorization_id)
            ).all()
            assert stored is not None and document is not None
            assert stored.status == "approved"
            assert stored.health_state == "healthy"
            assert [item.phase for item in receipts] == ["requested", "approved"]
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert route.route_class == "local_source"
            assert route.route_authority_kind == "local"
            assert route.active_lease_id is None
            assert route.active_durable_lease_id is None
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            audit = db.query(AuditLog).filter(
                AuditLog.action == "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_APPROVED"
            ).one()
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


def test_only_current_healthy_phase_n_evidence_is_admitted_and_route_drift_invalidates_pending(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_n(monkeypatch, tmp_path, endpoint, slug="durable-renewal-drift")

        with TestingSessionLocal() as db:
            health = db.get(
                EvidenceRecoveryDurableReadHealthQualification,
                UUID(data["health_qualification_id"]),
            )
            assert health is not None
            health.status = "degraded"
            health.health_state = "degraded"
            health.storage_unavailable_count = 1
            db.commit()

        not_healthy = _request_o(data)
        assert not_healthy.status_code == 409

        with TestingSessionLocal() as db:
            health = db.get(
                EvidenceRecoveryDurableReadHealthQualification,
                UUID(data["health_qualification_id"]),
            )
            assert health is not None
            health.status = "qualified"
            health.health_state = "healthy"
            health.storage_unavailable_count = 0
            db.commit()

        requested = _request_o(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()

        invalidated = _approve_o(data, authorization_id)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["authorization"]["status"] == "invalidated"
        assert invalidated.json()["authorization"]["read_path_switched"] is False
        assert invalidated.json()["authorization"]["write_path_switched"] is False


def test_transient_storage_outage_keeps_renewal_pending_then_expiry_fails_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_n(monkeypatch, tmp_path, endpoint, slug="durable-renewal-outage")
        requested = _request_o(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        original_reader = recovery_durable_read_health_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable(
                "simulated recovery object-store outage during Phase O approval"
            )

        monkeypatch.setattr(
            recovery_durable_read_health_service,
            "_read_verified_candidate",
            unavailable,
        )
        outage = _approve_o(data, authorization_id)
        assert outage.status_code == 503

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDurableReadRenewalAuthorization, UUID(authorization_id))
            assert stored is not None
            assert stored.status == "pending_second_approval"
            assert db.query(EvidenceRecoveryDurableReadRenewalAuthorizationReceipt).filter_by(
                authorization_id=UUID(authorization_id)
            ).count() == 1

        monkeypatch.setattr(
            recovery_durable_read_health_service,
            "_read_verified_candidate",
            original_reader,
        )
        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryDurableReadRenewalAuthorization, UUID(authorization_id))
            assert stored is not None
            stored.authorization_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        expired = _approve_o(data, authorization_id)
        assert expired.status_code == 200, expired.text
        assert expired.json()["outcome"] == "expired"
        assert expired.json()["authorization"]["status"] == "expired"
        assert expired.json()["authorization"]["read_path_switched"] is False
        assert expired.json()["authorization"]["durable_read_route_created"] is False
