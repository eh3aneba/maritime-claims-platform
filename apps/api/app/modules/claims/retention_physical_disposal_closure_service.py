import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.retention_disposal_dry_run_service import _as_utc
from app.modules.claims.retention_disposal_manifest_models import DisposalExecutionManifest
from app.modules.claims.retention_physical_disposal_authorization_models import (
    PhysicalDisposalAdmissionAuthorization,
)
from app.modules.claims.retention_physical_disposal_authorization_service import (
    PhysicalDisposalAdmissionError,
    _actor_set_hash,
    _canonical_hash,
    _get_admission,
    _get_release_review,
    _governance_actor_ids,
    _qualified_ao_receipt_integrity_ok,
    _stored_ao_integrity_ok,
    _verify_existing_integrity,
)
from app.modules.claims.retention_physical_disposal_closure_models import (
    PhysicalDisposalClosureQualification,
    PhysicalDisposalClosureReceipt,
)
from app.modules.claims.retention_physical_disposal_execution_models import (
    PhysicalDisposalExecution,
    PhysicalDisposalExecutionItem,
    PhysicalDisposalExecutionReceipt,
)
from app.modules.claims.retention_physical_disposal_execution_service import (
    _execution_hash,
    _is_retryable_recovery_error,
    _item_outcome_hash,
    _load_document,
    _load_qualification,
)
from app.modules.claims.retention_physical_disposal_storage import (
    local_disposal_target_exists,
)
from app.modules.claims.retention_service import (
    RetentionNotFoundError,
    get_claim_for_retention,
    get_current_retention_policy,
    preview_disposal_eligibility,
)
from app.modules.documents.recovery_authoritative_storage_ownership_execution_service import (
    RecoveryAuthoritativeStorageOwnershipExecutionError,
    get_authoritative_storage_ownership_route,
)
from app.modules.documents.recovery_authoritative_storage_ratification_execution_service import (
    RecoveryAuthoritativeStorageRatificationExecutionError,
    get_authoritative_storage_ratification,
)
from app.modules.documents.recovery_routable_read_cutover_service import (
    _load_replica,
    _read_verified_candidate,
)


PHYSICAL_DISPOSAL_CLOSURE_REVIEW_WINDOW = timedelta(minutes=10)


class PhysicalDisposalClosureError(ValueError):
    pass


class PhysicalDisposalClosureRetryableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhysicalDisposalClosureSnapshot:
    execution: PhysicalDisposalExecution
    authorization: PhysicalDisposalAdmissionAuthorization
    verification_snapshot: list[dict]
    verification_snapshot_hash: str
    execution_receipt_chain_hash: str
    item_outcomes_hash: str
    separation_actor_set_hash: str
    material_actor_ids: frozenset[UUID]
    document_count: int
    total_file_size_bytes: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _as_utc(value).isoformat()


