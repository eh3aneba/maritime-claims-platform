from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorization,
)
from app.modules.claims.retention_physical_disposal_authorization_service import (
    _authorization_hash,
    _canonical_hash,
    _document_binding,
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


def test_authorization_hash_binds_single_use_safety_boundary():
    requested_at = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
    expires_at = requested_at + timedelta(minutes=5)
    values = dict(
        release_review_id=uuid4(),
        release_review_hash="1" * 64,
        release_approval_hash="2" * 64,
        manifest_hash="3" * 64,
        inventory_hash="4" * 64,
        document_bindings_hash="5" * 64,
        requested_by_id=uuid4(),
        request_reason="Approve bounded physical disposal admission",
        requested_at=requested_at,
        authorization_expires_at=expires_at,
    )
    baseline = _authorization_hash(**values)
    changed = dict(values)
    changed["document_bindings_hash"] = "6" * 64

    assert baseline != _authorization_hash(**changed)


def test_model_hard_blocks_destructive_actions_in_phase_17_4_a():
    constraints = {
        constraint.name
        for constraint in PhysicalDisposalAdmissionAuthorization.__table__.constraints
        if constraint.name
    }

    assert "ck_physical_disposal_admission_single_use" in constraints
    assert "ck_physical_disposal_admission_four_eyes" in constraints
    assert "ck_physical_disposal_admission_no_destructive_action" in constraints
    assert "ck_physical_disposal_admission_no_storage_write" in constraints
    assert "ck_physical_disposal_admission_no_s3_delete" in constraints
    assert "ck_physical_disposal_admission_no_local_delete" in constraints
