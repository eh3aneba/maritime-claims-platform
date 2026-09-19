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


def lock_payment_transition(
    db: Session,
    item: PaymentAuthorization,
) -> tuple[SettlementProposal, PaymentAuthorization]:
    """Serialize one payment transition on settlement then payment rows.

    Callers may have loaded the payment before waiting on the settlement lock.
    Re-read the payment with populate_existing while holding both row locks so a
    waiter cannot continue from stale workflow state after another transaction
    commits a competing transition.
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

    locked_item = db.scalar(
        select(PaymentAuthorization)
        .where(
            PaymentAuthorization.id == item.id,
            PaymentAuthorization.settlement_id == settlement.id,
            PaymentAuthorization.organization_id == item.organization_id,
            PaymentAuthorization.claim_id == item.claim_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked_item is None:
        raise HTTPException(409, "Payment authorization disappeared during transition")
    return settlement, locked_item


def lock_and_validate_payment_capacity(
    db: Session,
    item: PaymentAuthorization,
) -> tuple[SettlementProposal, PaymentAuthorization]:
    """Serialize and validate any transition that carries settlement capacity.

    The accepted settlement row is the global serialization point. The payment
    row is then locked and refreshed so state-machine checks use current durable
    state even when the caller loaded the row before waiting for the settlement
    lock. The current payment is excluded from the aggregate and added exactly
    once.
    """
    settlement, locked_item = lock_payment_transition(db, item)

    allocated_other = db.scalar(
        select(func.coalesce(func.sum(PaymentAuthorization.amount), 0)).where(
            PaymentAuthorization.settlement_id == settlement.id,
            PaymentAuthorization.id != locked_item.id,
            PaymentAuthorization.status.in_(_CAPACITY_ACTIVE_PAYMENT_STATUSES),
        )
    )
    if Decimal(allocated_other) + locked_item.amount > settlement.amount:
        raise HTTPException(
            422,
            "Cumulative payment authorizations cannot exceed the accepted settlement amount",
        )
    return settlement, locked_item