def _normalize_reason(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < 8:
        raise PhysicalDisposalClosureError(
            "Post-disposal closure reason must contain at least 8 characters"
        )
    if len(normalized) > 2000:
        raise PhysicalDisposalClosureError(
            "Post-disposal closure reason must not exceed 2000 characters"
        )
    return normalized


def _execution_receipt_hash(receipt: PhysicalDisposalExecutionReceipt) -> str:
    return _canonical_hash(
        {
            "execution_id": str(receipt.execution_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "actor_id": str(receipt.actor_id),
            "occurred_at": _iso(receipt.occurred_at),
            "reason": receipt.reason,
            "execution_request_hash": receipt.execution_request_hash,
            "execution_hash": receipt.execution_hash,
            "prior_receipt_hash": receipt.prior_receipt_hash,
            "destructive_action_performed": receipt.destructive_action_performed,
            "local_delete_performed": receipt.local_delete_performed,
            "s3_delete_performed": False,
            "recovery_bytes_preserved": receipt.recovery_bytes_preserved,
            "document_row_deleted": False,
            "document_storage_key_mutated": False,
        }
    )


def _verify_execution_receipts(
    db: Session, execution: PhysicalDisposalExecution
) -> tuple[list[PhysicalDisposalExecutionReceipt], str]:
    receipts = list(
        db.scalars(
            select(PhysicalDisposalExecutionReceipt)
            .where(
                PhysicalDisposalExecutionReceipt.organization_id
                == execution.organization_id,
                PhysicalDisposalExecutionReceipt.claim_id == execution.claim_id,
                PhysicalDisposalExecutionReceipt.execution_id == execution.id,
            )
            .order_by(PhysicalDisposalExecutionReceipt.sequence_number.asc())
        ).all()
    )
    if len(receipts) < 3:
        raise PhysicalDisposalClosureError(
            "Phase 17.4-B execution receipt chain is incomplete"
        )
    prior: str | None = None
    for index, receipt in enumerate(receipts, start=1):
        if receipt.sequence_number != index:
            raise PhysicalDisposalClosureError(
                "Phase 17.4-B execution receipt sequence is not contiguous"
            )
        if receipt.prior_receipt_hash != prior:
            raise PhysicalDisposalClosureError(
                "Phase 17.4-B execution receipt prior-hash linkage failed"
            )
        if receipt.receipt_hash != _execution_receipt_hash(receipt):
            raise PhysicalDisposalClosureError(
                "Phase 17.4-B execution receipt integrity failed"
            )
        if not all(
            (
                receipt.execution_request_hash == execution.execution_request_hash,
                receipt.s3_delete_performed is False,
                receipt.document_row_deleted is False,
                receipt.document_storage_key_mutated is False,
            )
        ):
            raise PhysicalDisposalClosureError(
                "Phase 17.4-B execution receipt safety lineage drifted"
            )
        prior = receipt.receipt_hash
    if not all(
        (
            receipts[0].event_type == "prepared",
            receipts[0].status_after == "prepared",
            receipts[-1].event_type == "succeeded",
            receipts[-1].status_after == "succeeded",
            receipts[-1].execution_hash == execution.execution_hash,
            all(
                row.event_type in {"local_deleted", "reconciled"}
                for row in receipts[1:-1]
            ),
        )
    ):
        raise PhysicalDisposalClosureError(
            "Phase 17.4-B execution receipt lifecycle is inconsistent"
        )
    return receipts, _canonical_hash([row.receipt_hash for row in receipts])


def _closure_hash(
    *,
    execution_id: UUID,
    execution_hash: str,
    document_bindings_hash: str,
    execution_receipt_chain_hash: str,
    item_outcomes_hash: str,
    verification_snapshot_hash: str,
    separation_actor_set_hash: str,
    requested_by_id: UUID,
    requested_at: datetime,
    review_expires_at: datetime,
    request_reason: str,
) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution_id),
            "execution_hash": execution_hash,
            "document_bindings_hash": document_bindings_hash,
            "execution_receipt_chain_hash": execution_receipt_chain_hash,
            "item_outcomes_hash": item_outcomes_hash,
            "verification_snapshot_hash": verification_snapshot_hash,
            "separation_actor_set_hash": separation_actor_set_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _iso(requested_at),
            "review_expires_at": _iso(review_expires_at),
            "request_reason": request_reason,
            "health_state": "healthy",
            "observed_local_targets_absent": True,
            "observed_recovery_bytes_healthy": True,
            "observed_document_rows_preserved": True,
            "observed_storage_keys_preserved": True,
            "observed_authority_kind": "recovery_storage",
            "observed_authority_tenure": "durable_recovery",
            "storage_write_performed": False,
            "route_mutation_performed": False,
            "ownership_mutation_performed": False,
            "destructive_action_performed": False,
            "physical_disposal_authorized": False,
        }
    )


def _decision_hash(
    qualification: PhysicalDisposalClosureQualification,
    *,
    qualified_by_id: UUID,
    qualified_at: datetime,
    reason: str,
) -> str:
    return _canonical_hash(
        {
            "qualification_id": str(qualification.id),
            "closure_qualification_hash": qualification.closure_qualification_hash,
            "execution_hash": qualification.execution_hash,
            "verification_snapshot_hash": qualification.verification_snapshot_hash,
            "qualified_by_id": str(qualified_by_id),
            "qualified_at": _iso(qualified_at),
            "reason": reason,
            "status": "qualified",
            "health_state": "healthy",
            "storage_write_performed": False,
            "route_mutation_performed": False,
            "ownership_mutation_performed": False,
            "destructive_action_performed": False,
        }
    )


