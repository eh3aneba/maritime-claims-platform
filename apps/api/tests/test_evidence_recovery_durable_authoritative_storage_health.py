from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_durable_authoritative_storage_health_service as phase_ao_service
from app.modules.documents.models import Document
from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_models import (
    EvidenceRecoveryAuthoritativeStorageRatificationAuthorization,
)
from app.modules.documents.recovery_durable_authoritative_storage_health_models import (
    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification,
)
from app.modules.documents.recovery_durable_authoritative_storage_health_service import (
    RecoveryDurableAuthoritativeStorageHealthUnavailable,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_authoritative_storage_ratification_execution import (
    _approved_am,
    _execute_an,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3, _headers, _seed_tenant


def setup_function() -> None:
    reset_database()


REQUEST_REASON = "Independently verify the durable authoritative recovery-storage state after ratification."
QUALIFY_REASON = "Qualify the exact durable authoritative recovery-storage state as healthy."


def _ratified_an(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _approved_am(monkeypatch, tmp_path, endpoint, slug=slug)
    executor_id, executor_headers = _independent_admin(data, slug=f"{slug}-an-executor")
    executed = _execute_an(data, headers=executor_headers)
    assert executed.status_code == 201, executed.text
    assert executed.json()["outcome"] == "ratified"
    data["phase_an_ratification_id"] = executed.json()["ratification"]["id"]
    data["phase_an_executor_id"] = executor_id
    data["phase_an_executor_headers"] = executor_headers
    return data


def _request_ao(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        "recovery-durable-authoritative-storage-health-qualification",
        headers=headers,
        json={"ratification_id": data["phase_an_ratification_id"], "reason": reason},
    )


def _qualify_ao(data, qualification_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
        f"recovery-durable-authoritative-storage-health-qualifications/{qualification_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_ao_qualifies_durable_authority_without_mutation(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _ratified_an(monkeypatch, tmp_path, endpoint, slug="phase-ao-happy")
        requester_id, requester_headers = _independent_admin(data, slug="phase-ao-requester")
        qualifier_id, qualifier_headers = _independent_admin(data, slug="phase-ao-qualifier")

        denied = _request_ao(data, headers=data["manager_headers"])
        assert denied.status_code == 403

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None
            original_storage_key = document.storage_key
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route_version = route.route_version
            assert route.authority_kind == "recovery_storage"
            assert route.authority_tenure == "durable_recovery"
            assert route.active_authority_lease_id is None
            assert str(route.durable_ratification_id) == data["phase_an_ratification_id"]

        requested = _request_ao(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        body = requested.json()
        assert body["outcome"] == "pending_second_approval"
        q = body["qualification"]
        qualification_id = q["id"]
        assert q["requested_by_id"] == str(requester_id)
        assert q["ratification_id"] == data["phase_an_ratification_id"]
        assert q["observed_authority_kind"] == "recovery_storage"
        assert q["observed_authority_tenure"] == "durable_recovery"
        assert q["observed_ratification_active"] is True
        assert q["observed_durable_authority_created"] is True
        assert q["observed_local_authoritative"] is False
        assert q["observed_recovery_authoritative"] is True
        assert q["observed_authoritative_storage_changed"] is True
        assert q["local_evidence_preserved"] is True
        assert q["storage_write_performed"] is False
        assert q["route_mutation_performed"] is False
        assert q["ownership_mutation_performed"] is False
        assert q["read_path_switched"] is False
        assert q["write_path_switched"] is False
        assert q["document_storage_key_mutated"] is False
        assert q["destructive_action_performed"] is False
        assert q["physical_disposal_authorized"] is False
        assert q["s3_put_performed"] is False
        assert q["s3_copy_performed"] is False
        assert q["s3_delete_performed"] is False
        assert q["local_overwrite_performed"] is False
        assert q["local_move_performed"] is False
        assert q["local_delete_performed"] is False
        assert body["receipt"]["phase"] == "requested"

        forbidden = _qualify_ao(data, qualification_id, headers=data["phase_an_executor_headers"])
        assert forbidden.status_code == 409

        qualified = _qualify_ao(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        qualified_body = qualified.json()
        assert qualified_body["outcome"] == "qualified"
        assert qualified_body["qualification"]["qualified_by_id"] == str(qualifier_id)
        assert qualified_body["receipt"]["phase"] == "qualified"

        with TestingSessionLocal() as db:
            document = db.get(Document, data["document_id"])
            assert document is not None and document.storage_key == original_storage_key
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            assert route.route_version == route_version
            assert route.authority_kind == "recovery_storage"
            assert route.authority_tenure == "durable_recovery"
            assert route.active_authority_lease_id is None
            assert str(route.durable_ratification_id) == data["phase_an_ratification_id"]

        replay = _qualify_ao(data, qualification_id, headers=qualifier_headers)
        assert replay.status_code == 200, replay.text
        assert replay.json()["outcome"] == "unchanged"

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-authoritative-storage-health-qualifications/{qualification_id}/receipts",
            headers=data["manager_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        assert [item["phase"] for item in receipts.json()] == ["requested", "qualified"]

        _, other_admin_id, _, _, _, _, _ = _seed_tenant(slug="phase-ao-other", storage_root=tmp_path / "other")
        cross_tenant = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/"
            f"recovery-durable-authoritative-storage-health-qualifications/{qualification_id}",
            headers=_headers(other_admin_id),
        )
        assert cross_tenant.status_code == 404


def test_phase_ao_does_not_depend_on_expired_am_window_after_ratification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _ratified_an(monkeypatch, tmp_path, endpoint, slug="phase-ao-expired-am")
        _, requester_headers = _independent_admin(data, slug="phase-ao-expired-requester")

        with TestingSessionLocal() as db:
            am = db.get(
                EvidenceRecoveryAuthoritativeStorageRatificationAuthorization,
                UUID(data["phase_am_authorization_id"]),
            )
            assert am is not None and am.approved_at is not None
            am.authorization_expires_at = am.approved_at - timedelta(seconds=1)
            db.commit()

        response = _request_ao(data, headers=requester_headers)
        assert response.status_code == 201, response.text
        assert response.json()["outcome"] == "pending_second_approval"


def test_phase_ao_route_drift_invalidates_pending_qualification(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _ratified_an(monkeypatch, tmp_path, endpoint, slug="phase-ao-drift")
        _, requester_headers = _independent_admin(data, slug="phase-ao-drift-requester")
        _, qualifier_headers = _independent_admin(data, slug="phase-ao-drift-qualifier")
        requested = _request_ao(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryAuthoritativeStorageOwnershipRoute).filter_by(
                document_id=data["document_id"]
            ).one()
            route.route_version += 1
            db.commit()

        qualified = _qualify_ao(data, qualification_id, headers=qualifier_headers)
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "invalidated"
        assert qualified.json()["qualification"]["status"] == "invalidated"


def test_phase_ao_storage_outage_is_retryable_without_artifact(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _ratified_an(monkeypatch, tmp_path, endpoint, slug="phase-ao-outage")
        _, requester_headers = _independent_admin(data, slug="phase-ao-outage-requester")
        original = phase_ao_service._durable_an_snapshot

        def unavailable(*args, **kwargs):
            raise RecoveryDurableAuthoritativeStorageHealthUnavailable(
                "simulated Phase AO recovery-storage outage"
            )

        monkeypatch.setattr(phase_ao_service, "_durable_an_snapshot", unavailable)
        outage = _request_ao(data, headers=requester_headers)
        assert outage.status_code == 503, outage.text
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryDurableAuthoritativeStorageHealthQualification).filter_by(
                ratification_id=UUID(data["phase_an_ratification_id"])
            ).one_or_none() is None

        monkeypatch.setattr(phase_ao_service, "_durable_an_snapshot", original)
        retried = _request_ao(data, headers=requester_headers)
        assert retried.status_code == 201, retried.text
        assert retried.json()["outcome"] == "pending_second_approval"
