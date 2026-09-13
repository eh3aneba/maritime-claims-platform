from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.modules.claims.retention_physical_disposal_authorization_service import (
    _qualified_ao_receipt_integrity_ok,
)
from app.modules.documents.recovery_durable_authoritative_storage_health_service import (
    _receipt_hash as _ao_receipt_hash,
)


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, _statement):
        return _ScalarResult(self._rows)


def _qualification_and_receipt():
    transitioned_at = datetime(2026, 9, 13, 8, 30, tzinfo=timezone.utc)
    qualification = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        claim_id=uuid4(),
        document_id=uuid4(),
        ratification_id=uuid4(),
        qualified_by_id=uuid4(),
        qualified_at=transitioned_at,
        qualification_reason="Independently qualify durable authoritative storage health.",
        authority_route_version_at_request=7,
        integrity_proof_hash="1" * 64,
        request_snapshot_hash="2" * 64,
        health_qualification_hash="3" * 64,
    )
    receipt = SimpleNamespace(
        organization_id=qualification.organization_id,
        claim_id=qualification.claim_id,
        document_id=qualification.document_id,
        health_qualification_id=qualification.id,
        ratification_id=qualification.ratification_id,
        phase="qualified",
        health_state="healthy",
        observed_authority_kind="recovery_storage",
        observed_authority_tenure="durable_recovery",
        observed_ratification_active=True,
        observed_durable_authority_created=True,
        observed_local_authoritative=False,
        observed_recovery_authoritative=True,
        observed_authoritative_storage_changed=True,
        authority_route_version=qualification.authority_route_version_at_request,
        integrity_proof_hash=qualification.integrity_proof_hash,
        request_snapshot_hash=qualification.request_snapshot_hash,
        health_qualification_hash=qualification.health_qualification_hash,
        actor_id=qualification.qualified_by_id,
        reason=qualification.qualification_reason,
        transitioned_at=transitioned_at,
        local_evidence_preserved=True,
        storage_write_performed=False,
        route_mutation_performed=False,
        ownership_mutation_performed=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        destructive_action_performed=False,
        physical_disposal_authorized=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    receipt.receipt_hash = _ao_receipt_hash(
        qualification,
        phase="qualified",
        actor_id=receipt.actor_id,
        reason=receipt.reason,
        transitioned_at=receipt.transitioned_at,
    )
    return qualification, receipt


def test_exactly_one_intact_qualified_ao_receipt_is_required():
    qualification, receipt = _qualification_and_receipt()

    assert _qualified_ao_receipt_integrity_ok(_FakeDb([receipt]), qualification) is True
    assert _qualified_ao_receipt_integrity_ok(_FakeDb([]), qualification) is False
    assert _qualified_ao_receipt_integrity_ok(_FakeDb([receipt, receipt]), qualification) is False


def test_tampered_qualified_ao_receipt_is_rejected():
    qualification, receipt = _qualification_and_receipt()
    receipt.receipt_hash = "f" * 64

    assert _qualified_ao_receipt_integrity_ok(_FakeDb([receipt]), qualification) is False