def _receipt_hash(
    qualification: PhysicalDisposalClosureQualification,
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
            "qualification_id": str(qualification.id),
            "execution_id": str(qualification.execution_id),
            "sequence_number": sequence_number,
            "event_type": event_type,
            "status_after": qualification.status,
            "actor_id": str(actor_id),
            "occurred_at": _iso(occurred_at),
            "reason": reason,
            "execution_hash": qualification.execution_hash,
            "verification_snapshot_hash": qualification.verification_snapshot_hash,
            "closure_qualification_hash": qualification.closure_qualification_hash,
            "decision_hash": qualification.decision_hash,
            "prior_receipt_hash": prior_receipt_hash,
            "storage_write_performed": False,
            "route_mutation_performed": False,
            "ownership_mutation_performed": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "destructive_action_performed": False,
            "physical_disposal_authorized": False,
            "s3_put_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_overwrite_performed": False,
            "local_move_performed": False,
            "local_delete_performed": False,
        }
    )


def _append_receipt(
    db: Session,
    *,
    qualification: PhysicalDisposalClosureQualification,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    reason: str,
) -> PhysicalDisposalClosureReceipt:
    latest = db.scalar(
        select(PhysicalDisposalClosureReceipt)
        .where(PhysicalDisposalClosureReceipt.qualification_id == qualification.id)
        .order_by(PhysicalDisposalClosureReceipt.sequence_number.desc())
        .limit(1)
        .with_for_update()
    )
    sequence = 1 if latest is None else latest.sequence_number + 1
    prior = None if latest is None else latest.receipt_hash
    receipt = PhysicalDisposalClosureReceipt(
        organization_id=qualification.organization_id,
        claim_id=qualification.claim_id,
        qualification_id=qualification.id,
        execution_id=qualification.execution_id,
        sequence_number=sequence,
        event_type=event_type,
        status_after=qualification.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=reason,
        execution_hash=qualification.execution_hash,
        verification_snapshot_hash=qualification.verification_snapshot_hash,
        closure_qualification_hash=qualification.closure_qualification_hash,
        decision_hash=qualification.decision_hash,
        prior_receipt_hash=prior,
        receipt_hash=_receipt_hash(
            qualification,
            sequence_number=sequence,
            event_type=event_type,
            actor_id=actor_id,
            occurred_at=occurred_at,
            reason=reason,
            prior_receipt_hash=prior,
        ),
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
    db.add(receipt)
    db.flush()
    return receipt


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    execution_id: UUID,
) -> PhysicalDisposalExecution:
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


