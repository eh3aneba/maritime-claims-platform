import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.modules.documents import recovery_routable_read_cutover_service
from app.modules.documents.recovery_routable_read_cutover_models import (
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathCutoverReceipt,
    EvidenceRecoveryReadPathRoute,
)
from app.modules.documents.recovery_routable_read_cutover_service import (
    RoutableReadCutoverSnapshot,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3
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


def test_qualification_consumes_two_distinct_j_prepare_activate_rollback_cycles(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Exercise the J state machine twice before requesting K qualification.

    The first cycle uses the complete A-through-I recovery chain. For the second
    cycle only the upstream Phase-I authorization snapshot boundary is stubbed;
    Phase J itself still performs its real prepare, activation, route mutation,
    receipt generation and rollback behavior. This keeps the test focused on
    K's repeated-J evidence contract without weakening J production controls.
    """
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
            approver_headers,
            third_headers,
            _shadow_id,
            first_authorization_id,
        ) = _approved_read_path_authorization(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="read-qualification-two-j-cycles",
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
        assert first_activated.json()["outcome"] == "activated"
        first_rolled_back = _rollback_cutover(
            claim_id,
            document_id,
            first_lease_id,
            admin_headers,
        )
        assert first_rolled_back.status_code == 200, first_rolled_back.text
        assert first_rolled_back.json()["outcome"] == "rolled_back"

        with TestingSessionLocal() as db:
            first = db.get(EvidenceRecoveryReadPathCutoverLease, UUID(first_lease_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                document_id=document_id
            ).one()
            assert first is not None
            assert first.authorization_approved_by_id is not None
            assert route.route_class == "local_source"
            assert route.active_lease_id is None
            first_route_version = route.route_version

            second_authorization_id = uuid4()
            second_snapshot = RoutableReadCutoverSnapshot(
                authorization_id=second_authorization_id,
                authorization_approval_receipt_id=uuid4(),
                replica_id=first.replica_id,
                authorization_hash=_digest("second-j-authorization"),
                authorization_request_snapshot_hash=_digest("second-j-auth-request"),
                authorization_approval_receipt_hash=_digest("second-j-auth-receipt"),
                execution_transition_proof_hash=_digest("second-j-execution-proof"),
                replica_hash=first.replica_hash,
                source_file_hash=first.source_file_hash,
                source_file_size_bytes=first.source_file_size_bytes,
                recovery_bucket_fingerprint=first.recovery_bucket_fingerprint,
                candidate_storage_key_fingerprint=first.candidate_storage_key_fingerprint,
                source_authority_fingerprint=first.source_authority_fingerprint,
                candidate_authority_fingerprint=first.candidate_authority_fingerprint,
                configuration_fingerprint=first.configuration_fingerprint,
                lease_snapshot_hash=_digest("second-j-lease-snapshot"),
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
        assert second_prepared.json()["outcome"] == "prepared"
        second_lease_id = second_prepared.json()["lease"]["id"]
        assert second_lease_id != first_lease_id

        second_activated = _activate_cutover(
            claim_id,
            document_id,
            second_lease_id,
            third_headers,
        )
        assert second_activated.status_code == 200, second_activated.text
        assert second_activated.json()["outcome"] == "activated"
        assert second_activated.json()["route"]["route_class"] == "recovery_replica"

        second_rolled_back = _rollback_cutover(
            claim_id,
            document_id,
            second_lease_id,
            admin_headers,
        )
        assert second_rolled_back.status_code == 200, second_rolled_back.text
        assert second_rolled_back.json()["outcome"] == "rolled_back"
        assert second_rolled_back.json()["route"]["route_class"] == "local_source"

        requested = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-routable-read-qualification",
            headers=admin_headers,
            json={
                "cutover_lease_ids": [first_lease_id, second_lease_id],
                "reason": "Qualify two actual Phase J lifecycle cutovers after verified rollback.",
            },
        )
        assert requested.status_code == 201, requested.text
        assert requested.json()["outcome"] == "pending_second_approval"
        qualification_id = requested.json()["qualification"]["id"]

        qualified = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-routable-read-qualifications/{qualification_id}/qualify",
            headers=approver_headers,
            json={
                "reason": "Independently confirm the repeated Phase J rollback evidence is intact."
            },
        )
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["outcome"] == "qualified"
        assert qualified.json()["qualification"]["successful_cycle_count"] == 2
        assert qualified.json()["qualification"]["read_path_switched"] is False

        with TestingSessionLocal() as db:
            first = db.get(EvidenceRecoveryReadPathCutoverLease, UUID(first_lease_id))
            second = db.get(EvidenceRecoveryReadPathCutoverLease, UUID(second_lease_id))
            route = db.query(EvidenceRecoveryReadPathRoute).filter_by(
                document_id=document_id
            ).one()
            assert first is not None and second is not None
            assert first.status == "rolled_back"
            assert second.status == "rolled_back"
            assert first.authorization_id != second.authorization_id
            assert first.replica_id == second.replica_id
            assert route.route_class == "local_source"
            assert route.active_lease_id is None
            assert route.active_replica_id is None
            assert route.read_path_switched is False
            assert route.route_version == first_route_version + 2

            first_receipts = db.query(EvidenceRecoveryReadPathCutoverReceipt).filter_by(
                cutover_lease_id=UUID(first_lease_id)
            ).all()
            second_receipts = db.query(EvidenceRecoveryReadPathCutoverReceipt).filter_by(
                cutover_lease_id=UUID(second_lease_id)
            ).all()
            assert {item.phase for item in first_receipts} == {
                "prepared",
                "activated",
                "rolled_back",
            }
            assert {item.phase for item in second_receipts} == {
                "prepared",
                "activated",
                "rolled_back",
            }
