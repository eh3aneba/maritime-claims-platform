import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.retention_disposal_dry_run_service import _as_utc
from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorization,
    PhysicalDisposalAdmissionAuthorizationReceipt,
)
from app.modules.claims.retention_physical_disposal_authorization_service import (
    PhysicalDisposalAdmissionError,
    PhysicalDisposalAdmissionRetryableError,
    _actor_set_hash,
    _canonical_hash,
    _fresh_document_bindings,
    _get_admission,
    _governance_actor_ids,
    _verify_existing_integrity,
    _verify_release_review_and_manifest,
)
from app.modules.claims.retention_physical_disposal_execution_models import (
    PhysicalDisposalExecution,
    PhysicalDisposalExecutionItem,
    PhysicalDisposalExecutionReceipt,
)
from app.modules.claims.retention_physical_disposal_storage import (
    PhysicalDisposalStorageError,
    delete_exact_local_disposal_target,
    inspect_local_disposal_target,
    local_disposal_target_exists,
)
from app.modules.claims.retention_service import RetentionNotFoundError, get_claim_for_retention
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_authoritative_storage_health_models import (
    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification,
)
from app.modules.documents.recovery_read_ownership_transition_read_service import (
    resolve_recovery_document_read_ownership_transition,
)
from app.modules.documents.recovery_read_ownership_transition_routing_models import (
    EvidenceRecoveryReadOwnershipTransitionLease,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import (
    _load_replica,
    _read_verified_candidate,
)

EXECUTION_ROUTE_SAFETY_BUFFER = timedelta(minutes=5)


class PhysicalDisposalExecutionError(ValueError):
    pass


class PhysicalDisposalExecutionRetryableError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _as_utc(value).isoformat()


def _normalize_reason(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < 8:
        raise PhysicalDisposalExecutionError("Physical disposal execution reason must contain at least 8 characters")
    if len(normalized) > 2000:
        raise PhysicalDisposalExecutionError("Physical disposal execution reason must not exceed 2000 characters")
    return normalized


def _request_hash(
    authorization: PhysicalDisposalAdmissionAuthorization,
    *,
    request_id: UUID,
    executor_id: UUID,
    reason: str,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "approval_hash": authorization.approval_hash,
            "document_bindings_hash": authorization.document_bindings_hash,
            "request_id": str(request_id),
            "executor_id": str(executor_id),
            "reason": reason,
            "operation": "exact_local_physical_disposal",
            "max_execution_count": 1,
            "s3_delete_performed": False,
            "document_row_deleted": False,
            "document_storage_key_mutated": False,
        }
    )


def _receipt_hash(
    execution: PhysicalDisposalExecution,
    *,
    sequence_number: int,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
    prior_receipt_hash: str | None,
) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "sequence_number": sequence_number,
            "event_type": event_type,
            "status_after": execution.status,
            "actor_id": str(actor_id),
            "occurred_at": _iso(occurred_at),
            "reason": reason,
            "execution_request_hash": execution.execution_request_hash,
            "execution_hash": execution.execution_hash,
            "prior_receipt_hash": prior_receipt_hash,
            "destructive_action_performed": execution.destructive_action_performed,
            "local_delete_performed": execution.local_delete_performed,
            "s3_delete_performed": False,
            "recovery_bytes_preserved": execution.recovery_bytes_preserved,
            "document_row_deleted": False,
            "document_storage_key_mutated": False,
        }
    )