def _get_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    qualification_id: UUID,
    for_update: bool = False,
) -> PhysicalDisposalClosureQualification:
    stmt = select(PhysicalDisposalClosureQualification).where(
        PhysicalDisposalClosureQualification.id == qualification_id,
        PhysicalDisposalClosureQualification.organization_id == organization_id,
        PhysicalDisposalClosureQualification.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    qualification = db.scalar(stmt)
    if qualification is None:
        raise RetentionNotFoundError("Post-disposal closure qualification not found")
    return qualification


def _stored_integrity_ok(qualification: PhysicalDisposalClosureQualification) -> bool:
    return qualification.closure_qualification_hash == _closure_hash(
        execution_id=qualification.execution_id,
        execution_hash=qualification.execution_hash,
        document_bindings_hash=qualification.document_bindings_hash,
        execution_receipt_chain_hash=qualification.execution_receipt_chain_hash,
        item_outcomes_hash=qualification.item_outcomes_hash,
        verification_snapshot_hash=qualification.verification_snapshot_hash,
        separation_actor_set_hash=qualification.separation_actor_set_hash,
        requested_by_id=qualification.requested_by_id,
        requested_at=_as_utc(qualification.requested_at),
        review_expires_at=_as_utc(qualification.review_expires_at),
        request_reason=qualification.request_reason,
    )


def _material_actor_ids(
    db: Session,
    *,
    authorization: PhysicalDisposalAdmissionAuthorization,
    execution: PhysicalDisposalExecution,
    items: list[PhysicalDisposalExecutionItem],
) -> set[UUID]:
    actors: set[UUID] = {
        authorization.requested_by_id,
        execution.executor_id,
    }
    if authorization.approved_by_id is not None:
        actors.add(authorization.approved_by_id)
    release_review = _get_release_review(
        db,
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        review_id=authorization.disposal_release_review_id,
    )
    manifest = db.scalar(
        select(DisposalExecutionManifest).where(
            DisposalExecutionManifest.id == authorization.disposal_execution_manifest_id,
            DisposalExecutionManifest.organization_id == authorization.organization_id,
            DisposalExecutionManifest.claim_id == authorization.claim_id,
        )
    )
    if manifest is None:
        raise PhysicalDisposalClosureError("Bound disposal execution manifest is unavailable")
    if not all(
        (
            release_review.review_hash == authorization.release_review_hash,
            release_review.approval_hash == authorization.release_approval_hash,
            manifest.manifest_hash == authorization.manifest_hash,
            manifest.inventory_hash == authorization.inventory_hash,
            manifest.document_count == authorization.document_count,
            manifest.total_file_size_bytes == authorization.total_file_size_bytes,
        )
    ):
        raise PhysicalDisposalClosureError("Historical disposal governance lineage drifted")
    try:
        actors.update(
            _governance_actor_ids(
                db,
                organization_id=authorization.organization_id,
                claim_id=authorization.claim_id,
                review=release_review,
                manifest=manifest,
                requested_by_id=authorization.requested_by_id,
            )
        )
    except PhysicalDisposalAdmissionError as exc:
        raise PhysicalDisposalClosureError(str(exc)) from exc
    for item in items:
        ao = _load_qualification(
            db,
            organization_id=item.organization_id,
            claim_id=item.claim_id,
            document_id=item.document_id,
            qualification_id=item.ao_health_qualification_id,
        )
        for column in ao.__table__.columns:
            if column.name.endswith("_by_id"):
                actor_id = getattr(ao, column.name, None)
                if actor_id is not None:
                    actors.add(actor_id)
    return actors


def _fresh_closure_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    execution_id: UUID,
    now: datetime,
) -> PhysicalDisposalClosureSnapshot:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    execution = _get_execution(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        execution_id=execution_id,
    )
    items = list(
        db.scalars(
            select(PhysicalDisposalExecutionItem)
            .where(
                PhysicalDisposalExecutionItem.execution_id == execution.id,
                PhysicalDisposalExecutionItem.organization_id == organization_id,
                PhysicalDisposalExecutionItem.claim_id == claim_id,
            )
            .order_by(PhysicalDisposalExecutionItem.document_id.asc())
        ).all()
    )
    if not all(
        (
            execution.status == "succeeded",
            execution.execution_hash is not None,
            execution.document_count > 0,
            execution.deleted_count == execution.document_count,
            len(items) == execution.document_count,
            execution.destructive_action_performed is True,
            execution.local_delete_performed is True,
            execution.s3_delete_performed is False,
            execution.recovery_bytes_preserved is True,
            execution.document_row_deleted is False,
            execution.document_storage_key_mutated is False,
        )
    ):
        raise PhysicalDisposalClosureError(
            "Phase 17.4-C requires one exact successful Phase 17.4-B execution"
        )

    authorization = _get_admission(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        authorization_id=execution.authorization_id,
    )
    try:
        _verify_existing_integrity(authorization)
    except PhysicalDisposalAdmissionError as exc:
        raise PhysicalDisposalClosureError(str(exc)) from exc
    if not all(
        (
            authorization.status == "consumed",
            authorization.physical_disposal_authorized is True,
            authorization.execution_count == 1,
            authorization.max_execution_count == 1,
            authorization.approved_by_id is not None,
            authorization.approval_hash is not None,
            authorization.authorization_hash == execution.authorization_hash,
            authorization.approval_hash == execution.approval_hash,
            authorization.document_bindings_hash == execution.document_bindings_hash,
        )
    ):
        raise PhysicalDisposalClosureError(
            "Phase 17.4-A consumed credential no longer matches the disposal execution"
        )

    _, receipt_chain_hash = _verify_execution_receipts(db, execution)
    policy = get_current_retention_policy(db, organization_id=organization_id)
    manifest = db.scalar(
        select(DisposalExecutionManifest).where(
            DisposalExecutionManifest.id == authorization.disposal_execution_manifest_id,
            DisposalExecutionManifest.organization_id == organization_id,
            DisposalExecutionManifest.claim_id == claim_id,
        )
    )
    if manifest is None:
        raise PhysicalDisposalClosureError("Bound disposal execution manifest is unavailable")
    if policy is None or not all(
        (
            policy.id == manifest.retention_policy_id,
            policy.policy_number == manifest.retention_policy_number,
            policy.policy_hash == manifest.retention_policy_hash,
        )
    ):
        raise PhysicalDisposalClosureError("Retention policy drift detected after disposal")
    eligibility = preview_disposal_eligibility(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        now=now,
    )
    if eligibility.active_hold_ids:
        raise PhysicalDisposalClosureError("Active legal hold detected after disposal")
    if eligibility.pending_proposal_ids:
        raise PhysicalDisposalClosureError(
            "Pending legal-hold proposal detected after disposal"
        )

    verification_rows: list[dict] = []
    outcome_hashes: list[str] = []
    total_bytes = 0
    for item in items:
        if not all(
            (
                item.status == "verified",
                item.local_existed_before is True,
                item.local_deleted is True,
                item.local_absent_after is True,
                item.recovery_verified_before is True,
                item.recovery_verified_after is True,
                item.outcome_hash is not None,
                item.s3_delete_performed is False,
                item.document_row_deleted is False,
                item.document_storage_key_mutated is False,
            )
        ):
            raise PhysicalDisposalClosureError(
                f"Phase 17.4-B item is not a completed verified outcome:{item.document_id}"
            )
        outcome_hash = _item_outcome_hash(item)
        if outcome_hash != item.outcome_hash:
            raise PhysicalDisposalClosureError(
                f"Phase 17.4-B item outcome hash integrity failed:{item.document_id}"
            )
        outcome_hashes.append(outcome_hash)
        total_bytes += int(item.file_size_bytes)

        document = _load_document(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=item.document_id,
        )
        key_fingerprint = hashlib.sha256(
            document.storage_key.encode("utf-8")
        ).hexdigest()
        if not all(
            (
                document.deleted_at is None,
                document.file_hash.lower() == item.file_hash.lower(),
                int(document.file_size_bytes) == int(item.file_size_bytes),
                key_fingerprint == item.local_storage_key_fingerprint,
            )
        ):
            raise PhysicalDisposalClosureError(
                f"Document metadata drift detected after disposal:{item.document_id}"
            )
        try:
            if local_disposal_target_exists(document):
                raise PhysicalDisposalClosureError(
                    f"Disposed local target reappeared:{item.document_id}"
                )
        except (OSError, RuntimeError) as exc:
            raise PhysicalDisposalClosureError(
                f"Unable to inspect disposed local target:{item.document_id}"
            ) from exc

        ao = _load_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=item.document_id,
            qualification_id=item.ao_health_qualification_id,
        )
        if not _stored_ao_integrity_ok(ao) or not _qualified_ao_receipt_integrity_ok(db, ao):
            raise PhysicalDisposalClosureError(
                f"Phase AO qualification integrity failed after disposal:{item.document_id}"
            )
        try:
            route = get_authoritative_storage_ownership_route(
                db,
                organization_id=organization_id,
                claim_id=claim_id,
                document_id=item.document_id,
            )
            ratification = get_authoritative_storage_ratification(
                db,
                organization_id=organization_id,
                claim_id=claim_id,
                document_id=item.document_id,
                ratification_id=ao.ratification_id,
            )
            replica = _load_replica(
                db,
                organization_id=organization_id,
                claim_id=claim_id,
                document_id=item.document_id,
                replica_id=ao.replica_id,
            )
            payload = _read_verified_candidate(replica)
        except (
            RecoveryAuthoritativeStorageOwnershipExecutionError,
            RecoveryAuthoritativeStorageRatificationExecutionError,
            RuntimeError,
        ) as exc:
            if _is_retryable_recovery_error(exc):
                raise PhysicalDisposalClosureRetryableError(str(exc)) from exc
            raise PhysicalDisposalClosureError(str(exc)) from exc
        recovery_hash = hashlib.sha256(payload).hexdigest()
        if not all(
            (
                route.authority_kind == "recovery_storage",
                route.authority_tenure == "durable_recovery",
                route.active_authority_lease_id is None,
                route.durable_ratification_id == ao.ratification_id,
                route.local_authoritative is False,
                route.recovery_authoritative is True,
                route.authoritative_storage_changed is True,
                ratification.status == "ratified",
                ratification.ratification_active is True,
                ratification.durable_authority_created is True,
                ratification.replica_id == ao.replica_id,
                ratification.replica_hash == ao.replica_hash,
                ratification.source_file_hash == item.file_hash,
                int(ratification.source_file_size_bytes) == int(item.file_size_bytes),
                replica.replica_hash == ao.replica_hash,
                recovery_hash == item.file_hash,
                len(payload) == int(item.file_size_bytes),
                ao.source_file_hash == item.file_hash,
                int(ao.source_file_size_bytes) == int(item.file_size_bytes),
                ao.observed_authority_kind == "recovery_storage",
                ao.observed_authority_tenure == "durable_recovery",
            )
        ):
            raise PhysicalDisposalClosureError(
                f"Durable recovery authority or byte integrity drifted after disposal:{item.document_id}"
            )
        verification_rows.append(
            {
                "document_id": str(item.document_id),
                "execution_item_id": str(item.id),
                "ao_health_qualification_id": str(ao.id),
                "ao_health_qualification_hash": ao.health_qualification_hash,
                "ratification_id": str(ao.ratification_id),
                "ratification_hash": ao.ratification_hash,
                "replica_id": str(ao.replica_id),
                "replica_hash": ao.replica_hash,
                "authority_route_version": route.route_version,
                "file_hash": item.file_hash,
                "file_size_bytes": int(item.file_size_bytes),
                "local_storage_key_fingerprint": item.local_storage_key_fingerprint,
                "local_absent": True,
                "recovery_hash": recovery_hash,
                "recovery_size_bytes": len(payload),
                "document_row_preserved": True,
                "storage_key_preserved": True,
                "authority_kind": "recovery_storage",
                "authority_tenure": "durable_recovery",
            }
        )

    if _execution_hash(execution, items) != execution.execution_hash:
        raise PhysicalDisposalClosureError(
            "Phase 17.4-B final execution hash integrity failed"
        )
    material_actors = _material_actor_ids(
        db, authorization=authorization, execution=execution, items=items
    )
    verification_snapshot = sorted(
        verification_rows, key=lambda row: row["document_id"]
    )
    return PhysicalDisposalClosureSnapshot(
        execution=execution,
        authorization=authorization,
        verification_snapshot=verification_snapshot,
        verification_snapshot_hash=_canonical_hash(verification_snapshot),
        execution_receipt_chain_hash=receipt_chain_hash,
        item_outcomes_hash=_canonical_hash(sorted(outcome_hashes)),
        separation_actor_set_hash=_actor_set_hash(list(material_actors)),
        material_actor_ids=frozenset(material_actors),
        document_count=len(items),
        total_file_size_bytes=total_bytes,
    )


