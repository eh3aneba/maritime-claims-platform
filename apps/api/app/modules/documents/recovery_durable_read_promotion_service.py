from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_read_promotion_models import (
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationUnavailable,
    _assert_replica_matches_source,
    _snapshot_local,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_read_cutover_service import (
    RecoveryRoutableReadCutoverConflict,
    RecoveryRoutableReadCutoverNotFound,
    RecoveryRoutableReadCutoverUnavailable,
    _load_document,
    _load_replica,
    _read_verified_candidate,
)
from app.modules.documents.recovery_routable_read_qualification_models import (
    EvidenceRecoveryRoutableReadQualification,
    EvidenceRecoveryRoutableReadQualificationReceipt,
)
from app.modules.documents.recovery_routable_read_qualification_service import (
    RecoveryRoutableReadQualificationConflict,
    RecoveryRoutableReadQualificationNotFound,
    _get_qualification,
    _get_route,
    _load_snapshot as _load_qualification_snapshot,
    _matches_snapshot as _matches_qualification_snapshot,
)

DURABLE_READ_PROMOTION_AUTHORIZATION_WINDOW = timedelta(minutes=10)


class RecoveryDurableReadPromotionAuthorizationError(RuntimeError):
    pass


class RecoveryDurableReadPromotionAuthorizationNotFound(
    RecoveryDurableReadPromotionAuthorizationError
):
    pass


class RecoveryDurableReadPromotionAuthorizationConflict(
    RecoveryDurableReadPromotionAuthorizationError
):
    pass


class RecoveryDurableReadPromotionAuthorizationUnavailable(
    RecoveryDurableReadPromotionAuthorizationError
):
    pass


@dataclass(frozen=True)
class DurableReadPromotionAuthorizationSnapshot:
    qualification_id: UUID
    qualification_receipt_id: UUID
    replica_id: UUID
    qualification_hash: str
    qualification_bundle_hash: str
    qualification_request_snapshot_hash: str
    qualification_receipt_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    local_storage_key_fingerprint: str
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    route_version_at_request: int
    integrity_proof_hash: str
    request_snapshot_hash: str
    phase_k_qualified_by_id: UUID
    first_activated_by_id: UUID
    second_activated_by_id: UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _qualification_receipt(
    db: Session,
    *,
    qualification: EvidenceRecoveryRoutableReadQualification,
) -> EvidenceRecoveryRoutableReadQualificationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryRoutableReadQualificationReceipt).where(
                EvidenceRecoveryRoutableReadQualificationReceipt.organization_id
                == qualification.organization_id,
                EvidenceRecoveryRoutableReadQualificationReceipt.claim_id
                == qualification.claim_id,
                EvidenceRecoveryRoutableReadQualificationReceipt.document_id
                == qualification.document_id,
                EvidenceRecoveryRoutableReadQualificationReceipt.qualification_id
                == qualification.id,
                EvidenceRecoveryRoutableReadQualificationReceipt.phase == "qualified",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Qualified recovery read evidence must have exactly one qualification receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.qualification_bundle_hash == qualification.qualification_bundle_hash,
            receipt.request_snapshot_hash == qualification.request_snapshot_hash,
            receipt.qualification_hash == qualification.qualification_hash,
            receipt.actor_id == qualification.qualified_by_id,
            qualification.qualified_at is not None,
            _as_utc(receipt.transitioned_at) == _as_utc(qualification.qualified_at),
            receipt.routable_authority_created is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Phase K qualification receipt lineage is inconsistent"
        )
    return receipt


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
) -> DurableReadPromotionAuthorizationSnapshot:
    try:
        qualification = _get_qualification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
        )
        if (
            qualification.status != "qualified"
            or qualification.qualified_by_id is None
            or qualification.qualified_at is None
        ):
            raise RecoveryDurableReadPromotionAuthorizationConflict(
                "Only a qualified Phase K record can request durable read promotion authorization"
            )
        if any(
            (
                qualification.routable_authority_created,
                qualification.read_path_switched,
                qualification.write_path_switched,
                qualification.document_storage_key_mutated,
                qualification.authoritative_storage_changed,
                qualification.destructive_action_performed,
                qualification.s3_delete_performed,
                qualification.local_delete_performed,
            )
        ):
            raise RecoveryDurableReadPromotionAuthorizationConflict(
                "Phase K qualification crossed its non-routable safety boundary"
            )

        qualification_snapshot = _load_qualification_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            cutover_lease_ids=[
                qualification.first_cutover_lease_id,
                qualification.second_cutover_lease_id,
            ],
        )
        if not _matches_qualification_snapshot(qualification, qualification_snapshot):
            raise RecoveryDurableReadPromotionAuthorizationConflict(
                "Phase K qualification lineage drifted before durable read authorization"
            )
        qualification_receipt = _qualification_receipt(
            db,
            qualification=qualification,
        )

        route = _get_route(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        if not all(
            (
                route.route_class == "local_source",
                route.active_lease_id is None,
                route.active_replica_id is None,
                route.read_path_switched is False,
                route.write_path_switched is False,
                route.document_storage_key_mutated is False,
                route.authoritative_storage_changed is False,
                route.destructive_action_performed is False,
                route.route_version == qualification.route_version_at_request,
                route.source_authority_fingerprint
                == qualification.source_authority_fingerprint,
                route.candidate_authority_fingerprint
                == qualification.candidate_authority_fingerprint,
                route.configuration_fingerprint == qualification.configuration_fingerprint,
            )
        ):
            raise RecoveryDurableReadPromotionAuthorizationConflict(
                "Live read route changed after Phase K qualification"
            )

        document = _load_document(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        replica = _load_replica(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            replica_id=qualification.replica_id,
        )
        local_snapshot = _snapshot_local(document)
        _assert_replica_matches_source(replica, local_snapshot)
        candidate_payload = _read_verified_candidate(replica)
        candidate_hash = hashlib.sha256(candidate_payload).hexdigest()
        if not all(
            (
                replica.replica_hash == qualification.replica_hash,
                replica.source_file_hash == qualification.source_file_hash,
                replica.source_file_size_bytes == qualification.source_file_size_bytes,
                replica.recovery_bucket_fingerprint
                == qualification.recovery_bucket_fingerprint,
                local_snapshot.file_hash == qualification.source_file_hash,
                local_snapshot.file_size_bytes == qualification.source_file_size_bytes,
                candidate_hash == qualification.source_file_hash,
                len(candidate_payload) == qualification.source_file_size_bytes,
            )
        ):
            raise RecoveryDurableReadPromotionAuthorizationConflict(
                "Fresh local or recovery candidate integrity no longer matches Phase K"
            )

        integrity_proof_hash = _canonical_hash(
            {
                "qualification_id": str(qualification.id),
                "qualification_hash": qualification.qualification_hash,
                "qualification_receipt_id": str(qualification_receipt.id),
                "qualification_receipt_hash": qualification_receipt.receipt_hash,
                "replica_id": str(replica.id),
                "replica_hash": replica.replica_hash,
                "source_file_hash": local_snapshot.file_hash,
                "source_file_size_bytes": local_snapshot.file_size_bytes,
                "local_storage_key_fingerprint": local_snapshot.storage_key_fingerprint,
                "recovery_bucket_fingerprint": qualification.recovery_bucket_fingerprint,
                "candidate_storage_key_fingerprint": qualification.candidate_storage_key_fingerprint,
                "candidate_sha256": candidate_hash,
                "candidate_size_bytes": len(candidate_payload),
                "route_version": route.route_version,
                "route_class": "local_source",
                "source_authority_fingerprint": qualification.source_authority_fingerprint,
                "candidate_authority_fingerprint": qualification.candidate_authority_fingerprint,
                "configuration_fingerprint": qualification.configuration_fingerprint,
                "read_path_switched": False,
                "write_path_switched": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        request_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "qualification_id": str(qualification.id),
                "qualification_bundle_hash": qualification.qualification_bundle_hash,
                "qualification_request_snapshot_hash": qualification.request_snapshot_hash,
                "integrity_proof_hash": integrity_proof_hash,
                "route_version_at_request": route.route_version,
                "mode": "durable_read_promotion_governance_authorization_only",
                "routable_authority_created": False,
                "durable_read_route_created": False,
                "read_path_switched": False,
                "write_path_switched": False,
                "authoritative_storage_changed": False,
                "destructive_action_performed": False,
            }
        )
        return DurableReadPromotionAuthorizationSnapshot(
            qualification_id=qualification.id,
            qualification_receipt_id=qualification_receipt.id,
            replica_id=qualification.replica_id,
            qualification_hash=qualification.qualification_hash,
            qualification_bundle_hash=qualification.qualification_bundle_hash,
            qualification_request_snapshot_hash=qualification.request_snapshot_hash,
            qualification_receipt_hash=qualification_receipt.receipt_hash,
            replica_hash=qualification.replica_hash,
            source_file_hash=qualification.source_file_hash,
            source_file_size_bytes=qualification.source_file_size_bytes,
            local_storage_key_fingerprint=local_snapshot.storage_key_fingerprint,
            recovery_bucket_fingerprint=qualification.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=qualification.candidate_storage_key_fingerprint,
            source_authority_fingerprint=qualification.source_authority_fingerprint,
            candidate_authority_fingerprint=qualification.candidate_authority_fingerprint,
            configuration_fingerprint=qualification.configuration_fingerprint,
            route_version_at_request=route.route_version,
            integrity_proof_hash=integrity_proof_hash,
            request_snapshot_hash=request_snapshot_hash,
            phase_k_qualified_by_id=qualification.qualified_by_id,
            first_activated_by_id=qualification.first_activated_by_id,
            second_activated_by_id=qualification.second_activated_by_id,
        )
    except RecoveryDurableReadPromotionAuthorizationError:
        raise
    except RecoveryRoutableReadQualificationNotFound as exc:
        raise RecoveryDurableReadPromotionAuthorizationNotFound(str(exc)) from exc
    except RecoveryRoutableReadQualificationConflict as exc:
        raise RecoveryDurableReadPromotionAuthorizationConflict(str(exc)) from exc
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryDurableReadPromotionAuthorizationNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict) as exc:
        raise RecoveryDurableReadPromotionAuthorizationConflict(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadPromotionAuthorizationUnavailable(str(exc)) from exc


def _matches_snapshot(
    authorization: EvidenceRecoveryDurableReadPromotionAuthorization,
    snapshot: DurableReadPromotionAuthorizationSnapshot,
) -> bool:
    return all(
        (
            authorization.qualification_id == snapshot.qualification_id,
            authorization.qualification_receipt_id == snapshot.qualification_receipt_id,
            authorization.replica_id == snapshot.replica_id,
            authorization.qualification_hash == snapshot.qualification_hash,
            authorization.qualification_bundle_hash == snapshot.qualification_bundle_hash,
            authorization.qualification_request_snapshot_hash
            == snapshot.qualification_request_snapshot_hash,
            authorization.qualification_receipt_hash == snapshot.qualification_receipt_hash,
            authorization.replica_hash == snapshot.replica_hash,
            authorization.source_file_hash == snapshot.source_file_hash,
            authorization.source_file_size_bytes == snapshot.source_file_size_bytes,
            authorization.local_storage_key_fingerprint
            == snapshot.local_storage_key_fingerprint,
            authorization.recovery_bucket_fingerprint
            == snapshot.recovery_bucket_fingerprint,
            authorization.candidate_storage_key_fingerprint
            == snapshot.candidate_storage_key_fingerprint,
            authorization.source_authority_fingerprint
            == snapshot.source_authority_fingerprint,
            authorization.candidate_authority_fingerprint
            == snapshot.candidate_authority_fingerprint,
            authorization.configuration_fingerprint == snapshot.configuration_fingerprint,
            authorization.route_version_at_request == snapshot.route_version_at_request,
            authorization.integrity_proof_hash == snapshot.integrity_proof_hash,
            authorization.request_snapshot_hash == snapshot.request_snapshot_hash,
            authorization.phase_k_qualified_by_id == snapshot.phase_k_qualified_by_id,
            authorization.first_activated_by_id == snapshot.first_activated_by_id,
            authorization.second_activated_by_id == snapshot.second_activated_by_id,
        )
    )


def _new_receipt(
    *,
    authorization: EvidenceRecoveryDurableReadPromotionAuthorization,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadPromotionAuthorizationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "qualification_id": str(authorization.qualification_id),
            "phase": phase,
            "qualification_hash": authorization.qualification_hash,
            "integrity_proof_hash": authorization.integrity_proof_hash,
            "request_snapshot_hash": authorization.request_snapshot_hash,
            "authorization_hash": authorization.authorization_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": False,
            "durable_read_route_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryDurableReadPromotionAuthorizationReceipt(
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_id=authorization.document_id,
        authorization_id=authorization.id,
        qualification_id=authorization.qualification_id,
        phase=phase,
        qualification_hash=authorization.qualification_hash,
        integrity_proof_hash=authorization.integrity_proof_hash,
        request_snapshot_hash=authorization.request_snapshot_hash,
        authorization_hash=authorization.authorization_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=False,
        durable_read_route_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )


def _terminalize(
    db: Session,
    *,
    authorization: EvidenceRecoveryDurableReadPromotionAuthorization,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadPromotionAuthorizationReceipt:
    authorization.status = status
    authorization.terminal_by_id = actor_id
    authorization.terminal_at = now
    authorization.terminal_reason = reason
    receipt = _new_receipt(
        authorization=authorization,
        phase=status,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_durable_read_promotion_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Durable read promotion authorization request reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadPromotionAuthorization)
        .where(
            EvidenceRecoveryDurableReadPromotionAuthorization.organization_id
            == organization_id,
            EvidenceRecoveryDurableReadPromotionAuthorization.claim_id == claim_id,
            EvidenceRecoveryDurableReadPromotionAuthorization.document_id == document_id,
            EvidenceRecoveryDurableReadPromotionAuthorization.qualification_id
            == qualification_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if not _matches_snapshot(existing, snapshot):
            if existing.status == "pending_second_approval":
                receipt = _terminalize(
                    db,
                    authorization=existing,
                    status="invalidated",
                    actor_id=requested_by_id,
                    reason="Durable read promotion authorization lineage drifted before request replay",
                    now=current_time,
                )
                return existing, receipt, "invalidated"
            raise RecoveryDurableReadPromotionAuthorizationConflict(
                "Existing durable read promotion authorization no longer matches the current evidence snapshot"
            )
        if not (
            existing.requested_by_id == requested_by_id
            and existing.request_reason == normalized_reason
        ):
            raise RecoveryDurableReadPromotionAuthorizationConflict(
                "An authorization already exists for this qualification with different request semantics"
            )
        return existing, None, "unchanged"

    authorization_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "qualification_id": str(qualification_id),
            "qualification_hash": snapshot.qualification_hash,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "request_reason": normalized_reason,
            "mode": "non_routable_durable_read_promotion_authorization",
        }
    )
    authorization = EvidenceRecoveryDurableReadPromotionAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=snapshot.qualification_id,
        qualification_receipt_id=snapshot.qualification_receipt_id,
        replica_id=snapshot.replica_id,
        qualification_hash=snapshot.qualification_hash,
        qualification_bundle_hash=snapshot.qualification_bundle_hash,
        qualification_request_snapshot_hash=snapshot.qualification_request_snapshot_hash,
        qualification_receipt_hash=snapshot.qualification_receipt_hash,
        replica_hash=snapshot.replica_hash,
        source_file_hash=snapshot.source_file_hash,
        source_file_size_bytes=snapshot.source_file_size_bytes,
        local_storage_key_fingerprint=snapshot.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=snapshot.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=snapshot.candidate_storage_key_fingerprint,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        route_version_at_request=snapshot.route_version_at_request,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        authorization_hash=authorization_hash,
        phase_k_qualified_by_id=snapshot.phase_k_qualified_by_id,
        first_activated_by_id=snapshot.first_activated_by_id,
        second_activated_by_id=snapshot.second_activated_by_id,
        status="pending_second_approval",
        authorization_expires_at=current_time
        + DURABLE_READ_PROMOTION_AUTHORIZATION_WINDOW,
        requested_by_id=requested_by_id,
        requested_at=current_time,
        request_reason=normalized_reason,
        routable_authority_created=False,
        durable_read_route_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(authorization)
    db.flush()
    receipt = _new_receipt(
        authorization=authorization,
        phase="requested",
        actor_id=requested_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "pending_second_approval"


def approve_durable_read_promotion_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Durable read promotion authorization approval reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if authorization.status == "approved":
        if (
            authorization.approved_by_id == approved_by_id
            and authorization.approval_reason == normalized_reason
        ):
            return authorization, None, "unchanged"
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Approved authorization replay does not match the original approval"
        )
    if authorization.status != "pending_second_approval":
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Only a pending durable read promotion authorization can be approved"
        )
    if current_time >= _as_utc(authorization.authorization_expires_at):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="expired",
            actor_id=approved_by_id,
            reason="Durable read promotion authorization approval window expired",
            now=current_time,
        )
        return authorization, receipt, "expired"
    if authorization.requested_by_id == approved_by_id:
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Durable read promotion authorization requires a different Admin from the requester"
        )
    if approved_by_id in {
        authorization.phase_k_qualified_by_id,
        authorization.first_activated_by_id,
        authorization.second_activated_by_id,
    }:
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Approver must differ from the Phase K qualifier and both qualifying read-cutover activators"
        )

    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=authorization.qualification_id,
        )
    except (
        RecoveryDurableReadPromotionAuthorizationNotFound,
        RecoveryDurableReadPromotionAuthorizationConflict,
        RecoveryDurableReadPromotionAuthorizationUnavailable,
    ) as exc:
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason=f"Fresh durable read promotion preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return authorization, receipt, "invalidated"
    if not _matches_snapshot(authorization, snapshot):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Durable read promotion authorization snapshot drifted before approval",
            now=current_time,
        )
        return authorization, receipt, "invalidated"

    authorization.status = "approved"
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current_time
    authorization.approval_reason = normalized_reason
    receipt = _new_receipt(
        authorization=authorization,
        phase="approved",
        actor_id=approved_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "approved"


def reject_durable_read_promotion_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Durable read promotion authorization rejection reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        for_update=True,
    )
    if authorization.status == "rejected":
        if (
            authorization.rejected_by_id == rejected_by_id
            and authorization.rejection_reason == normalized_reason
        ):
            return authorization, None, "unchanged"
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Rejected authorization replay does not match the original rejection"
        )
    if authorization.status != "pending_second_approval":
        raise RecoveryDurableReadPromotionAuthorizationConflict(
            "Only a pending durable read promotion authorization can be rejected"
        )
    authorization.status = "rejected"
    authorization.rejected_by_id = rejected_by_id
    authorization.rejected_at = current_time
    authorization.rejection_reason = normalized_reason
    receipt = _new_receipt(
        authorization=authorization,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return authorization, receipt, "rejected"


def _get_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryDurableReadPromotionAuthorization:
    stmt = select(EvidenceRecoveryDurableReadPromotionAuthorization).where(
        EvidenceRecoveryDurableReadPromotionAuthorization.id == authorization_id,
        EvidenceRecoveryDurableReadPromotionAuthorization.organization_id
        == organization_id,
        EvidenceRecoveryDurableReadPromotionAuthorization.claim_id == claim_id,
        EvidenceRecoveryDurableReadPromotionAuthorization.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RecoveryDurableReadPromotionAuthorizationNotFound(
            "Recovery durable read promotion authorization not found"
        )
    return authorization


def get_durable_read_promotion_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> EvidenceRecoveryDurableReadPromotionAuthorization:
    return _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )


def list_durable_read_promotion_authorization_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
) -> list[EvidenceRecoveryDurableReadPromotionAuthorizationReceipt]:
    _get_authorization(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadPromotionAuthorizationReceipt)
            .where(
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.organization_id
                == organization_id,
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.claim_id
                == claim_id,
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.document_id
                == document_id,
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.authorization_id
                == authorization_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadPromotionAuthorizationReceipt.id.asc(),
            )
        ).all()
    )
