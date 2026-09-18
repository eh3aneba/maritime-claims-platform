from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.settlements.models import (
    PaymentAuthorization,
    PaymentStatus,
    SettlementProposal,
    SettlementStatus,
)

_CAPACITY_ACTIVE_PAYMENT_STATUSES = {
    PaymentStatus.DRAFT,
    PaymentStatus.UNDER_REVIEW,
    PaymentStatus.FIRST_APPROVED,
    PaymentStatus.AUTHORIZED,
    PaymentStatus.PAID_EXTERNALLY,
}


def lock_and_validate_payment_capacity(db: Session, item: PaymentAuthorization) -> SettlementProposal:
    """Serialize and validate any transition that carries settlement capacity.

    The accepted settlement row is the serialization point. The current payment
    is excluded from the aggregate and then added exactly once, so this works for
    both an already-active row progressing through approval and a rejected row
    re-entering the active ledger.
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
            PaymentAuthorization.status.in_(_CAPACITY_ACTIVE_PAYMENT_STATUSES),
        )
    )
    if Decimal(allocated_other) + item.amount > settlement.amount:
        raise HTTPException(
            422,
            "Cumulative payment authorizations cannot exceed the accepted settlement amount",
        )
    return settlement