def request_physical_disposal_closure(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    execution_id: UUID,
    requested_by_id: UUID,
    request_reason: str,
    now: datetime | None = None,
) -> PhysicalDisposalClosureQualification:
    current = _as_utc(now or _utc_now())
    reason = _normalize_reason(request_reason)
    existing = db.scalar(
        select(PhysicalDisposalClosureQualification).where(
            PhysicalDisposalClosureQualification.organization_id == organization_id,
            PhysicalDisposalClosureQualification.claim_id == claim_id,
            PhysicalDisposalClosureQualification.execution_id == execution_id,
        )
    )
    if existing is not None:
        if not _stored_integrity_ok(existing):
            raise PhysicalDisposalClosureError(
                "Stored post-disposal closure qualification integrity failed"
            )
        if existing.requested_by_id == requested_by_id and existing.request_reason == reason:
            return existing
        raise PhysicalDisposalClosureError(
            "Phase 17.4-B execution already has a closure qualification"
        )
    snapshot = _fresh_closure_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        execution_id=execution_id,
        now=current,
    )
    if requested_by_id in snapshot.material_actor_ids:
        raise PhysicalDisposalClosureError(
            "Post-disposal closure requester must be independent of prior material governance actors"
        )
    review_expires_at = current + PHYSICAL_DISPOSAL_CLOSURE_REVIEW_WINDOW
    closure_hash = _closure_hash(
        execution_id=execution_id,
        execution_hash=snapshot.execution.execution_hash,
        document_bindings_hash=snapshot.execution.document_bindings_hash,
        execution_receipt_chain_hash=snapshot.execution_receipt_chain_hash,
        item_outcomes_hash=snapshot.item_outcomes_hash,
        verification_snapshot_hash=snapshot.verification_snapshot_hash,
        separation_actor_set_hash=snapshot.separation_actor_set_hash,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        request_reason=reason,
    )
    qualification = PhysicalDisposalClosureQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        execution_id=execution_id,
        authorization_id=snapshot.authorization.id,
        execution_request_hash=snapshot.execution.execution_request_hash,
        execution_hash=snapshot.execution.execution_hash,
        document_bindings_hash=snapshot.execution.document_bindings_hash,
        execution_receipt_chain_hash=snapshot.execution_receipt_chain_hash,
        item_outcomes_hash=snapshot.item_outcomes_hash,
        verification_snapshot=snapshot.verification_snapshot,
        verification_snapshot_hash=snapshot.verification_snapshot_hash,
        separation_actor_set_hash=snapshot.separation_actor_set_hash,
        document_count=snapshot.document_count,
        total_file_size_bytes=snapshot.total_file_size_bytes,
        observed_local_targets_absent=True,
        observed_recovery_bytes_healthy=True,
        observed_document_rows_preserved=True,
        observed_storage_keys_preserved=True,
        observed_authority_kind="recovery_storage",
        observed_authority_tenure="durable_recovery",
        health_state="healthy",
        phase_17_4_b_executor_id=snapshot.execution.executor_id,
        phase_17_4_a_requested_by_id=snapshot.authorization.requested_by_id,
        phase_17_4_a_approved_by_id=snapshot.authorization.approved_by_id,
        requested_by_id=requested_by_id,
        request_reason=reason,
        requested_at=current,
        review_expires_at=review_expires_at,
        closure_qualification_hash=closure_hash,
        status="pending_second_approval",
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
    db.add(qualification)
    db.flush()
    _append_receipt(
        db,
        qualification=qualification,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        reason=reason,
    )
    return qualification


