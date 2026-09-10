from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_read_renewal_models import (
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadRenewalAuthorizationReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_service import (
    RecoveryDurableReadRenewalAuthorizationConflict,
    RecoveryDurableReadRenewalAuthorizationNotFound,
    RecoveryDurableReadRenewalAuthorizationUnavailable,
    _as_utc,
    _get_authorization,
    _load_snapshot,
    _matches_snapshot,
    _new_receipt,
    _terminalize,
    _utc_now,
)


def approve_durable_read_renewal_authorization(
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
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadRenewalAuthorizationReceipt | None,
    str,
]:
    """Approve Phase O while keeping transient object-storage outages retryable."""

    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Durable read renewal authorization approval reason is required"
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
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Approved renewal authorization replay does not match the original approval"
        )
    if authorization.status != "pending_second_approval":
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Only a pending durable read renewal authorization can be approved"
        )
    if current_time >= _as_utc(authorization.authorization_expires_at):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="expired",
            actor_id=approved_by_id,
            reason="Durable read renewal authorization approval window expired",
            now=current_time,
        )
        return authorization, receipt, "expired"
    if authorization.requested_by_id == approved_by_id:
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Durable read renewal authorization requires a different Admin from the requester"
        )
    if approved_by_id in {
        authorization.health_qualified_by_id,
        authorization.durable_activated_by_id,
    }:
        raise RecoveryDurableReadRenewalAuthorizationConflict(
            "Approver must differ from the Phase N qualifier and prior Phase M durable-route activator"
        )

    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=authorization.health_qualification_id,
        )
    except RecoveryDurableReadRenewalAuthorizationUnavailable:
        raise
    except (
        RecoveryDurableReadRenewalAuthorizationNotFound,
        RecoveryDurableReadRenewalAuthorizationConflict,
    ) as exc:
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason=f"Fresh durable read renewal preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return authorization, receipt, "invalidated"

    if not _matches_snapshot(authorization, snapshot):
        receipt = _terminalize(
            db,
            authorization=authorization,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Durable read renewal authorization snapshot drifted before approval",
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
