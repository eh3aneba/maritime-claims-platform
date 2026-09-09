from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_authority_switch_models import (
    EvidenceRecoveryAuthoritySwitchReceipt,
    EvidenceRecoveryAuthoritySwitchRehearsal,
)
from app.modules.documents.recovery_promotion_service import (
    RecoveryPromotionConflict,
    RecoveryPromotionNotFound,
    RecoveryPromotionUnavailable,
    _as_utc,
    _build_promotion_snapshot,
    _get_attestation,
    _semantic_matches,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_shadow_models import (
    EvidenceRecoveryShadowPromotion,
    EvidenceRecoveryShadowVerification,
)
from app.modules.documents.recovery_shadow_service import (
    RecoveryShadowConflict,
    RecoveryShadowNotFound,
    RecoveryShadowUnavailable,
    _assert_attestation_safety,
    _assert_shadow_lineage,
    _verify_shadow_path,
)

AUTHORITY_SWITCH_ACTIVATION_WINDOW = timedelta(minutes=30)


class RecoveryAuthoritySwitchError(RuntimeError):
    pass


class RecoveryAuthoritySwitchNotFound(RecoveryAuthoritySwitchError):
    pass


class RecoveryAuthoritySwitchConflict(RecoveryAuthoritySwitchError):
    pass


class RecoveryAuthoritySwitchUnavailable(RecoveryAuthoritySwitchError):
    pass


@dataclass(frozen=True)
class AuthoritySwitchSnapshot:
    shadow_promotion_id: UUID
    attestation_id: UUID
    replica_id: UUID
    restore_rehearsal_id: UUID
    restore_verification_id: UUID
    shadow_verification_id: UUID
    attestation_request_snapshot_hash: str
    promotion_plan_hash: str
    configuration_fingerprint: str
    shadow_promotion_hash: str
    shadow_verification_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    source_document_updated_at: datetime
    source_storage_key_fingerprint: str
    shadow_storage_key_fingerprint: str
    lineage_hash: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    attestation_expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _latest_shadow_verification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    shadow_promotion_id: UUID,
) -> EvidenceRecoveryShadowVerification:
    verification = db.scalar(
        select(EvidenceRecoveryShadowVerification)
        .where(
            EvidenceRecoveryShadowVerification.organization_id == organization_id,
            EvidenceRecoveryShadowVerification.claim_id == claim_id,
            EvidenceRecoveryShadowVerification.document_id == document_id,
            EvidenceRecoveryShadowVerification.shadow_promotion_id == shadow_promotion_id,
        )
        .order_by(
            EvidenceRecoveryShadowVerification.verified_at.desc(),
            EvidenceRecoveryShadowVerification.created_at.desc(),
            EvidenceRecoveryShadowVerification.id.desc(),
        )
        .limit(1)
    )
    if verification is None:
        raise RecoveryAuthoritySwitchConflict("Shadow promotion has no verification lineage")
    return verification


def _assert_shadow_verification_matches(
    verification: EvidenceRecoveryShadowVerification,
    *,
    shadow: EvidenceRecoveryShadowPromotion,
) -> None:
    expected = all(
        (
            verification.attestation_id == shadow.attestation_id,
            verification.shadow_promotion_id == shadow.id,
            verification.expected_file_hash == shadow.source_file_hash,
            verification.expected_file_size_bytes == shadow.source_file_size_bytes,
            verification.shadow_file_hash == shadow.shadow_file_hash,
            verification.shadow_file_size_bytes == shadow.shadow_file_size_bytes,
            verification.promotion_plan_hash == shadow.promotion_plan_hash,
            verification.configuration_fingerprint == shadow.configuration_fingerprint,
            verification.shadow_storage_key_fingerprint == shadow.shadow_storage_key_fingerprint,
        )
    )
    if not expected:
        raise RecoveryAuthoritySwitchConflict(
            "Latest shadow verification does not match the current shadow promotion lineage"
        )