def qualify_physical_disposal_closure(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    qualification_id: UUID,
    qualified_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    current = _as_utc(now or _utc_now())
    reason = _normalize_reason(decision_reason)
    qualification = _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        qualification_id=qualification_id,
        for_update=True,
    )
    if not _stored_integrity_ok(qualification):
        raise PhysicalDisposalClosureError(
            "Stored post-disposal closure qualification integrity failed"
        )
    if qualification.status == "qualified":
        if (
            qualification.qualified_by_id == qualified_by_id
            and qualification.qualification_reason == reason
        ):
            return qualification, "unchanged"
        raise PhysicalDisposalClosureError("Conflicting replay for qualified closure")
    if qualification.status != "pending_second_approval":
        raise PhysicalDisposalClosureError(
            f"Closure qualification is already terminal:{qualification.status}"
        )
    if qualified_by_id == qualification.requested_by_id:
        raise PhysicalDisposalClosureError(
            "Post-disposal closure requires an independent second qualifier"
        )
    if current >= _as_utc(qualification.review_expires_at):
        qualification.status = "expired"
        qualification.terminal_by_id = qualified_by_id
        qualification.terminal_at = current
        qualification.terminal_reason = (
            "Closure review window expired before qualification"
        )
        _append_receipt(
            db,
            qualification=qualification,
            event_type="expired",
            actor_id=qualified_by_id,
            occurred_at=current,
            reason=qualification.terminal_reason,
        )
        return qualification, "expired"

    snapshot = _fresh_closure_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        execution_id=qualification.execution_id,
        now=current,
    )
    if qualified_by_id in snapshot.material_actor_ids:
        raise PhysicalDisposalClosureError(
            "Post-disposal closure qualifier must be independent of all material prior governance actors"
        )
    drifted = any(
        (
            snapshot.execution.execution_hash != qualification.execution_hash,
            snapshot.execution.execution_request_hash
            != qualification.execution_request_hash,
            snapshot.execution.document_bindings_hash
            != qualification.document_bindings_hash,
            snapshot.execution_receipt_chain_hash
            != qualification.execution_receipt_chain_hash,
            snapshot.item_outcomes_hash != qualification.item_outcomes_hash,
            snapshot.verification_snapshot_hash
            != qualification.verification_snapshot_hash,
            snapshot.verification_snapshot
            != list(qualification.verification_snapshot or []),
            snapshot.separation_actor_set_hash
            != qualification.separation_actor_set_hash,
            snapshot.document_count != qualification.document_count,
            snapshot.total_file_size_bytes
            != qualification.total_file_size_bytes,
        )
    )
    if drifted:
        qualification.status = "invalidated"
        qualification.terminal_by_id = qualified_by_id
        qualification.terminal_at = current
        qualification.terminal_reason = (
            "Post-disposal execution, storage or governance state drifted"
        )
        _append_receipt(
            db,
            qualification=qualification,
            event_type="invalidated",
            actor_id=qualified_by_id,
            occurred_at=current,
            reason=qualification.terminal_reason,
        )
        return qualification, "invalidated"

    qualification.status = "qualified"
    qualification.qualified_by_id = qualified_by_id
    qualification.qualified_at = current
    qualification.qualification_reason = reason
    qualification.decision_hash = _decision_hash(
        qualification,
        qualified_by_id=qualified_by_id,
        qualified_at=current,
        reason=reason,
    )
    _append_receipt(
        db,
        qualification=qualification,
        event_type="qualified",
        actor_id=qualified_by_id,
        occurred_at=current,
        reason=reason,
    )
    return qualification, "qualified"


