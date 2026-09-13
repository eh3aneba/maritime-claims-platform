from pathlib import Path
from uuid import UUID, uuid4

from app.modules.claims import retention_physical_disposal_closure_service as closure_service
from app.modules.claims.retention_physical_disposal_closure_models import (
    PhysicalDisposalClosureQualification,
    PhysicalDisposalClosureReceipt,
)
from app.modules.claims.retention_physical_disposal_execution_models import (
    PhysicalDisposalExecutionReceipt,
)
from app.modules.documents.models import Document
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import (
    _independent_admin,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3
from tests.test_retention_physical_disposal_execution import (
    _authorized_phase_17_4_a,
    _execute,
)


def setup_function() -> None:
    reset_database()


REQUEST_REASON = (
    "Independently request exact post-disposal closure verification for the completed bounded execution."
)
QUALIFY_REASON = (
    "Independently confirm local absence, durable recovery authority, byte integrity and preserved metadata."
)


def _completed_phase_b(monkeypatch, tmp_path: Path, endpoint: str, *, slug: str):
    data = _authorized_phase_17_4_a(
        monkeypatch,
        tmp_path,
        endpoint,
        slug=slug,
    )
    local_bytes = data["local_path"].read_bytes()
    executed = _execute(data, uuid4())
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["status"] == "succeeded"
    assert body["recovery_bytes_preserved"] is True
    assert not data["local_path"].exists()
    data["execution_id"] = body["id"]
    data["local_bytes"] = local_bytes
    return data


def _request_closure(data, *, headers, reason: str = REQUEST_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/physical-disposal-executions/"
        f"{data['execution_id']}/closure-qualification",
        headers=headers,
        json={"reason": reason},
    )


def _qualify_closure(data, qualification_id: str, *, headers, reason: str = QUALIFY_REASON):
    return client.post(
        f"/api/v1/claims/{data['claim_id']}/physical-disposal-closures/"
        f"{qualification_id}/qualify",
        headers=headers,
        json={"reason": reason},
    )


def test_phase_17_4_c_independently_qualifies_post_disposal_closure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_phase_b(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="phase-17-4-c-success",
        )
        requester_id, requester_headers = _independent_admin(
            data, slug="phase-17-4-c-requester"
        )
        qualifier_id, qualifier_headers = _independent_admin(
            data, slug="phase-17-4-c-qualifier"
        )

        requested = _request_closure(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        requested_body = requested.json()
        qualification_id = requested_body["id"]
        assert requested_body["status"] == "pending_second_approval"
        assert requested_body["requested_by_id"] == str(requester_id)
        assert requested_body["document_count"] == 1
        assert requested_body["observed_local_targets_absent"] is True
        assert requested_body["observed_recovery_bytes_healthy"] is True
        assert requested_body["observed_document_rows_preserved"] is True
        assert requested_body["observed_storage_keys_preserved"] is True
        assert requested_body["observed_authority_kind"] == "recovery_storage"
        assert requested_body["observed_authority_tenure"] == "durable_recovery"
        assert len(requested_body["verification_snapshot_hash"]) == 64
        assert len(requested_body["closure_qualification_hash"]) == 64
        assert requested_body["destructive_action_performed"] is False
        assert requested_body["storage_write_performed"] is False
        assert requested_body["route_mutation_performed"] is False
        assert requested_body["local_delete_performed"] is False
        assert requested_body["s3_delete_performed"] is False

        self_qualification = _qualify_closure(
            data,
            qualification_id,
            headers=requester_headers,
        )
        assert self_qualification.status_code == 409, self_qualification.text

        executor_qualification = _qualify_closure(
            data,
            qualification_id,
            headers=data["executor_headers"],
        )
        assert executor_qualification.status_code == 409, executor_qualification.text
        assert "independent" in executor_qualification.text.lower()

        qualified = _qualify_closure(
            data,
            qualification_id,
            headers=qualifier_headers,
        )
        assert qualified.status_code == 200, qualified.text
        body = qualified.json()
        assert body["status"] == "qualified"
        assert body["qualified_by_id"] == str(qualifier_id)
        assert len(body["decision_hash"]) == 64
        assert body["destructive_action_performed"] is False
        assert body["storage_write_performed"] is False
        assert body["route_mutation_performed"] is False
        assert body["ownership_mutation_performed"] is False
        assert body["physical_disposal_authorized"] is False
        assert body["local_delete_performed"] is False
        assert body["s3_delete_performed"] is False
        assert not data["local_path"].exists()

        replay = _qualify_closure(
            data,
            qualification_id,
            headers=qualifier_headers,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["decision_hash"] == body["decision_hash"]

        receipts = client.get(
            f"/api/v1/claims/{data['claim_id']}/physical-disposal-closures/"
            f"{qualification_id}/receipts",
            headers=qualifier_headers,
        )
        assert receipts.status_code == 200, receipts.text
        rows = receipts.json()
        assert [row["event_type"] for row in rows] == ["requested", "qualified"]
        assert [row["sequence_number"] for row in rows] == [1, 2]
        assert rows[0]["prior_receipt_hash"] is None
        assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
        assert all(row["destructive_action_performed"] is False for row in rows)
        assert all(row["storage_write_performed"] is False for row in rows)
        assert all(row["local_delete_performed"] is False for row in rows)
        assert all(row["s3_delete_performed"] is False for row in rows)

        with TestingSessionLocal() as db:
            qualification = db.get(
                PhysicalDisposalClosureQualification,
                UUID(qualification_id),
            )
            document = db.get(Document, data["document_id"])
            receipt_count = db.query(PhysicalDisposalClosureReceipt).count()
            assert qualification is not None and qualification.status == "qualified"
            assert document is not None
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert receipt_count == 2


def test_phase_17_4_c_recovery_outage_is_retryable_and_pending_survives(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_phase_b(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="phase-17-4-c-outage",
        )
        _, requester_headers = _independent_admin(
            data, slug="phase-17-4-c-outage-requester"
        )
        _, qualifier_headers = _independent_admin(
            data, slug="phase-17-4-c-outage-qualifier"
        )
        requested = _request_closure(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["id"]

        original_read = closure_service._read_verified_candidate

        def _temporary_outage(*_args, **_kwargs):
            raise RuntimeError("Temporary recovery endpoint unavailable")

        monkeypatch.setattr(
            closure_service,
            "_read_verified_candidate",
            _temporary_outage,
        )
        unavailable = _qualify_closure(
            data,
            qualification_id,
            headers=qualifier_headers,
        )
        assert unavailable.status_code == 503, unavailable.text
        assert not data["local_path"].exists()

        with TestingSessionLocal() as db:
            qualification = db.get(
                PhysicalDisposalClosureQualification,
                UUID(qualification_id),
            )
            receipts = db.query(PhysicalDisposalClosureReceipt).all()
            assert qualification is not None
            assert qualification.status == "pending_second_approval"
            assert len(receipts) == 1
            assert receipts[0].event_type == "requested"

        monkeypatch.setattr(
            closure_service,
            "_read_verified_candidate",
            original_read,
        )
        qualified = _qualify_closure(
            data,
            qualification_id,
            headers=qualifier_headers,
        )
        assert qualified.status_code == 200, qualified.text
        assert qualified.json()["status"] == "qualified"


def test_phase_17_4_c_local_target_reappearance_fails_closed_without_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_phase_b(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="phase-17-4-c-reappearance",
        )
        _, requester_headers = _independent_admin(
            data, slug="phase-17-4-c-reappearance-requester"
        )
        _, qualifier_headers = _independent_admin(
            data, slug="phase-17-4-c-reappearance-qualifier"
        )
        requested = _request_closure(data, headers=requester_headers)
        assert requested.status_code == 201, requested.text
        qualification_id = requested.json()["id"]

        data["local_path"].parent.mkdir(parents=True, exist_ok=True)
        data["local_path"].write_bytes(data["local_bytes"])
        assert data["local_path"].exists()

        blocked = _qualify_closure(
            data,
            qualification_id,
            headers=qualifier_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert "reappeared" in blocked.text.lower()
        assert data["local_path"].read_bytes() == data["local_bytes"]

        with TestingSessionLocal() as db:
            qualification = db.get(
                PhysicalDisposalClosureQualification,
                UUID(qualification_id),
            )
            document = db.get(Document, data["document_id"])
            assert qualification is not None
            assert qualification.status == "pending_second_approval"
            assert document is not None
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None


def test_phase_17_4_c_rejects_tampered_phase_b_receipt_chain(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _completed_phase_b(
            monkeypatch,
            tmp_path,
            endpoint,
            slug="phase-17-4-c-tamper",
        )
        _, requester_headers = _independent_admin(
            data, slug="phase-17-4-c-tamper-requester"
        )
        with TestingSessionLocal() as db:
            terminal = (
                db.query(PhysicalDisposalExecutionReceipt)
                .filter(
                    PhysicalDisposalExecutionReceipt.execution_id
                    == UUID(data["execution_id"])
                )
                .order_by(PhysicalDisposalExecutionReceipt.sequence_number.desc())
                .first()
            )
            assert terminal is not None
            terminal.receipt_hash = "0" * 64
            db.commit()

        blocked = _request_closure(data, headers=requester_headers)
        assert blocked.status_code == 409, blocked.text
        assert "integrity" in blocked.text.lower()
        assert not data["local_path"].exists()
        with TestingSessionLocal() as db:
            assert db.query(PhysicalDisposalClosureQualification).count() == 0
