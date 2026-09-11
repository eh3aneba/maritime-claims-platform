from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_evidence_recovery_durable_read_reauthorized_renewal_health_qualification import (
    _completed_s,
    _qualify_t,
    _request_t,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import _independent_admin
from tests.test_evidence_recovery_restore_rehearsal import (
    _RecoveryRestoreS3Handler,
    _fake_s3,
)


def setup_function() -> None:
    reset_database()


def test_phase_t_route_drift_after_request_invalidates_second_approval(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_s(monkeypatch, tmp_path, endpoint, slug="phase-t-route-drift")
        requested = _request_t(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-t-route-drift-qualifier")

        with TestingSessionLocal() as db:
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"], document_id=data["document_id"]
            ).one()
            route.route_version += 1
            route.changed_at = datetime.now(UTC)
            db.commit()

        invalidated = _qualify_t(data, qualification_id, headers=qualifier_headers)
        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["qualification"]["status"] == "invalidated"
        assert invalidated.json()["qualification"]["routable_authority_created"] is False
        assert invalidated.json()["qualification"]["write_path_switched"] is False
        assert invalidated.json()["qualification"]["authoritative_storage_changed"] is False

        with TestingSessionLocal() as db:
            stored = db.get(
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
                UUID(qualification_id),
            )
            assert stored is not None and stored.status == "invalidated"


def test_phase_t_replica_tamper_after_request_invalidates_second_approval(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        data = _completed_s(monkeypatch, tmp_path, endpoint, slug="phase-t-replica-tamper")
        requested = _request_t(data)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["qualification"]["id"]
        _, qualifier_headers = _independent_admin(data, slug="phase-t-replica-tamper-qualifier")

        original_remote = _RecoveryRestoreS3Handler.objects[data["remote_key"]]
        _RecoveryRestoreS3Handler.objects[data["remote_key"]] = (
            b"tampered-phase-t-replica-payload",
            original_remote[1],
        )
        try:
            invalidated = _qualify_t(data, qualification_id, headers=qualifier_headers)
        finally:
            _RecoveryRestoreS3Handler.objects[data["remote_key"]] = original_remote

        assert invalidated.status_code == 200, invalidated.text
        assert invalidated.json()["outcome"] == "invalidated"
        assert invalidated.json()["qualification"]["status"] == "invalidated"
        assert invalidated.json()["qualification"]["read_path_switched"] is False
        assert invalidated.json()["qualification"]["document_storage_key_mutated"] is False
        assert invalidated.json()["qualification"]["destructive_action_performed"] is False