def reject_physical_disposal_closure(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    qualification_id: UUID,
    rejected_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
):
    current = _as_utc(now or _utc_now())
    reason = _normalize_reason(decision_reason)
    qualification = _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        qualification_id=qualification_id,
        for_update=True,
    )
    if not _stored_integrity_ok(qualification):
        raise PhysicalDisposalClosureError(
            "Stored post-disposal closure qualification integrity failed"
        )
    if qualification.status == "rejected":
        if (
            qualification.terminal_by_id == rejected_by_id
            and qualification.terminal_reason == reason
        ):
            return qualification, "unchanged"
        raise PhysicalDisposalClosureError("Conflicting replay for rejected closure")
    if qualification.status != "pending_second_approval":
        raise PhysicalDisposalClosureError(
            f"Closure qualification is already terminal:{qualification.status}"
        )
    if rejected_by_id == qualification.requested_by_id:
        raise PhysicalDisposalClosureError(
            "Post-disposal closure rejection requires an independent actor"
        )
    event = "rejected"
    terminal_reason = reason
    if current >= _as_utc(qualification.review_expires_at):
        event = "expired"
        terminal_reason = "Closure review window expired before rejection"
    qualification.status = event
    qualification.terminal_by_id = rejected_by_id
    qualification.terminal_at = current
    qualification.terminal_reason = terminal_reason
    _append_receipt(
        db,
        qualification=qualification,
        event_type=event,
        actor_id=rejected_by_id,
        occurred_at=current,
        reason=terminal_reason,
    )
    return qualification, event


def get_physical_disposal_closure(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    qualification_id: UUID,
) -> PhysicalDisposalClosureQualification:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        qualification_id=qualification_id,
    )


def list_physical_disposal_closure_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    qualification_id: UUID,
) -> list[PhysicalDisposalClosureReceipt]:
    qualification = get_physical_disposal_closure(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        qualification_id=qualification_id,
    )
    return list(
        db.scalars(
            select(PhysicalDisposalClosureReceipt)
            .where(
                PhysicalDisposalClosureReceipt.organization_id == organization_id,
                PhysicalDisposalClosureReceipt.claim_id == claim_id,
                PhysicalDisposalClosureReceipt.qualification_id == qualification.id,
            )
            .order_by(PhysicalDisposalClosureReceipt.sequence_number.asc())
        ).all()
    )
