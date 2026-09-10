from pathlib import Path
from uuid import UUID

from app.modules.documents import recovery_durable_read_promotion_service
from app.modules.documents.recovery_durable_read_promotion_models import (
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import (
    EvidenceRecoveryReadPathRoute,
)
from app.modules.documents.recovery_routable_read_cutover_service import (
    RecoveryRoutableReadCutoverUnavailable,
)
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_evidence_recovery_durable_read_promotion_authorization import (
    _approve_l,
    _qualified_k_real_j_cycles,
    _request_l,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3


def setup_function() -> None:
    reset_database()


def test_transient_candidate_storage_outage_is_503_and_keeps_authorization_pending(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _qualified_k_real_j_cycles(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="durable-read-auth-transient-outage",
        )
        requested = _request_l(data)
        assert requested.status_code == 201, requested.text
        authorization_id = requested.json()["authorization"]["id"]

        monkeypatch.setattr(
            recovery_durable_read_promotion_service,
            "_read_verified_candidate",
            lambda replica: (_ for _ in ()).throw(
                RecoveryRoutableReadCutoverUnavailable(
                    "Recovery candidate storage is temporarily unavailable"
                )
            ),
        )

        unavailable = _approve_l(data, authorization_id)
        assert unavailable.status_code == 503, unavailable.text

        with TestingSessionLocal() as db:
            authorization = db.get(
                EvidenceRecoveryDurableReadPromotionAuthorization,
                UUID(authorization_id),
            )
            assert authorization is not None
            assert authorization.status == "pending_second_approval"
            assert authorization.approved_by_id is None
            assert authorization.terminal_at is None
            assert (
                db.query(EvidenceRecoveryDurableReadPromotionAuthorizationReceipt)
                .filter_by(authorization_id=UUID(authorization_id))
                .count()
                == 1
            )
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                organization_id=data["org_id"],
                document_id=data["document_id"],
            ).one()
            assert route.route_class == "local_source"
            assert route.active_lease_id is None
            assert route.active_replica_id is None
            assert route.read_path_switched is False
