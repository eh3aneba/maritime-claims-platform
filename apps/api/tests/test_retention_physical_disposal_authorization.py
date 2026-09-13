from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.claims.retention_disposal_release_service import (
    RELEASE_MINIMUM_QUARANTINE_DWELL,
)
from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorization,
    PhysicalDisposalAdmissionAuthorizationReceipt,
)
from app.modules.claims import retention_physical_disposal_authorization_service as phase_17_4_a_service
from app.modules.claims.retention_physical_disposal_authorization_service import (
    PHYSICAL_DISPOSAL_ADMISSION_WINDOW,
    _actor_set_hash,
    _authorization_hash,
    _canonical_hash,
    _document_binding,
    _is_retryable_ao_error,
    _receipt_hash,
)
from app.modules.claims.retention_service import create_retention_policy
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_authoritative_storage_health_service import (
    RecoveryDurableAuthoritativeStorageHealthError,
)
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_disposal_release_review import (
    _chain_to_stage,
    _request_release,
    _set_release_clock,
    _stage_time,
)
from tests.test_evidence_recovery_durable_authoritative_storage_health import (
    _qualify_ao,
    _ratified_an,
    _request_ao,
)
from tests.test_evidence_recovery_durable_read_renewal_health_qualification import (
    _independent_admin,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3


def setup_function() -> None:
    reset_database()


def _qualification(document_id):
    return SimpleNamespace(
        id=uuid4(),
        document_id=document_id,
        health_qualification_hash="a" * 64,
        ratification_id=uuid4(),
        ratification_hash="b" * 64,
        integrity_proof_hash="c" * 64,
    )


def test_document_binding_is_exact_and_self_hashed():
    document_id = uuid4()
    row = {
        "file_hash": "d" * 64,
        "file_size_bytes": 123,
        "storage_key_fingerprint": "e" * 64,
        "row_fingerprint": "f" * 64,
    }
    binding = _document_binding(row, _qualification(document_id))

    assert binding["document_id"] == str(document_id)
    assert binding["file_hash"] == row["file_hash"]
    assert binding["file_size_bytes"] == 123
    assert binding["storage_key_fingerprint"] == row["storage_key_fingerprint"]
    assert binding["row_fingerprint"] == row["row_fingerprint"]

    unhashed = dict(binding)
    stored_hash = unhashed.pop("binding_hash")
    assert stored_hash == _canonical_hash(unhashed)


def test_binding_set_hash_detects_any_document_drift():
    first = {
        "document_id": str(uuid4()),
        "file_hash": "1" * 64,
        "file_size_bytes": 10,
        "storage_key_fingerprint": "2" * 64,
        "row_fingerprint": "3" * 64,
    }
    second = {
        "document_id": str(uuid4()),
        "file_hash": "4" * 64,
        "file_size_bytes": 20,
        "storage_key_fingerprint": "5" * 64,
        "row_fingerprint": "6" * 64,
    }
    original = _canonical_hash([first, second])
    changed = dict(second)
    changed["file_hash"] = "7" * 64

    assert original != _canonical_hash([first, changed])


def test_actor_set_hash_is_order_independent_and_deduplicated():
    first = uuid4()
    second = uuid4()

    assert _actor_set_hash([first, second, first, None]) == _actor_set_hash([second, first])
    assert _actor_set_hash([first, second]) != _actor_set_hash([first])


def test_authorization_hash_binds_single_use_and_actor_separation_boundary():
    requested_at = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
    expires_at = requested_at + timedelta(minutes=5)
    values = dict(
        release_review_id=uuid4(),
        release_review_hash="1" * 64,
        release_approval_hash="2" * 64,
        manifest_hash="3" * 64,
        inventory_hash="4" * 64,
        document_bindings_hash="5" * 64,
        separation_actor_set_hash="6" * 64,
        requested_by_id=uuid4(),
        request_reason="Approve bounded physical disposal admission",
        requested_at=requested_at,
        authorization_expires_at=expires_at,
    )
    baseline = _authorization_hash(**values)
    changed = dict(values)
    changed["document_bindings_hash"] = "7" * 64
    actor_changed = dict(values)
    actor_changed["separation_actor_set_hash"] = "8" * 64

    assert baseline != _authorization_hash(**changed)
    assert baseline != _authorization_hash(**actor_changed)


def test_recovery_store_outage_is_retryable_but_lineage_failure_is_not():
    outage = RecoveryDurableAuthoritativeStorageHealthError(
        "Unable to inspect durable recovery evidence: endpoint timed out"
    )
    stale = RecoveryDurableAuthoritativeStorageHealthError(
        "Phase AN ratification lineage is inconsistent"
    )

    assert _is_retryable_ao_error(outage) is True
    assert _is_retryable_ao_error(stale) is False


def test_receipt_hash_is_append_only_chain_bound():
    occurred_at = datetime(2026, 9, 13, 8, 1, tzinfo=timezone.utc)
    authorization = SimpleNamespace(
        id=uuid4(),
        authorization_hash="a" * 64,
        document_bindings_hash="b" * 64,
        separation_actor_set_hash="c" * 64,
        approval_hash=None,
    )
    actor_id = uuid4()
    first = _receipt_hash(
        authorization=authorization,
        sequence_number=1,
        event_type="requested",
        status_after="pending_second_approval",
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason="Create bounded admission credential",
        prior_receipt_hash=None,
    )
    second = _receipt_hash(
        authorization=authorization,
        sequence_number=2,
        event_type="invalidated",
        status_after="invalidated",
        actor_id=actor_id,
        occurred_at=occurred_at + timedelta(seconds=1),
        reason="Governance drift",
        prior_receipt_hash=first,
    )
    changed_chain = _receipt_hash(
        authorization=authorization,
        sequence_number=2,
        event_type="invalidated",
        status_after="invalidated",
        actor_id=actor_id,
        occurred_at=occurred_at + timedelta(seconds=1),
        reason="Governance drift",
        prior_receipt_hash="d" * 64,
    )

    assert first != second
    assert second != changed_chain


def test_models_hard_block_destructive_actions_and_receipt_rewrites():
    authorization_constraints = {
        constraint.name
        for constraint in PhysicalDisposalAdmissionAuthorization.__table__.constraints
        if constraint.name
    }
    receipt_constraints = {
        constraint.name
        for constraint in PhysicalDisposalAdmissionAuthorizationReceipt.__table__.constraints
        if constraint.name
    }

    assert "ck_physical_disposal_admission_single_use" in authorization_constraints
    assert "ck_physical_disposal_admission_four_eyes" in authorization_constraints
    assert "ck_physical_disposal_admission_no_destructive_action" in authorization_constraints
    assert "ck_physical_disposal_admission_no_storage_write" in authorization_constraints
    assert "ck_physical_disposal_admission_no_s3_delete" in authorization_constraints
    assert "ck_physical_disposal_admission_no_local_delete" in authorization_constraints
    assert "ck_pd_adm_receipt_chain" in receipt_constraints
    assert "ck_pd_adm_receipt_status_mapping" in receipt_constraints
    assert "ck_pd_adm_receipt_no_destructive_action" in receipt_constraints


def _prepare_real_phase_17_4_a_chain(monkeypatch, tmp_path: Path, endpoint: str):
    data = _ratified_an(monkeypatch, tmp_path, endpoint, slug="phase-17-4-a-e2e")

    ao_requester_id, ao_requester_headers = _independent_admin(
        data, slug="phase-17-4-a-ao-requester"
    )
    ao_qualifier_id, ao_qualifier_headers = _independent_admin(
        data, slug="phase-17-4-a-ao-qualifier"
    )
    ao_requested = _request_ao(data, headers=ao_requester_headers)
    assert ao_requested.status_code == 201, ao_requested.text
    ao_qualification_id = ao_requested.json()["qualification"]["id"]
    ao_qualified = _qualify_ao(
        data,
        ao_qualification_id,
        headers=ao_qualifier_headers,
    )
    assert ao_qualified.status_code == 200, ao_qualified.text
    assert ao_qualified.json()["outcome"] == "qualified"

    disposal_requester_id, _ = _independent_admin(data, slug="phase-17-4-a-disposal-requester")
    stage_creator_id, _ = _independent_admin(data, slug="phase-17-4-a-stage-creator")
    release_approver_id, release_approver_headers = _independent_admin(
        data, slug="phase-17-4-a-release-approver"
    )
    admission_requester_id, admission_requester_headers = _independent_admin(
        data, slug="phase-17-4-a-admission-requester"
    )
    admission_approver_id, admission_approver_headers = _independent_admin(
        data, slug="phase-17-4-a-admission-approver"
    )

    old_anchor = datetime.now(timezone.utc) - timedelta(days=120)
    with TestingSessionLocal() as db:
        claim = db.get(Claim, data["claim_id"])
        document = db.get(Document, data["document_id"])
        assert claim is not None and document is not None
        claim.created_at = old_anchor
        claim.updated_at = old_anchor
        document.created_at = old_anchor
        document.updated_at = old_anchor
        create_retention_policy(
            db,
            organization_id=data["org_id"],
            closed_claim_retention_days=30,
            evidence_retention_days=30,
            enabled=True,
            disposal_enabled=True,
            created_by_id=disposal_requester_id,
        )
        db.commit()

    stage_id, disposal_requester_headers, stage_creator_headers = _chain_to_stage(
        data["claim_id"],
        disposal_requester_id,
        stage_creator_id,
    )
    eligible_at = (
        _stage_time(stage_id)
        + RELEASE_MINIMUM_QUARANTINE_DWELL
        + timedelta(seconds=1)
    )
    _set_release_clock(monkeypatch, eligible_at)
    release_requested = _request_release(
        data["claim_id"],
        stage_id,
        disposal_requester_headers,
    )
    assert release_requested.status_code == 201, release_requested.text
    release_review_id = release_requested.json()["id"]

    approval_time = eligible_at + timedelta(seconds=10)
    _set_release_clock(monkeypatch, approval_time)
    release_approved = client.post(
        f"/api/v1/claims/{data['claim_id']}/disposal-release-reviews/{release_review_id}/approve",
        headers=release_approver_headers,
        json={"reason": "Independently approve the exact final release snapshot before admission."},
    )
    assert release_approved.status_code == 200, release_approved.text
    assert release_approved.json()["status"] == "approved"

    admission_now = approval_time + timedelta(seconds=1)
    monkeypatch.setattr(phase_17_4_a_service, "_utc_now", lambda: admission_now)
    data.update(
        {
            "phase_ao_qualification_id": ao_qualification_id,
            "phase_ao_requester_id": ao_requester_id,
            "phase_ao_qualifier_id": ao_qualifier_id,
            "disposal_requester_id": disposal_requester_id,
            "disposal_requester_headers": disposal_requester_headers,
            "stage_creator_id": stage_creator_id,
            "stage_creator_headers": stage_creator_headers,
            "release_approver_id": release_approver_id,
            "release_approver_headers": release_approver_headers,
            "release_review_id": release_review_id,
            "admission_requester_id": admission_requester_id,
            "admission_requester_headers": admission_requester_headers,
            "admission_approver_id": admission_approver_id,
            "admission_approver_headers": admission_approver_headers,
            "admission_now": admission_now,
        }
    )
    return data


def test_phase_17_4_a_real_chain_authorizes_bounded_non_destructive_admission(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _fake_s3() as endpoint:
        data = _prepare_real_phase_17_4_a_chain(monkeypatch, tmp_path, endpoint)
        local_before = data["local_path"].read_bytes()

        requested = client.post(
            f"/api/v1/claims/{data['claim_id']}/disposal-release-reviews/"
            f"{data['release_review_id']}/physical-disposal-admission",
            headers=data["admission_requester_headers"],
            json={"reason": "Create the bounded one-use physical-disposal admission credential."},
        )
        assert requested.status_code == 201, requested.text
        body = requested.json()
        authorization_id = body["id"]
        assert body["status"] == "pending_second_approval"
        assert body["requested_by_id"] == str(data["admission_requester_id"])
        assert body["physical_disposal_authorized"] is False
        assert body["max_execution_count"] == 1
        assert body["execution_count"] == 0
        assert body["document_count"] == 1
        assert len(body["document_bindings"]) == 1
        assert body["document_bindings"][0]["document_id"] == str(data["document_id"])
        assert len(body["document_bindings_hash"]) == 64
        assert len(body["authorization_hash"]) == 64
        assert body["destructive_action_performed"] is False
        assert body["storage_write_performed"] is False
        assert body["s3_delete_performed"] is False
        assert body["local_delete_performed"] is False
        expires_at = datetime.fromisoformat(body["authorization_expires_at"])
        assert expires_at <= data["admission_now"] + PHYSICAL_DISPOSAL_ADMISSION_WINDOW

        self_approval = client.post(
            f"/api/v1/claims/{data['claim_id']}/physical-disposal-admissions/"
            f"{authorization_id}/approve",
            headers=data["admission_requester_headers"],
            json={"reason": "The admission requester must not self-approve this credential."},
        )
        assert self_approval.status_code == 409, self_approval.text

        prior_governance_actor = client.post(
            f"/api/v1/claims/{data['claim_id']}/physical-disposal-admissions/"
            f"{authorization_id}/approve",
            headers=data["release_approver_headers"],
            json={"reason": "A prior material disposal actor must remain outside approval."},
        )
        assert prior_governance_actor.status_code == 409, prior_governance_actor.text

        approved = client.post(
            f"/api/v1/claims/{data['claim_id']}/physical-disposal-admissions/"
            f"{authorization_id}/approve",
            headers=data["admission_approver_headers"],
            json={"reason": "Independently approve the bounded admission after fresh revalidation."},
        )
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["status"] == "authorized"
        assert approved_body["physical_disposal_authorized"] is True
        assert approved_body["approved_by_id"] == str(data["admission_approver_id"])
        assert approved_body["max_execution_count"] == 1
        assert approved_body["execution_count"] == 0
        assert len(approved_body["approval_hash"]) == 64
        assert approved_body["destructive_action_performed"] is False
        assert approved_body["storage_write_performed"] is False
        assert approved_body["s3_delete_performed"] is False
        assert approved_body["local_delete_performed"] is False

        replay = client.post(
            f"/api/v1/claims/{data['claim_id']}/physical-disposal-admissions/"
            f"{authorization_id}/approve",
            headers=data["admission_approver_headers"],
            json={"reason": "Independently approve the bounded admission after fresh revalidation."},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == authorization_id
        assert replay.json()["execution_count"] == 0

        with TestingSessionLocal() as db:
            stored = db.get(PhysicalDisposalAdmissionAuthorization, UUID(authorization_id))
            document = db.get(Document, data["document_id"])
            receipts = (
                db.query(PhysicalDisposalAdmissionAuthorizationReceipt)
                .filter_by(authorization_id=UUID(authorization_id))
                .order_by(PhysicalDisposalAdmissionAuthorizationReceipt.sequence_number.asc())
                .all()
            )
            assert stored is not None and document is not None
            assert stored.status == "authorized"
            assert stored.execution_count == 0
            assert stored.physical_disposal_authorized is True
            assert document.storage_key == data["storage_key"]
            assert document.deleted_at is None
            assert [receipt.event_type for receipt in receipts] == ["requested", "authorized"]
            assert [receipt.sequence_number for receipt in receipts] == [1, 2]
            assert receipts[0].prior_receipt_hash is None
            assert receipts[1].prior_receipt_hash == receipts[0].receipt_hash
            assert all(receipt.destructive_action_performed is False for receipt in receipts)
            assert all(receipt.storage_write_performed is False for receipt in receipts)
            assert all(receipt.s3_delete_performed is False for receipt in receipts)
            assert all(receipt.local_delete_performed is False for receipt in receipts)
            audit_rows = db.query(AuditLog).filter(
                AuditLog.entity_type == "physical_disposal_admission_authorization"
            ).all()
            rendered = " ".join(str(item.new_values) for item in audit_rows)
            assert data["storage_key"] not in rendered

        assert data["local_path"].read_bytes() == local_before
