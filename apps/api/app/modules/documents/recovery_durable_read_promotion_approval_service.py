from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_read_promotion_models import (
    EvidenceRecoveryDurableReadPromotionAuthorization,
    EvidenceRecoveryDurableReadPromotionAuthorizationReceipt,
)
from app.modules.documents.recovery_durable_read_promotion_service import (
    RecoveryDurableReadPromotionAuthorizationConflict,
    RecoveryDurableReadPromotionAuthorizationNotFound,
    RecoveryDurableReadPromotionAuthorizationUnavailable,
    _as_utc,
    _get_authorization,
    _load_snapshot,
    _matches_snapshot,
    _new_receipt,
    _terminalize,
    _utc_now,
)


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
    """Approve Phase L while preserving retryability for transient storage outages.

    Integrity/lineage drift terminalizes the pending record. A temporary storage
    availability failure propagates as 503 through the router and leaves the
    record pending, so no authority is created and a later retry inside the
    bounded approval window can re-run the complete fresh preflight.
    """

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
    except RecoveryDurableReadPromotionAuthorizationUnavailable:
        raise
    except (
        RecoveryDurableReadPromotionAuthorizationNotFound,
        RecoveryDurableReadPromotionAuthorizationConflict,
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
