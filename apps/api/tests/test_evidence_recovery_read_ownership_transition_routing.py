from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_read_ownership_transition_routing_service as phase_v_service
from app.modules.documents.recovery_read_ownership_transition_routing_models import (
    EvidenceRecoveryReadOwnershipTransitionLease,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import RecoveryRoutableReadCutoverUnavailable
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_read_ownership_transition_authorization import (
    _approve_u,
    _qualified_t,
    _request_u,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


PREPARE_REASON = "Prepare the independently authorized bounded Phase V recovery read-ownership transition lease."
ACTIVATE_REASON = "Activate the bounded Phase V recovery read-ownership route after fresh integrity review."
ROLLBACK_REASON = "Roll back the Phase V recovery read-ownership route to the intact local source."
RECONCILE_REASON = "Reconcile the expired Phase V recovery read-ownership window back to local source."


def _approved_u(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _qualified_t(monkeypatch, tmp_path, endpoint, slug=slug)
    requested = _request_u(data)
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["authorization"]["id"]
    approver_id, approver_headers = _independent_admin(data, slug=f"{slug}-u-approver")
    approved = _approve_u(data, authorization_id, headers=approver_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["outcome"] == "approved"
    data["phase_u_authorization_id"] = authorization_id
    data["phase_u_approver_id"] = approver_id
    data["phase_u_approver_headers"] = approver_headers
    return data


def _prepare_v(data, *, headers=None, reason: str = PREPARE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-authorizations/{data['phase_u_authorization_id']}/transition-lease",
        headers=headers or data["admin_headers"],
        json={"reason": reason},
    )


def _activate_v(data, lease_id: str, *, headers, reason: str = ACTIVATE_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-leases/{lease_id}/activate",
        headers=headers,
        json={"reason": reason},
    )


def _rollback_v(data, lease_id: str, *, headers, reason: str = ROLLBACK_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-leases/{lease_id}/rollback",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_v_owns_reads_boundedly_and_rolls_back_without_storage_ownership(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_u(monkeypatch, tmp_path, endpoint, slug="phase-v-happy")
        prepared = _prepare_v(data)
        assert prepared.status_code == 201, prepared.text
        body = prepared.json()
        assert body["outcome"] == "prepared"
        lease = body["lease"]
        lease_id = lease["id"]
        assert lease["authorization_id"] == data["phase_u_authorization_id"]
        assert lease["routable_authority_created"] is False
        assert lease["durable_read_route_created"] is False
        assert lease["read_ownership_authority_created"] is False
        assert lease["read_path_switched"] is False
        assert lease["write_path_switched"] is False
        assert lease["document_storage_key_mutated"] is False
        assert lease["authoritative_storage_changed"] is False
        assert lease["destructive_action_performed"] is False

        replay = _prepare_v(data)
        assert replay.status_code == 201, replay.text
        assert replay.json()["outcome"] == "unchanged"
        assert replay.json()["lease"]["id"] == lease_id
        changed = _prepare_v(
            data,
            reason="Prepare the same Phase V authorization with intentionally changed semantics.",
        )
        assert changed.status_code == 409

        assert _activate_v(data, lease_id, headers=data["admin_headers"]).status_code == 409
        assert _activate_v(data, lease_id, headers=data["phase_u_approver_headers"]).status_code == 409
        activator_id, activator_headers = _independent_admin(data, slug="phase-v-happy-activator")
        activated = _activate_v(data, lease_id, headers=activator_headers)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"
        active = activated.json()["lease"]
        assert active["activated_by_id"] == str(activator_id)
        assert active["routable_authority_created"] is True
        assert active["durable_read_route_created"] is True
        assert active["read_ownership_authority_created"] is True
        assert active["read_path_switched"] is True
        assert active["write_path_switched"] is False
        assert active["document_storage_key_mutated"] is False
        assert active["authoritative_storage_changed"] is False
        assert active["destructive_action_performed"] is False
        assert activated.json()["route"]["route_authority_kind"] == "read_ownership_transition"
        assert activated.json()["route"]["active_read_ownership_transition_lease_id"] == lease_id

        download = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert download.status_code == 200, download.text
        assert download.headers["X-MCRI-Evidence-Read-Source"] == "recovery-replica-read-ownership-transition"

        manager_get = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-leases/{lease_id}",
            headers=data["manager_headers"],
        )
        assert manager_get.status_code == 200, manager_get.text
        assert _prepare_v(data, headers=data["manager_headers"]).status_code == 403

        rolled_back = _rollback_v(data, lease_id, headers=activator_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
        assert rolled_back.json()["route"]["route_class"] == "local_source"
        assert rolled_back.json()["route"]["route_authority_kind"] == "local"
        assert rolled_back.json()["route"]["active_read_ownership_transition_lease_id"] is None
        assert rolled_back.json()["lease"]["authoritative_storage_changed"] is False

        local_download = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert local_download.status_code == 200, local_download.text
        assert local_download.headers["X-MCRI-Evidence-Read-Source"] == "local-source"

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-leases/{lease_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["prepared", "activated", "rolled_back"]

        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionLease, UUID(lease_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            assert stored is not None and stored.status == "rolled_back"
            assert stored.write_path_switched is False
            assert stored.document_storage_key_mutated is False
            assert stored.authoritative_storage_changed is False
            assert route.route_class == "local_source"
            assert route.active_read_ownership_transition_lease_id is None

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(
            slug="phase-v-other", storage_root=tmp_path / "other"
        )
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-leases/{lease_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_v_activation_storage_outage_is_retryable_and_keeps_prepared(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_u(monkeypatch, tmp_path, endpoint, slug="phase-v-activation-outage")
        prepared = _prepare_v(data)
        assert prepared.status_code == 201, prepared.text
        lease_id = prepared.json()["lease"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-v-outage-activator")
        original_reader = phase_v_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase V activation storage outage")

        monkeypatch.setattr(phase_v_service, "_read_verified_candidate", unavailable)
        outage = _activate_v(data, lease_id, headers=activator_headers)
        assert outage.status_code == 503
        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionLease, UUID(lease_id))
            assert stored is not None and stored.status == "prepared"
        monkeypatch.setattr(phase_v_service, "_read_verified_candidate", original_reader)

        activated = _activate_v(data, lease_id, headers=activator_headers)
        assert activated.status_code == 200, activated.text
        assert activated.json()["outcome"] == "activated"


def test_phase_v_active_read_storage_outage_has_no_local_fallback(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_u(monkeypatch, tmp_path, endpoint, slug="phase-v-read-outage")
        prepared = _prepare_v(data)
        lease_id = prepared.json()["lease"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-v-read-outage-activator")
        activated = _activate_v(data, lease_id, headers=activator_headers)
        assert activated.status_code == 200, activated.text
        original_reader = phase_v_service._read_verified_candidate

        def unavailable(*args, **kwargs):
            raise RecoveryRoutableReadCutoverUnavailable("simulated Phase V active-read storage outage")

        monkeypatch.setattr(phase_v_service, "_read_verified_candidate", unavailable)
        download = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert download.status_code == 503
        monkeypatch.setattr(phase_v_service, "_read_verified_candidate", original_reader)
        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionLease, UUID(lease_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            assert stored is not None and stored.status == "activated"
            assert route.route_authority_kind == "read_ownership_transition"


def test_phase_v_route_drift_before_activation_invalidates_fail_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_u(monkeypatch, tmp_path, endpoint, slug="phase-v-route-drift")
        prepared = _prepare_v(data)
        lease_id = prepared.json()["lease"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-v-route-drift-activator")
        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(document_id=data["document_id"]).one()
            route.route_version += 1
            db.commit()
        invalidated = _activate_v(data, lease_id, headers=activator_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["lease"]["status"] == "invalidated"
        assert invalidated.json()["lease"]["authoritative_storage_changed"] is False
        assert invalidated.json()["route"]["route_class"] == "local_source"


def test_phase_v_expiry_reconciliation_restores_local_route(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _approved_u(monkeypatch, tmp_path, endpoint, slug="phase-v-expiry")
        prepared = _prepare_v(data)
        lease_id = prepared.json()["lease"]["id"]
        _, activator_headers = _independent_admin(data, slug="phase-v-expiry-activator")
        activated = _activate_v(data, lease_id, headers=activator_headers)
        assert activated.status_code == 200, activated.text
        with TestingSessionLocal() as db:
            stored = db.get(EvidenceRecoveryReadOwnershipTransitionLease, UUID(lease_id))
            assert stored is not None
            stored.route_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        reconciled = client.post(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/recovery-read-ownership-transition-leases/{lease_id}/reconcile",
            headers=activator_headers,
            json={"reason": RECONCILE_REASON},
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["outcome"] == "expired"
        assert reconciled.json()["route"]["route_class"] == "local_source"
        assert reconciled.json()["route"]["active_read_ownership_transition_lease_id"] is None
