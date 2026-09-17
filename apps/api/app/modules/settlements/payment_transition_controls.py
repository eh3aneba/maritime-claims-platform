from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.settlements.models import PaymentAuthorization, SettlementProposal, SettlementStatus
from app.modules.settlements.service import ACTIVE_PAYMENT_STATUSES


def lock_and_validate_payment_capacity(db: Session, item: PaymentAuthorization) -> SettlementProposal:
    """Serialize active-payment transitions against one accepted settlement cap.

    The settlement row is locked for the duration of the caller's transaction so
    create/resubmit/approval paths cannot race past the accepted amount. The
    current payment is excluded from the aggregate and then added exactly once,
    which works whether it is already active or is re-entering from rejected.
    """
    settlement = db.scalar(
        select(SettlementProposal)
        .where(
            SettlementProposal.id == item.settlement_id,
            SettlementProposal.organization_id == item.organization_id,
            SettlementProposal.claim_id == item.claim_id,
        )
        .with_for_update()
    )
    if settlement is None:
        raise HTTPException(409, "Payment authorization settlement lineage is missing")
    if settlement.status != SettlementStatus.ACCEPTED:
        raise HTTPException(409, "Payment authorization requires an accepted settlement")

    allocated_other = db.scalar(
        select(func.coalesce(func.sum(PaymentAuthorization.amount), 0)).where(
            PaymentAuthorization.settlement_id == settlement.id,
            PaymentAuthorization.id != item.id,
            PaymentAuthorization.status.in_(ACTIVE_PAYMENT_STATUSES),
        )
    )
    if Decimal(allocated_other) + item.amount > settlement.amount:
        raise HTTPException(
            422,
            "Cumulative payment authorizations cannot exceed the accepted settlement amount",
        )
    return settlement
