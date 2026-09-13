from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorization,
    PhysicalDisposalAdmissionAuthorizationReceipt,
)
from app.modules.claims.retention_physical_disposal_authorization_service import (
    _actor_set_hash,
    _authorization_hash,
    _canonical_hash,
    _document_binding,
    _is_retryable_ao_error,
    _receipt_hash,
)
from app.modules.documents.recovery_durable_authoritative_storage_health_service import (
    RecoveryDurableAuthoritativeStorageHealthError,
)


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