def _load_switch_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    shadow_promotion_id: UUID,
    now: datetime | None = None,
    allow_attestation_expired: bool = False,
) -> AuthoritySwitchSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        shadow = db.scalar(
            select(EvidenceRecoveryShadowPromotion).where(
                EvidenceRecoveryShadowPromotion.id == shadow_promotion_id,
                EvidenceRecoveryShadowPromotion.organization_id == organization_id,
                EvidenceRecoveryShadowPromotion.claim_id == claim_id,
                EvidenceRecoveryShadowPromotion.document_id == document_id,
            )
        )
        if shadow is None:
            raise RecoveryAuthoritySwitchNotFound("Recovery shadow promotion not found")

        attestation = _get_attestation(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=shadow.attestation_id,
        )
        if attestation.status != "approved" or attestation.approved_by_id is None or attestation.approved_at is None:
            raise RecoveryAuthoritySwitchConflict("Recovery promotion attestation is not approved")
        if not allow_attestation_expired and current_time >= _as_utc(attestation.attestation_expires_at):
            raise RecoveryAuthoritySwitchConflict("Recovery promotion attestation expired")
        _assert_attestation_safety(attestation)

        promotion_snapshot = _build_promotion_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        if not _semantic_matches(attestation, promotion_snapshot):
            raise RecoveryAuthoritySwitchConflict("Recovery promotion lineage drifted")
        _assert_shadow_lineage(shadow, attestation=attestation)
        verified_shadow = _verify_shadow_path(
            shadow.shadow_storage_key,
            expected_hash=shadow.source_file_hash,
            expected_size=shadow.source_file_size_bytes,
        )
        if (
            verified_shadow.file_hash != shadow.shadow_file_hash
            or verified_shadow.file_size_bytes != shadow.shadow_file_size_bytes
            or verified_shadow.shadow_storage_key_fingerprint != shadow.shadow_storage_key_fingerprint
        ):
            raise RecoveryAuthoritySwitchConflict("Recovery shadow bytes drifted")

        shadow_verification = _latest_shadow_verification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            shadow_promotion_id=shadow.id,
        )
        _assert_shadow_verification_matches(shadow_verification, shadow=shadow)

        source_authority_fingerprint = _canonical_hash(
            {
                "authority_class": "authoritative_source",
                "document_id": str(document_id),
                "file_hash": shadow.source_file_hash,
                "file_size_bytes": shadow.source_file_size_bytes,
                "document_updated_at": _utc_iso(shadow.source_document_updated_at),
                "storage_key_fingerprint": shadow.source_storage_key_fingerprint,
            }
        )
        candidate_authority_fingerprint = _canonical_hash(
            {
                "authority_class": "recovery_shadow_candidate",
                "document_id": str(document_id),
                "shadow_promotion_id": str(shadow.id),
                "shadow_promotion_hash": shadow.shadow_promotion_hash,
                "file_hash": shadow.shadow_file_hash,
                "file_size_bytes": shadow.shadow_file_size_bytes,
                "storage_key_fingerprint": shadow.shadow_storage_key_fingerprint,
            }
        )
        lineage_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "shadow_promotion_id": str(shadow.id),
                "attestation_id": str(shadow.attestation_id),
                "replica_id": str(shadow.replica_id),
                "restore_rehearsal_id": str(shadow.rehearsal_id),
                "restore_verification_id": str(shadow.restore_verification_id),
                "shadow_verification_id": str(shadow_verification.id),
                "attestation_request_snapshot_hash": shadow.attestation_request_snapshot_hash,
                "promotion_plan_hash": shadow.promotion_plan_hash,
                "configuration_fingerprint": shadow.configuration_fingerprint,
                "shadow_promotion_hash": shadow.shadow_promotion_hash,
                "shadow_verification_hash": shadow_verification.verification_hash,
                "source_file_hash": shadow.source_file_hash,
                "source_file_size_bytes": shadow.source_file_size_bytes,
                "source_storage_key_fingerprint": shadow.source_storage_key_fingerprint,
                "shadow_storage_key_fingerprint": shadow.shadow_storage_key_fingerprint,
            }
        )
        return AuthoritySwitchSnapshot(
            shadow_promotion_id=shadow.id,
            attestation_id=shadow.attestation_id,
            replica_id=shadow.replica_id,
            restore_rehearsal_id=shadow.rehearsal_id,
            restore_verification_id=shadow.restore_verification_id,
            shadow_verification_id=shadow_verification.id,
            attestation_request_snapshot_hash=shadow.attestation_request_snapshot_hash,
            promotion_plan_hash=shadow.promotion_plan_hash,
            configuration_fingerprint=shadow.configuration_fingerprint,
            shadow_promotion_hash=shadow.shadow_promotion_hash,
            shadow_verification_hash=shadow_verification.verification_hash,
            source_file_hash=shadow.source_file_hash,
            source_file_size_bytes=shadow.source_file_size_bytes,
            source_document_updated_at=shadow.source_document_updated_at,
            source_storage_key_fingerprint=shadow.source_storage_key_fingerprint,
            shadow_storage_key_fingerprint=shadow.shadow_storage_key_fingerprint,
            lineage_hash=lineage_hash,
            source_authority_fingerprint=source_authority_fingerprint,
            candidate_authority_fingerprint=candidate_authority_fingerprint,
            attestation_expires_at=attestation.attestation_expires_at,
        )
    except RecoveryAuthoritySwitchError:
        raise
    except RecoveryPromotionNotFound as exc:
        raise RecoveryAuthoritySwitchNotFound(str(exc)) from exc
    except RecoveryPromotionConflict as exc:
        raise RecoveryAuthoritySwitchConflict(str(exc)) from exc
    except RecoveryPromotionUnavailable as exc:
        raise RecoveryAuthoritySwitchUnavailable(str(exc)) from exc
    except RecoveryShadowNotFound as exc:
        raise RecoveryAuthoritySwitchNotFound(str(exc)) from exc
    except RecoveryShadowConflict as exc:
        raise RecoveryAuthoritySwitchConflict(str(exc)) from exc
    except RecoveryShadowUnavailable as exc:
        raise RecoveryAuthoritySwitchUnavailable(str(exc)) from exc