def _append_receipt(
    db: Session,
    *,
    execution: PhysicalDisposalExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
) -> PhysicalDisposalExecutionReceipt:
    latest = db.scalar(
        select(PhysicalDisposalExecutionReceipt)
        .where(PhysicalDisposalExecutionReceipt.execution_id == execution.id)
        .order_by(PhysicalDisposalExecutionReceipt.sequence_number.desc())
        .limit(1)
        .with_for_update()
    )
    sequence = 1 if latest is None else latest.sequence_number + 1
    prior = None if latest is None else latest.receipt_hash
    receipt = PhysicalDisposalExecutionReceipt(
        organization_id=execution.organization_id,
        claim_id=execution.claim_id,
        execution_id=execution.id,
        sequence_number=sequence,
        event_type=event_type,
        status_after=execution.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        execution_request_hash=execution.execution_request_hash,
        execution_hash=execution.execution_hash,
        prior_receipt_hash=prior,
        receipt_hash=_receipt_hash(
            execution,
            sequence_number=sequence,
            event_type=event_type,
            actor_id=actor_id,
            occurred_at=occurred_at,
            reason=reason,
            prior_receipt_hash=prior,
        ),
        destructive_action_performed=execution.destructive_action_performed,
        local_delete_performed=execution.local_delete_performed,
        s3_delete_performed=False,
        recovery_bytes_preserved=execution.recovery_bytes_preserved,
        document_row_deleted=False,
        document_storage_key_mutated=False,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _verify_admission_receipts(db: Session, authorization: PhysicalDisposalAdmissionAuthorization) -> None:
    receipts = list(
        db.scalars(
            select(PhysicalDisposalAdmissionAuthorizationReceipt)
            .where(PhysicalDisposalAdmissionAuthorizationReceipt.authorization_id == authorization.id)
            .order_by(PhysicalDisposalAdmissionAuthorizationReceipt.sequence_number.asc())
        ).all()
    )
    if len(receipts) != 2 or [receipt.event_type for receipt in receipts] != ["requested", "authorized"]:
        raise PhysicalDisposalExecutionError("Phase 17.4-A authorization receipt chain is incomplete")
    prior: str | None = None
    for receipt in receipts:
        expected = _canonical_hash(
            {
                "authorization_id": str(authorization.id),
                "sequence_number": receipt.sequence_number,
                "event_type": receipt.event_type,
                "status_after": receipt.status_after,
                "actor_id": str(receipt.actor_id),
                "occurred_at": _iso(receipt.occurred_at),
                "reason": receipt.reason,
                "authorization_hash": receipt.authorization_hash,
                "document_bindings_hash": receipt.document_bindings_hash,
                "separation_actor_set_hash": receipt.separation_actor_set_hash,
                "approval_hash": receipt.approval_hash,
                "prior_receipt_hash": prior,
                "destructive_action_performed": False,
                "storage_write_performed": False,
                "s3_delete_performed": False,
                "local_delete_performed": False,
            }
        )
        if receipt.prior_receipt_hash != prior or receipt.receipt_hash != expected:
            raise PhysicalDisposalExecutionError("Phase 17.4-A authorization receipt chain integrity failed")
        prior = receipt.receipt_hash
    if receipts[-1].status_after != "authorized" or receipts[-1].approval_hash != authorization.approval_hash:
        raise PhysicalDisposalExecutionError("Phase 17.4-A authorization receipt does not bind the approved credential")


def _load_document(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise PhysicalDisposalExecutionError(f"Bound document is unavailable:{document_id}")
    return document


def _load_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
) -> EvidenceRecoveryDurableAuthoritativeStorageHealthQualification:
    qualification = db.scalar(
        select(EvidenceRecoveryDurableAuthoritativeStorageHealthQualification).where(
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.id == qualification_id,
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.organization_id == organization_id,
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.claim_id == claim_id,
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.document_id == document_id,
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.status == "qualified",
        )
    )
    if qualification is None:
        raise PhysicalDisposalExecutionError(f"Bound AO qualification is unavailable:{document_id}")
    return qualification


def _qualification_actor_ids(qualification) -> set[UUID]:
    actors: set[UUID] = set()
    for column in qualification.__table__.columns:
        if column.name.endswith("_by_id"):
            value = getattr(qualification, column.name, None)
            if value is not None:
                actors.add(value)
    return actors


def _verify_recovery_read_preflight(
    db: Session,
    *,
    document: Document,
    expected_hash: str,
    expected_size: int,
    now: datetime,
) -> str:
    route = db.scalar(
        select(EvidenceRecoveryReadPathRoute).where(
            EvidenceRecoveryReadPathRoute.organization_id == document.organization_id,
            EvidenceRecoveryReadPathRoute.claim_id == document.claim_id,
            EvidenceRecoveryReadPathRoute.document_id == document.id,
        )
    )
    if (
        route is None
        or route.route_authority_kind != "read_ownership_transition"
        or route.active_read_ownership_transition_lease_id is None
    ):
        raise PhysicalDisposalExecutionError(
            f"Permanent recovery read-ownership transition is not active:{document.id}"
        )
    lease = db.scalar(
        select(EvidenceRecoveryReadOwnershipTransitionLease).where(
            EvidenceRecoveryReadOwnershipTransitionLease.id == route.active_read_ownership_transition_lease_id,
            EvidenceRecoveryReadOwnershipTransitionLease.organization_id == document.organization_id,
            EvidenceRecoveryReadOwnershipTransitionLease.claim_id == document.claim_id,
            EvidenceRecoveryReadOwnershipTransitionLease.document_id == document.id,
        )
    )
    if (
        lease is None
        or lease.status != "activated"
        or lease.route_expires_at is None
        or _as_utc(lease.route_expires_at) <= now + EXECUTION_ROUTE_SAFETY_BUFFER
    ):
        raise PhysicalDisposalExecutionError(
            f"Recovery read-ownership transition lacks a safe execution window:{document.id}"
        )
    try:
        payload, source = resolve_recovery_document_read_ownership_transition(db, document=document, now=now)
    except RuntimeError as exc:
        message = str(exc).lower()
        if any(marker in message for marker in ("unavailable", "timeout", "endpoint", "connection", "temporar")):
            raise PhysicalDisposalExecutionRetryableError(str(exc)) from exc
        raise PhysicalDisposalExecutionError(str(exc)) from exc
    if source != "recovery-replica-read-ownership-transition":
        raise PhysicalDisposalExecutionError(f"Document is not served from recovery read ownership:{document.id}")
    if hashlib.sha256(payload).hexdigest() != expected_hash or len(payload) != expected_size:
        raise PhysicalDisposalExecutionError(f"Recovery read bytes failed bound integrity verification:{document.id}")
    return source


def _verify_recovery_only_after_delete(
    db: Session,
    *,
    qualification: EvidenceRecoveryDurableAuthoritativeStorageHealthQualification,
    expected_hash: str,
    expected_size: int,
) -> None:
    try:
        replica = _load_replica(
            db,
            organization_id=qualification.organization_id,
            claim_id=qualification.claim_id,
            document_id=qualification.document_id,
            replica_id=qualification.replica_id,
        )
        payload = _read_verified_candidate(replica)
    except RuntimeError as exc:
        raise PhysicalDisposalExecutionRetryableError(str(exc)) from exc
    if not all(
        (
            replica.replica_hash == qualification.replica_hash,
            hashlib.sha256(payload).hexdigest() == expected_hash,
            len(payload) == expected_size,
            expected_hash == qualification.source_file_hash,
            expected_size == qualification.source_file_size_bytes,
        )
    ):
        raise PhysicalDisposalExecutionError(
            f"Recovery evidence failed post-delete integrity verification:{qualification.document_id}"
        )


def _item_outcome_hash(item: PhysicalDisposalExecutionItem) -> str:
    return _canonical_hash(
        {
            "execution_id": str(item.execution_id),
            "document_id": str(item.document_id),
            "target_hash": item.target_hash,
            "file_hash": item.file_hash,
            "file_size_bytes": item.file_size_bytes,
            "local_storage_key_fingerprint": item.local_storage_key_fingerprint,
            "local_deleted": True,
            "local_absent_after": True,
            "recovery_verified_after": True,
            "s3_delete_performed": False,
            "document_row_deleted": False,
            "document_storage_key_mutated": False,
        }
    )


def _execution_hash(execution: PhysicalDisposalExecution, items: list[PhysicalDisposalExecutionItem]) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "authorization_id": str(execution.authorization_id),
            "execution_request_hash": execution.execution_request_hash,
            "item_outcome_hashes": [item.outcome_hash for item in sorted(items, key=lambda row: str(row.document_id))],
            "document_count": execution.document_count,
            "deleted_count": execution.document_count,
            "destructive_action_performed": True,
            "local_delete_performed": True,
            "s3_delete_performed": False,
            "recovery_bytes_preserved": True,
            "document_row_deleted": False,
            "document_storage_key_mutated": False,
        }
    )


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    execution_id: UUID,
) -> PhysicalDisposalExecution:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    execution = db.scalar(
        select(PhysicalDisposalExecution).where(
            PhysicalDisposalExecution.id == execution_id,
            PhysicalDisposalExecution.organization_id == organization_id,
            PhysicalDisposalExecution.claim_id == claim_id,
        )
    )
    if execution is None:
        raise RetentionNotFoundError("Physical disposal execution not found")
    return execution


