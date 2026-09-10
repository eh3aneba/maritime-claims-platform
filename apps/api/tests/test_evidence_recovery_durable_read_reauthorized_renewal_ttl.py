from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.documents.recovery_durable_read_renewal_reauthorization_models import (
    EvidenceRecoveryDurableReadRenewalReauthorization,
)
from app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalLease,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_reauthorized_renewal_routing import (
    _activate_happy_s,
    _approved_r,
    _rollback_s,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3


def setup_function() -> None:
    reset_database()


def test_phase_r_consumption_expiry_does_not_end_already_active_phase_s_route(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Phase R is an activation admission TTL; Phase S owns its runtime TTL after activation."""
    with _fake_s3() as endpoint:
        data = _approved_r(monkeypatch, tmp_path, endpoint, slug="phase-s-r-ttl-separation")
        lease_id, activator_headers = _activate_happy_s(
            data,
            slug="phase-s-r-ttl-separation",
        )

        with TestingSessionLocal() as db:
            reauthorization = db.get(
                EvidenceRecoveryDurableReadRenewalReauthorization,
                UUID(data["phase_r_reauthorization_id"]),
            )
            lease = db.get(
                EvidenceRecoveryDurableReadReauthorizedRenewalLease,
                UUID(lease_id),
            )
            assert reauthorization is not None and lease is not None
            assert lease.status == "activated"
            assert lease.route_expires_at is not None
            route_expires_at = lease.route_expires_at
            if route_expires_at.tzinfo is None:
                route_expires_at = route_expires_at.replace(tzinfo=UTC)
            assert route_expires_at > datetime.now(UTC)

            reauthorization.authorization_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        download = client.get(
            f"/api/v1/claims/{data['claim_id']}/documents/{data['document_id']}/download",
            headers=data["manager_headers"],
        )
        assert download.status_code == 200, download.text
        assert download.headers["X-MCRI-Evidence-Read-Source"] == (
            "recovery-replica-durable-reauthorized-renewal"
        )

        rolled_back = _rollback_s(data, lease_id, headers=activator_headers)
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["outcome"] == "rolled_back"