def _get_rehearsal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryAuthoritySwitchRehearsal:
    stmt = select(EvidenceRecoveryAuthoritySwitchRehearsal).where(
        EvidenceRecoveryAuthoritySwitchRehearsal.id == rehearsal_id,
        EvidenceRecoveryAuthoritySwitchRehearsal.organization_id == organization_id,
        EvidenceRecoveryAuthoritySwitchRehearsal.claim_id == claim_id,
        EvidenceRecoveryAuthoritySwitchRehearsal.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    item = db.scalar(stmt)
    if item is None:
        raise RecoveryAuthoritySwitchNotFound("Recovery authority-switch rehearsal not found")
    return item


def _matches_snapshot(
    rehearsal: EvidenceRecoveryAuthoritySwitchRehearsal,
    snapshot: AuthoritySwitchSnapshot,
) -> bool:
    return all(
        (
            rehearsal.shadow_promotion_id == snapshot.shadow_promotion_id,
            rehearsal.attestation_id == snapshot.attestation_id,
            rehearsal.replica_id == snapshot.replica_id,
            rehearsal.restore_rehearsal_id == snapshot.restore_rehearsal_id,
            rehearsal.restore_verification_id == snapshot.restore_verification_id,
            rehearsal.shadow_verification_id == snapshot.shadow_verification_id,
            rehearsal.attestation_request_snapshot_hash == snapshot.attestation_request_snapshot_hash,
            rehearsal.promotion_plan_hash == snapshot.promotion_plan_hash,
            rehearsal.configuration_fingerprint == snapshot.configuration_fingerprint,
            rehearsal.shadow_promotion_hash == snapshot.shadow_promotion_hash,
            rehearsal.shadow_verification_hash == snapshot.shadow_verification_hash,
            rehearsal.source_file_hash == snapshot.source_file_hash,
            rehearsal.source_storage_key_fingerprint == snapshot.source_storage_key_fingerprint,
            rehearsal.shadow_storage_key_fingerprint == snapshot.shadow_storage_key_fingerprint,
            rehearsal.lineage_hash == snapshot.lineage_hash,
            rehearsal.source_authority_fingerprint == snapshot.source_authority_fingerprint,
            rehearsal.candidate_authority_fingerprint == snapshot.candidate_authority_fingerprint,
        )
    )


def _new_receipt(
    *,
    rehearsal: EvidenceRecoveryAuthoritySwitchRehearsal,
    phase: str,
    from_class: str,
    to_class: str,
    from_fingerprint: str,
    to_fingerprint: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryAuthoritySwitchReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "authority_switch_rehearsal_id": str(rehearsal.id),
            "shadow_promotion_id": str(rehearsal.shadow_promotion_id),
            "phase": phase,
            "from_authority_class": from_class,
            "to_authority_class": to_class,
            "from_authority_fingerprint": from_fingerprint,
            "to_authority_fingerprint": to_fingerprint,
            "lineage_hash": rehearsal.lineage_hash,
            "contract_hash": rehearsal.contract_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "cutover_performed": False,
            "authoritative_storage_changed": False,
        }
    )
    return EvidenceRecoveryAuthoritySwitchReceipt(
        organization_id=rehearsal.organization_id,
        claim_id=rehearsal.claim_id,
        document_id=rehearsal.document_id,
        authority_switch_rehearsal_id=rehearsal.id,
        shadow_promotion_id=rehearsal.shadow_promotion_id,
        phase=phase,
        from_authority_class=from_class,
        to_authority_class=to_class,
        from_authority_fingerprint=from_fingerprint,
        to_authority_fingerprint=to_fingerprint,
        lineage_hash=rehearsal.lineage_hash,
        contract_hash=rehearsal.contract_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        cutover_performed=False,
        authoritative_storage_changed=False,
    )


