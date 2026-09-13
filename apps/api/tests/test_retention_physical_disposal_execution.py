from pathlib import Path
from uuid import UUID, uuid4

from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorization,
)
from app.modules.claims.retention_physical_disposal_execution_models import (
    PhysicalDisposalExecution,
    PhysicalDisposalExecutionItem,
    PhysicalDisposalExecutionReceipt,
)
from app.modules.claims import retention_physical_disposal_execution_service as phase_17_4_b_service
from app.modules.claims.retention_physical_disposal_execution_service import (
    PhysicalDisposalExecutionRetryableError,
)
from app.modules.documents import service as document_service
from app.modules.documents.models import Document
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import (
    _independent_admin,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3
from tests.test_retention_physical_disposal_authorization import (
    _prepare_real_phase_17_4_a_chain,
)


def setup_function() -> None:
    reset_database()


def _authorized_phase_17_4_a(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    # The upstream recovery-chain fixture seeds the local evidence under tmp_path.
    # Phase 17.4-B deliberately resolves the destructive target through the live
    # document-storage configuration, so align that runtime root with the seeded
    # evidence instead of bypassing the production storage boundary in the test.
    monkeypatch.setattr(document_service.settings, "storage_backend", "local")
    monkeypatch.setattr(document_service.settings, "local_storage_path", str(tmp_path))

    data = _prepare_real_phase_17_4_a_chain(monkeypatch, tmp_path, endpoint)
    requested = client.post(
        f"/api/v1/claims/{data['claim_id']}/disposal-release-reviews/"
        f"{data['release_review_id']}/physical-disposal-admission",
        headers=data["admission_requester_headers"],
        json={"reason": f"Create exact Phase 17.4-A admission for {slug}."},
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]

    approved = client.post(
        f"/api/v1/claims/{data['claim_id']}/physical-disposal-admissions/"
        f"{authorization_id}/approve",
        headers=data["admission_approver_headers"],
        json={"reason": f"Independently approve exact Phase 17.4-A admission for {slug}."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "authorized"

    executor_id, executor_headers = _independent_admin(data, slug=f"{slug}-executor")
    data.update(
        {
            "authorization_id": authorization_id,
            "executor_id": executor_id,
            "executor_headers": executor_headers,
        }
    )
    return data


def _execute(data, request_id, *, headers=None, reason="Execute exact bounded local physical disposal."):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/physical-disposal-admissions/"
        f"{data['authorization_id']}/execute",
        headers=headers or data["executor_headers"],
        json={"request_id": str(request_id), "reason": reason},
    )


def test_phase_17_4_b_executes_exact_local_disposal_and_replay_is_unchanged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _authorized_phase_17_4_a(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="phase-17-4-b-success",
        )
        assert data["local_path"].exists()
        request_id = uuid4()

        executed = _execute(data, request_id)
        assert executed.status_code == 200, executed.text
        body = executed.json()
        execution_id = body["id"]
        assert body["status"] == "succeeded"
        assert body["document_count"] == 1
        assert body["deleted_count"] == 1
        assert body["destructive_action_performed"] is True
        assert body["local_delete_performed"] is True
        assert body["s3_delete_performed"] is False
        assert body["recovery_bytes_preserved"] is True
        assert body["document_row_deleted"] is False
        assert body["document_storage_key_mutated"] is False
        assert len(body["execution_hash"]) == 64
        assert len(body["items"]) == 1
        assert body["items"][0]["status"] == "verified"
        assert body["items"][0]["local_deleted"] is True
        assert body["items"][0]["local_absent_after"] is True
        assert body["items"][0]["recovery_verified_before"] is True
        assert body["items"][0]["recovery_verified_after"] is True
        assert body["items"][0]["s3_delete_performed"] is False
        assert not data["local_path"].exists()

        replay = _execute(data, request_id)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == execution_id
        assert replay.json()["execution_hash"] == body["execution_hash"]
        assert replay.json()["deleted_count"] == 1

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/physical-disposal-executions/"
            f"{execution_id}/receipts",
            headers=data["executor_headers"],
        )
        assert receipts.status_code == 200, receipts.text
        receipt_rows = receipts.json()
        assert [row["event_type"] for row in receipt_rows] == [
            "prepared",
            "local_deleted",
            "succeeded",
        ]
        assert [row["sequence_number"] for row in receipt_rows] == [1, 2, 3]
        assert receipt_rows[0]["prior_receipt_hash"] is None
        assert receipt_rows[1]["prior_receipt_hash"] == receipt_rows[0]["receipt_hash"]
        assert receipt_rows[2]["prior_receipt_hash"] == receipt_rows[1]["receipt_hash"]
        assert all(row["s3_delete_performed"] is False for row in receipt_rows)
        assert all(row["document_row_deleted"] is False for row in receipt_rows)
        assert all(row["document_storage_key_mutated"] is False for row in receipt_rows)

        with TestingSessionLocal() as db:
            authorization = db.get(
                PhysicalDisposalAdmissionAuthorization,
                UUID(data["authorization_id"]),
            )
            document = db.get(Document, data["document_id"])
            execution = db.get(PhysicalDisposalExecution, UUID(execution_id))
            assert authorization is not None and document is not None and execution is not None
            assert authorization.status == "consumed"
            assert authorization.execution_count == 1
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert execution.executor_id == data["executor_id"]


def test_phase_17_4_b_prior_governance_actor_is_blocked_before_any_delete(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _authorized_phase_17_4_a(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="phase-17-4-b-separation",
        )
        local_before = data["local_path"].read_bytes()

        denied = _execute(
            data,
            uuid4(),
            headers=data["admission_approver_headers"],
            reason="Attempt execution with a prior material governance actor.",
        )
        assert denied.status_code == 409, denied.text
        assert "independent" in denied.text.lower()
        assert data["local_path"].read_bytes() == local_before

        with TestingSessionLocal() as db:
            execution_count = db.query(PhysicalDisposalExecution).count()
            item_count = db.query(PhysicalDisposalExecutionItem).count()
            receipt_count = db.query(PhysicalDisposalExecutionReceipt).count()
            authorization = db.get(
                PhysicalDisposalAdmissionAuthorization,
                UUID(data["authorization_id"]),
            )
            assert execution_count == 0
            assert item_count == 0
            assert receipt_count == 0
            assert authorization is not None
            assert authorization.status == "authorized"
            assert authorization.execution_count == 0


def test_phase_17_4_b_post_delete_recovery_outage_resumes_same_execution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _authorized_phase_17_4_a(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="phase-17-4-b-resume",
        )
        request_id = uuid4()
        original_verify = phase_17_4_b_service._verify_recovery_only_after_delete

        def _temporary_recovery_outage(*_args, **_kwargs):
            raise PhysicalDisposalExecutionRetryableError(
                "Temporary recovery endpoint unavailable after local delete"
            )

        monkeypatch.setattr(
            phase_17_4_b_service,
            "_verify_recovery_only_after_delete",
            _temporary_recovery_outage,
        )
        interrupted = _execute(data, request_id)
        assert interrupted.status_code == 503, interrupted.text
        assert not data["local_path"].exists()

        with TestingSessionLocal() as db:
            execution = db.query(PhysicalDisposalExecution).one()
            item = db.query(PhysicalDisposalExecutionItem).one()
            receipts = (
                db.query(PhysicalDisposalExecutionReceipt)
                .order_by(PhysicalDisposalExecutionReceipt.sequence_number.asc())
                .all()
            )
            assert execution.status == "partial"
            assert execution.deleted_count == 1
            assert execution.local_delete_performed is True
            assert execution.destructive_action_performed is True
            assert item.status == "deleted"
            assert item.local_deleted is True
            assert item.recovery_verified_after is False
            assert [receipt.event_type for receipt in receipts] == ["prepared", "local_deleted"]

        monkeypatch.setattr(
            phase_17_4_b_service,
            "_verify_recovery_only_after_delete",
            original_verify,
        )
        resumed = _execute(data, request_id)
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["status"] == "succeeded"
        assert body["deleted_count"] == 1
        assert body["recovery_bytes_preserved"] is True
        assert body["items"][0]["status"] == "verified"
        assert body["items"][0]["recovery_verified_after"] is True
        assert not data["local_path"].exists()

        with TestingSessionLocal() as db:
            receipts = (
                db.query(PhysicalDisposalExecutionReceipt)
                .order_by(PhysicalDisposalExecutionReceipt.sequence_number.asc())
                .all()
            )
            authorization = db.get(
                PhysicalDisposalAdmissionAuthorization,
                UUID(data["authorization_id"]),
            )
            document = db.get(Document, data["document_id"])
            assert [receipt.event_type for receipt in receipts] == [
                "prepared",
                "local_deleted",
                "succeeded",
            ]
            assert authorization is not None and authorization.status == "consumed"
            assert authorization.execution_count == 1
            assert document is not None
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