def get_physical_disposal_execution(db: Session, *, organization_id: UUID, claim_id: UUID, execution_id: UUID):
    execution = _get_execution(
        db, organization_id=organization_id, claim_id=claim_id, execution_id=execution_id
    )
    items = list(
        db.scalars(
            select(PhysicalDisposalExecutionItem)
            .where(PhysicalDisposalExecutionItem.execution_id == execution.id)
            .order_by(PhysicalDisposalExecutionItem.document_id.asc())
        ).all()
    )
    return execution, items


def list_physical_disposal_execution_receipts(
    db: Session, *, organization_id: UUID, claim_id: UUID, execution_id: UUID
) -> list[PhysicalDisposalExecutionReceipt]:
    execution = _get_execution(
        db, organization_id=organization_id, claim_id=claim_id, execution_id=execution_id
    )
    return list(
        db.scalars(
            select(PhysicalDisposalExecutionReceipt)
            .where(PhysicalDisposalExecutionReceipt.execution_id == execution.id)
            .order_by(PhysicalDisposalExecutionReceipt.sequence_number.asc())
        ).all()
    )


def execute_physical_disposal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    request_id: UUID,
    executor_id: UUID,
    execution_reason: str,
    now: datetime | None = None,
):
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(execution_reason)
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)

    authorization = _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    _verify_existing_integrity(authorization)
    request_hash = _request_hash(
        authorization, request_id=request_id, executor_id=executor_id, reason=reason
    )
    existing = db.scalar(
        select(PhysicalDisposalExecution).where(
            PhysicalDisposalExecution.organization_id == organization_id,
            PhysicalDisposalExecution.claim_id == claim_id,
            PhysicalDisposalExecution.authorization_id == authorization.id,
        )
    )
    if existing is not None:
        if existing.execution_request_hash != request_hash:
            raise PhysicalDisposalExecutionError("Conflicting replay for an existing physical disposal execution")
        if existing.status == "succeeded":
            return get_physical_disposal_execution(
                db, organization_id=organization_id, claim_id=claim_id, execution_id=existing.id
            ) + ("unchanged",)
        execution = existing
    else:
        if not all(
            (
                authorization.status == "authorized",
                authorization.physical_disposal_authorized is True,
                authorization.execution_count == 0,
                authorization.max_execution_count == 1,
                authorization.approved_by_id is not None,
                authorization.approval_hash is not None,
            )
        ):
            raise PhysicalDisposalExecutionError("Phase 17.4-A credential is not executable")
        if current_time >= _as_utc(authorization.authorization_expires_at):
            raise PhysicalDisposalExecutionError("Phase 17.4-A credential expired before execution")
        _verify_admission_receipts(db, authorization)
        try:
            review, manifest, _stage = _verify_release_review_and_manifest(
                db,
                organization_id=organization_id,
                claim_id=claim_id,
                review_id=authorization.disposal_release_review_id,
                actor_id=executor_id,
                now=current_time,
            )
            actor_ids = set(
                _governance_actor_ids(
                    db,
                    organization_id=organization_id,
                    claim_id=claim_id,
                    review=review,
                    manifest=manifest,
                    requested_by_id=authorization.requested_by_id,
                )
            )
            live_bindings = _fresh_document_bindings(
                db,
                organization_id=organization_id,
                claim_id=claim_id,
                inventory=list(manifest.inventory or []),
                expected_document_count=manifest.document_count,
                now=current_time,
            )
        except PhysicalDisposalAdmissionRetryableError as exc:
            raise PhysicalDisposalExecutionRetryableError(str(exc)) from exc
        except PhysicalDisposalAdmissionError as exc:
            raise PhysicalDisposalExecutionError(str(exc)) from exc
        if not all(
            (
                _actor_set_hash(list(actor_ids)) == authorization.separation_actor_set_hash,
                live_bindings == list(authorization.document_bindings or []),
                _canonical_hash(live_bindings) == authorization.document_bindings_hash,
                review.review_hash == authorization.release_review_hash,
                review.approval_hash == authorization.release_approval_hash,
                manifest.manifest_hash == authorization.manifest_hash,
                manifest.inventory_hash == authorization.inventory_hash,
            )
        ):
            raise PhysicalDisposalExecutionError("Phase 17.4-A governance or binding drift detected")
        actor_ids.add(authorization.approved_by_id)

        preflight: list[tuple[dict, Document, EvidenceRecoveryDurableAuthoritativeStorageHealthQualification, str]] = []
        for binding in live_bindings:
            document_id = UUID(binding["document_id"])
            qualification_id = UUID(binding["ao_health_qualification_id"])
            document = _load_document(
                db, organization_id=organization_id, claim_id=claim_id, document_id=document_id
            )
            qualification = _load_qualification(
                db,
                organization_id=organization_id,
                claim_id=claim_id,
                document_id=document_id,
                qualification_id=qualification_id,
            )
            actor_ids.update(_qualification_actor_ids(qualification))
            target = inspect_local_disposal_target(document)
            if not all(
                (
                    target.storage_key_fingerprint == binding["storage_key_fingerprint"],
                    target.file_hash == binding["file_hash"],
                    target.file_size_bytes == int(binding["file_size_bytes"]),
                )
            ):
                raise PhysicalDisposalExecutionError(f"Local disposal target drifted:{document_id}")
            read_source = _verify_recovery_read_preflight(
                db,
                document=document,
                expected_hash=binding["file_hash"],
                expected_size=int(binding["file_size_bytes"]),
                now=current_time,
            )
            preflight.append((binding, document, qualification, read_source))

        if executor_id in actor_ids:
            raise PhysicalDisposalExecutionError(
                "Physical disposal executor must be independent of all material prior governance actors"
            )

        execution = PhysicalDisposalExecution(
            organization_id=organization_id,
            claim_id=claim_id,
            authorization_id=authorization.id,
            request_id=request_id,
            authorization_hash=authorization.authorization_hash,
            approval_hash=authorization.approval_hash,
            document_bindings_hash=authorization.document_bindings_hash,
            execution_request_hash=request_hash,
            executor_id=executor_id,
            execution_reason=reason,
            prepared_at=current_time,
            status="prepared",
            document_count=len(preflight),
            deleted_count=0,
            destructive_action_performed=False,
            local_delete_performed=False,
            s3_delete_performed=False,
            recovery_bytes_preserved=True,
            document_row_deleted=False,
            document_storage_key_mutated=False,
        )
        db.add(execution)
        db.flush()
        for binding, document, qualification, read_source in preflight:
            target_hash = _canonical_hash(
                {
                    "execution_id": str(execution.id),
                    "document_id": str(document.id),
                    "ao_health_qualification_id": str(qualification.id),
                    "binding_hash": binding["binding_hash"],
                    "file_hash": binding["file_hash"],
                    "file_size_bytes": int(binding["file_size_bytes"]),
                    "local_storage_key_fingerprint": binding["storage_key_fingerprint"],
                    "recovery_read_source": read_source,
                }
            )
            db.add(
                PhysicalDisposalExecutionItem(
                    organization_id=organization_id,
                    claim_id=claim_id,
                    execution_id=execution.id,
                    document_id=document.id,
                    ao_health_qualification_id=qualification.id,
                    binding_hash=binding["binding_hash"],
                    file_hash=binding["file_hash"],
                    file_size_bytes=int(binding["file_size_bytes"]),
                    local_storage_key_fingerprint=binding["storage_key_fingerprint"],
                    recovery_read_source=read_source,
                    target_hash=target_hash,
                    status="prepared",
                    local_existed_before=True,
                    local_deleted=False,
                    local_absent_after=False,
                    recovery_verified_before=True,
                    recovery_verified_after=False,
                    s3_delete_performed=False,
                    document_row_deleted=False,
                    document_storage_key_mutated=False,
                )
            )
        _append_receipt(
            db,
            execution=execution,
            event_type="prepared",
            actor_id=executor_id,
            occurred_at=current_time,
            reason=reason,
        )
        db.commit()
        db.refresh(execution)

    items = list(
        db.scalars(
            select(PhysicalDisposalExecutionItem)
            .where(PhysicalDisposalExecutionItem.execution_id == execution.id)
            .order_by(PhysicalDisposalExecutionItem.document_id.asc())
        ).all()
    )
    for item in items:
        if item.status == "verified":
            continue
        document = _load_document(
            db, organization_id=organization_id, claim_id=claim_id, document_id=item.document_id
        )
        qualification = _load_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=item.document_id,
            qualification_id=item.ao_health_qualification_id,
        )
        if item.status == "prepared":
            if local_disposal_target_exists(document):
                delete_exact_local_disposal_target(
                    document,
                    expected_storage_key_fingerprint=item.local_storage_key_fingerprint,
                    expected_file_hash=item.file_hash,
                    expected_file_size_bytes=item.file_size_bytes,
                )
                event_type = "local_deleted"
            else:
                event_type = "reconciled"
            item.status = "deleted"
            item.local_deleted = True
            item.local_absent_after = True
            item.deleted_at = _as_utc(now or _utc_now())
            execution.status = "partial"
            execution.local_delete_performed = True
            execution.destructive_action_performed = True
            execution.deleted_count = sum(1 for candidate in items if candidate.local_deleted) + (0 if item.local_deleted else 1)
            _append_receipt(
                db,
                execution=execution,
                event_type=event_type,
                actor_id=executor_id,
                occurred_at=item.deleted_at,
                reason=reason,
            )
            db.commit()
            db.refresh(item)
            db.refresh(execution)
        try:
            _verify_recovery_only_after_delete(
                db,
                qualification=qualification,
                expected_hash=item.file_hash,
                expected_size=item.file_size_bytes,
            )
        except PhysicalDisposalExecutionRetryableError:
            execution.status = "partial"
            execution.local_delete_performed = True
            execution.destructive_action_performed = True
            db.commit()
            raise
        if local_disposal_target_exists(document):
            raise PhysicalDisposalExecutionError(f"Local evidence unexpectedly reappeared:{document.id}")
        item.status = "verified"
        item.recovery_verified_after = True
        item.verified_at = _as_utc(now or _utc_now())
        item.outcome_hash = _item_outcome_hash(item)
        db.commit()

    items = list(
        db.scalars(
            select(PhysicalDisposalExecutionItem)
            .where(PhysicalDisposalExecutionItem.execution_id == execution.id)
            .order_by(PhysicalDisposalExecutionItem.document_id.asc())
        ).all()
    )
    if any(item.status != "verified" for item in items):
        raise PhysicalDisposalExecutionRetryableError("Physical disposal execution requires reconciliation")

    authorization = _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if authorization.status not in {"authorized", "consumed"}:
        raise PhysicalDisposalExecutionError("Admission credential changed during physical disposal execution")
    if authorization.status == "authorized":
        if authorization.execution_count != 0:
            raise PhysicalDisposalExecutionError("Admission credential execution count drifted")
        authorization.status = "consumed"
        authorization.execution_count = 1
        authorization.terminal_by_id = executor_id
        authorization.terminal_at = _as_utc(now or _utc_now())
        authorization.terminal_reason = f"Consumed by Phase 17.4-B execution {execution.id}"
    elif authorization.execution_count != 1:
        raise PhysicalDisposalExecutionError("Consumed admission credential has invalid execution count")

    execution.status = "succeeded"
    execution.deleted_count = len(items)
    execution.destructive_action_performed = True
    execution.local_delete_performed = True
    execution.recovery_bytes_preserved = True
    execution.completed_at = _as_utc(now or _utc_now())
    execution.execution_hash = _execution_hash(execution, items)
    _append_receipt(
        db,
        execution=execution,
        event_type="succeeded",
        actor_id=executor_id,
        occurred_at=execution.completed_at,
        reason=reason,
    )
    db.commit()
    db.refresh(execution)
    return execution, items, "succeeded"