def _terminalize(
    db: Session,
    *,
    rehearsal: EvidenceRecoveryAuthoritySwitchRehearsal,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryAuthoritySwitchReceipt:
    rehearsal.status = status
    rehearsal.terminal_by_id = actor_id
    rehearsal.terminal_at = now
    rehearsal.terminal_reason = reason
    receipt = _new_receipt(
        rehearsal=rehearsal,
        phase=status,
        from_class=rehearsal.virtual_authority_class,
        to_class=rehearsal.virtual_authority_class,
        from_fingerprint=rehearsal.virtual_authority_fingerprint,
        to_fingerprint=rehearsal.virtual_authority_fingerprint,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def prepare_recovery_authority_switch_rehearsal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    shadow_promotion_id: UUID,
    prepared_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryAuthoritySwitchRehearsal, EvidenceRecoveryAuthoritySwitchReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryAuthoritySwitchConflict("Authority-switch preparation reason is required")
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_switch_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        shadow_promotion_id=shadow_promotion_id,
        now=current_time,
    )
    existing = db.scalar(
        select(EvidenceRecoveryAuthoritySwitchRehearsal)
        .where(
            EvidenceRecoveryAuthoritySwitchRehearsal.organization_id == organization_id,
            EvidenceRecoveryAuthoritySwitchRehearsal.claim_id == claim_id,
            EvidenceRecoveryAuthoritySwitchRehearsal.document_id == document_id,
            EvidenceRecoveryAuthoritySwitchRehearsal.shadow_promotion_id == shadow_promotion_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if _matches_snapshot(existing, snapshot) and existing.status in {"prepared", "activated", "rolled_back"}:
            return existing, None, "unchanged"
        if existing.status == "prepared":
            receipt = _terminalize(
                db,
                rehearsal=existing,
                status="invalidated",
                actor_id=prepared_by_id,
                reason="Authority-switch lineage drifted before preparation replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        raise RecoveryAuthoritySwitchConflict("A terminal authority-switch rehearsal already exists for this shadow promotion")

    lease_expires_at = min(
        current_time + AUTHORITY_SWITCH_ACTIVATION_WINDOW,
        _as_utc(snapshot.attestation_expires_at),
    )
    if lease_expires_at <= current_time:
        raise RecoveryAuthoritySwitchConflict("Authority-switch activation window is not available")
    contract_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "shadow_promotion_id": str(snapshot.shadow_promotion_id),
            "lineage_hash": snapshot.lineage_hash,
            "source_authority_fingerprint": snapshot.source_authority_fingerprint,
            "candidate_authority_fingerprint": snapshot.candidate_authority_fingerprint,
            "prepared_by_id": str(prepared_by_id),
            "prepared_at": _utc_iso(current_time),
            "activation_lease_expires_at": _utc_iso(lease_expires_at),
            "mode": "virtual_reversible_rehearsal_only",
            "cutover_performed": False,
            "authoritative_storage_changed": False,
        }
    )
    rehearsal = EvidenceRecoveryAuthoritySwitchRehearsal(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        shadow_promotion_id=snapshot.shadow_promotion_id,
        attestation_id=snapshot.attestation_id,
        replica_id=snapshot.replica_id,
        restore_rehearsal_id=snapshot.restore_rehearsal_id,
        restore_verification_id=snapshot.restore_verification_id,
        shadow_verification_id=snapshot.shadow_verification_id,
        attestation_request_snapshot_hash=snapshot.attestation_request_snapshot_hash,
        promotion_plan_hash=snapshot.promotion_plan_hash,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        shadow_promotion_hash=snapshot.shadow_promotion_hash,
        shadow_verification_hash=snapshot.shadow_verification_hash,
        source_file_hash=snapshot.source_file_hash,
        source_storage_key_fingerprint=snapshot.source_storage_key_fingerprint,
        shadow_storage_key_fingerprint=snapshot.shadow_storage_key_fingerprint,
        lineage_hash=snapshot.lineage_hash,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        contract_hash=contract_hash,
        status="prepared",
        virtual_authority_class="authoritative_source",
        virtual_authority_fingerprint=snapshot.source_authority_fingerprint,
        activation_lease_expires_at=lease_expires_at,
        prepared_by_id=prepared_by_id,
        prepared_at=current_time,
        preparation_reason=normalized_reason,
        cutover_performed=False,
        authoritative_storage_changed=False,
        document_storage_key_mutated=False,
        active_backend_changed=False,
    )
    db.add(rehearsal)
    db.flush()
    receipt = _new_receipt(
        rehearsal=rehearsal,
        phase="prepared",
        from_class="authoritative_source",
        to_class="authoritative_source",
        from_fingerprint=snapshot.source_authority_fingerprint,
        to_fingerprint=snapshot.source_authority_fingerprint,
        actor_id=prepared_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return rehearsal, receipt, "prepared"


def activate_recovery_authority_switch_rehearsal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryAuthoritySwitchRehearsal, EvidenceRecoveryAuthoritySwitchReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryAuthoritySwitchConflict("Authority-switch activation reason is required")
    current_time = _as_utc(now or _utc_now())
    rehearsal = _get_rehearsal(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        rehearsal_id=rehearsal_id,
        for_update=True,
    )
    if rehearsal.status == "activated":
        return rehearsal, None, "unchanged"
    if rehearsal.status != "prepared":
        raise RecoveryAuthoritySwitchConflict("Only a prepared authority-switch rehearsal can be activated")
    if rehearsal.prepared_by_id == activated_by_id:
        raise RecoveryAuthoritySwitchConflict("Authority-switch activation requires a different Admin")
    if current_time >= _as_utc(rehearsal.activation_lease_expires_at):
        receipt = _terminalize(
            db,
            rehearsal=rehearsal,
            status="expired",
            actor_id=activated_by_id,
            reason="Authority-switch activation lease expired before activation",
            now=current_time,
        )
        return rehearsal, receipt, "expired"
    try:
        snapshot = _load_switch_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            shadow_promotion_id=rehearsal.shadow_promotion_id,
            now=current_time,
        )
    except (RecoveryAuthoritySwitchConflict, RecoveryAuthoritySwitchNotFound) as exc:
        receipt = _terminalize(
            db,
            rehearsal=rehearsal,
            status="invalidated",
            actor_id=activated_by_id,
            reason=f"Fresh authority-switch preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return rehearsal, receipt, "invalidated"
    if not _matches_snapshot(rehearsal, snapshot):
        receipt = _terminalize(
            db,
            rehearsal=rehearsal,
            status="invalidated",
            actor_id=activated_by_id,
            reason="Authority-switch lineage drifted before virtual activation",
            now=current_time,
        )
        return rehearsal, receipt, "invalidated"

    rehearsal.status = "activated"
    rehearsal.activated_by_id = activated_by_id
    rehearsal.activated_at = current_time
    rehearsal.activation_reason = normalized_reason
    rehearsal.virtual_authority_class = "recovery_shadow_candidate"
    rehearsal.virtual_authority_fingerprint = rehearsal.candidate_authority_fingerprint
    receipt = _new_receipt(
        rehearsal=rehearsal,
        phase="activated",
        from_class="authoritative_source",
        to_class="recovery_shadow_candidate",
        from_fingerprint=rehearsal.source_authority_fingerprint,
        to_fingerprint=rehearsal.candidate_authority_fingerprint,
        actor_id=activated_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return rehearsal, receipt, "activated"


def rollback_recovery_authority_switch_rehearsal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryAuthoritySwitchRehearsal, EvidenceRecoveryAuthoritySwitchReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryAuthoritySwitchConflict("Authority-switch rollback reason is required")
    current_time = _as_utc(now or _utc_now())
    rehearsal = _get_rehearsal(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        rehearsal_id=rehearsal_id,
        for_update=True,
    )
    if rehearsal.status == "rolled_back":
        return rehearsal, None, "unchanged"
    if rehearsal.status != "activated":
        raise RecoveryAuthoritySwitchConflict("Only an activated authority-switch rehearsal can be rolled back")
    try:
        snapshot = _load_switch_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            shadow_promotion_id=rehearsal.shadow_promotion_id,
            now=current_time,
            allow_attestation_expired=True,
        )
    except (RecoveryAuthoritySwitchConflict, RecoveryAuthoritySwitchNotFound) as exc:
        receipt = _terminalize(
            db,
            rehearsal=rehearsal,
            status="invalidated",
            actor_id=rolled_back_by_id,
            reason=f"Fresh rollback reconciliation failed: {type(exc).__name__}",
            now=current_time,
        )
        return rehearsal, receipt, "invalidated"
    if not _matches_snapshot(rehearsal, snapshot):
        receipt = _terminalize(
            db,
            rehearsal=rehearsal,
            status="invalidated",
            actor_id=rolled_back_by_id,
            reason="Authority-switch lineage drifted before virtual rollback",
            now=current_time,
        )
        return rehearsal, receipt, "invalidated"

    rehearsal.status = "rolled_back"
    rehearsal.rolled_back_by_id = rolled_back_by_id
    rehearsal.rolled_back_at = current_time
    rehearsal.rollback_reason = normalized_reason
    rehearsal.virtual_authority_class = "authoritative_source"
    rehearsal.virtual_authority_fingerprint = rehearsal.source_authority_fingerprint
    receipt = _new_receipt(
        rehearsal=rehearsal,
        phase="rolled_back",
        from_class="recovery_shadow_candidate",
        to_class="authoritative_source",
        from_fingerprint=rehearsal.candidate_authority_fingerprint,
        to_fingerprint=rehearsal.source_authority_fingerprint,
        actor_id=rolled_back_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return rehearsal, receipt, "rolled_back"


def get_recovery_authority_switch_rehearsal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
) -> EvidenceRecoveryAuthoritySwitchRehearsal:
    return _get_rehearsal(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        rehearsal_id=rehearsal_id,
    )


def list_recovery_authority_switch_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
) -> list[EvidenceRecoveryAuthoritySwitchReceipt]:
    _get_rehearsal(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        rehearsal_id=rehearsal_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryAuthoritySwitchReceipt)
            .where(
                EvidenceRecoveryAuthoritySwitchReceipt.organization_id == organization_id,
                EvidenceRecoveryAuthoritySwitchReceipt.claim_id == claim_id,
                EvidenceRecoveryAuthoritySwitchReceipt.document_id == document_id,
                EvidenceRecoveryAuthoritySwitchReceipt.authority_switch_rehearsal_id == rehearsal_id,
            )
            .order_by(
                EvidenceRecoveryAuthoritySwitchReceipt.transitioned_at.asc(),
                EvidenceRecoveryAuthoritySwitchReceipt.created_at.asc(),
                EvidenceRecoveryAuthoritySwitchReceipt.id.asc(),
            )
        ).all()
    )
