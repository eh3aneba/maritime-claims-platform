from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.adjustments.models import AdjustmentStatement, AdjustmentStatus
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.settlements.models import PaymentAuthorization, PaymentStatus, SettlementProposal, SettlementStatus
from app.modules.settlements.schemas import PaymentCreate, SettlementCreate, SettlementUpdate
from app.modules.users.models import User


ACTIVE_PAYMENT_STATUSES = {
    PaymentStatus.DRAFT, PaymentStatus.UNDER_REVIEW, PaymentStatus.FIRST_APPROVED,
    PaymentStatus.AUTHORIZED, PaymentStatus.PAID_EXTERNALLY,
}


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _audit(db: Session, *, obj, user: User, action: str, values: dict, details: str | None = None) -> None:
    write_audit_log(db, organization_id=obj.organization_id, user_id=user.id, action=action,
                    entity_type=obj.__tablename__, entity_id=obj.id, new_values=values, details=details)


def list_ledger(db: Session, claim: Claim) -> tuple[list[SettlementProposal], list[PaymentAuthorization]]:
    settlements = list(db.scalars(select(SettlementProposal).where(
        SettlementProposal.organization_id == claim.organization_id,
        SettlementProposal.claim_id == claim.id,
    ).order_by(SettlementProposal.version.desc())))
    payments = list(db.scalars(select(PaymentAuthorization).where(
        PaymentAuthorization.organization_id == claim.organization_id,
        PaymentAuthorization.claim_id == claim.id,
    ).order_by(PaymentAuthorization.created_at.desc())))
    return settlements, payments


def get_settlement(db: Session, claim: Claim, settlement_id: UUID, *, lock: bool = False) -> SettlementProposal:
    query = select(SettlementProposal).where(
        SettlementProposal.id == settlement_id,
        SettlementProposal.organization_id == claim.organization_id,
        SettlementProposal.claim_id == claim.id,
    )
    item = db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise HTTPException(404, "Settlement proposal not found")
    return item


def get_payment(db: Session, claim: Claim, payment_id: UUID) -> PaymentAuthorization:
    item = db.scalar(select(PaymentAuthorization).where(
        PaymentAuthorization.id == payment_id,
        PaymentAuthorization.organization_id == claim.organization_id,
        PaymentAuthorization.claim_id == claim.id,
    ))
    if item is None:
        raise HTTPException(404, "Payment authorization not found")
    return item


def create_settlement(db: Session, claim: Claim, user: User, payload: SettlementCreate) -> SettlementProposal:
    adjustment = db.scalar(select(AdjustmentStatement).where(
        AdjustmentStatement.id == payload.adjustment_statement_id,
        AdjustmentStatement.organization_id == claim.organization_id,
        AdjustmentStatement.claim_id == claim.id,
    ))
    if adjustment is None or adjustment.status != AdjustmentStatus.APPROVED or not adjustment.content_hash:
        raise HTTPException(409, "Settlement must be sourced from an approved immutable adjustment statement")
    if payload.amount > adjustment.net_adjusted:
        raise HTTPException(422, "Settlement amount cannot exceed the approved adjusted total")
    version = (db.scalar(select(func.max(SettlementProposal.version)).where(SettlementProposal.claim_id == claim.id)) or 0) + 1
    item = SettlementProposal(
        organization_id=claim.organization_id, claim_id=claim.id, adjustment_statement_id=adjustment.id,
        created_by_id=user.id, version=version, title=payload.title.strip(), settlement_type=payload.settlement_type,
        status=SettlementStatus.DRAFT, currency=adjustment.currency, amount=payload.amount, terms=payload.terms.strip(),
        release_required=payload.release_required, without_prejudice=payload.without_prejudice, expires_on=payload.expires_on,
        source_adjustment_hash=adjustment.content_hash,
        source_snapshot={"adjustment_statement_id": str(adjustment.id), "version": adjustment.version,
                         "currency": adjustment.currency, "net_adjusted": str(adjustment.net_adjusted),
                         "content_hash": adjustment.content_hash},
    )
    db.add(item); db.flush()
    _audit(db, obj=item, user=user, action="CREATE_SETTLEMENT_PROPOSAL",
           values={"version": version, "amount": str(item.amount), "currency": item.currency})
    db.commit(); db.refresh(item)
    return item


def update_settlement(db: Session, item: SettlementProposal, user: User, payload: SettlementUpdate) -> SettlementProposal:
    if item.status not in {SettlementStatus.DRAFT, SettlementStatus.REJECTED}:
        raise HTTPException(409, "Only draft or rejected settlement proposals can be edited")
    adjustment = db.get(AdjustmentStatement, item.adjustment_statement_id)
    if payload.amount is not None and payload.amount > adjustment.net_adjusted:
        raise HTTPException(422, "Settlement amount cannot exceed the approved adjusted total")
    for field in ("title", "settlement_type", "amount", "terms", "release_required", "without_prejudice", "expires_on"):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, field, value.strip() if isinstance(value, str) else value)
    item.status = SettlementStatus.DRAFT
    item.reviewed_by_id = None; item.reviewed_at = None; item.review_note = None; item.content_hash = None
    _audit(db, obj=item, user=user, action="UPDATE_SETTLEMENT_PROPOSAL", values={"amount": str(item.amount)})
    db.commit(); db.refresh(item)
    return item


def submit_settlement(db: Session, item: SettlementProposal, user: User) -> SettlementProposal:
    if item.status not in {SettlementStatus.DRAFT, SettlementStatus.REJECTED}:
        raise HTTPException(409, "Only draft or rejected settlement proposals can be submitted")
    item.status = SettlementStatus.UNDER_REVIEW
    _audit(db, obj=item, user=user, action="SUBMIT_SETTLEMENT_FOR_REVIEW", values={"status": item.status.value})
    db.commit(); db.refresh(item)
    return item


def review_settlement(db: Session, item: SettlementProposal, user: User, approve: bool, note: str) -> SettlementProposal:
    if item.status != SettlementStatus.UNDER_REVIEW:
        raise HTTPException(409, "Only settlement proposals under review can be approved or rejected")
    if approve and item.created_by_id == user.id:
        raise HTTPException(409, "Settlement creator cannot approve their own proposal")
    item.status = SettlementStatus.APPROVED if approve else SettlementStatus.REJECTED
    item.reviewed_by_id = user.id; item.reviewed_at = datetime.now(UTC); item.review_note = note.strip()
    if approve:
        item.content_hash = _hash({"id": str(item.id), "version": item.version, "adjustment_hash": item.source_adjustment_hash,
                                   "title": item.title, "type": item.settlement_type.value, "currency": item.currency,
                                   "amount": str(item.amount), "terms": item.terms, "release_required": item.release_required,
                                   "without_prejudice": item.without_prejudice, "expires_on": str(item.expires_on) if item.expires_on else None})
    else:
        item.content_hash = None
    _audit(db, obj=item, user=user, action="APPROVE_SETTLEMENT_PROPOSAL" if approve else "REJECT_SETTLEMENT_PROPOSAL",
           values={"status": item.status.value, "content_hash": item.content_hash},
           details="Human-reviewed proposal only; no payment is initiated." if approve else None)
    db.commit(); db.refresh(item)
    return item


def record_disposition(db: Session, item: SettlementProposal, user: User, disposition: str, note: str) -> SettlementProposal:
    if item.status != SettlementStatus.APPROVED:
        raise HTTPException(409, "Only an approved proposal can receive a disposition")
    allowed = {"accepted": SettlementStatus.ACCEPTED, "declined": SettlementStatus.DECLINED, "withdrawn": SettlementStatus.WITHDRAWN}
    if disposition not in allowed:
        raise HTTPException(422, "Disposition must be accepted, declined or withdrawn")
    item.status = allowed[disposition]; item.disposition_by_id = user.id
    item.disposition_at = datetime.now(UTC); item.disposition_note = note.strip()
    _audit(db, obj=item, user=user, action=f"RECORD_SETTLEMENT_{disposition.upper()}",
           values={"status": item.status.value}, details="External outcome recorded manually; the platform did not communicate or accept it.")
    db.commit(); db.refresh(item)
    return item


def create_payment(db: Session, claim: Claim, user: User, payload: PaymentCreate) -> PaymentAuthorization:
    settlement = get_settlement(db, claim, payload.settlement_id, lock=True)
    if settlement.status != SettlementStatus.ACCEPTED:
        raise HTTPException(409, "Payment authorization requires an accepted settlement")
    allocated = db.scalar(select(func.coalesce(func.sum(PaymentAuthorization.amount), 0)).where(
        PaymentAuthorization.settlement_id == settlement.id,
        PaymentAuthorization.status.in_(ACTIVE_PAYMENT_STATUSES),
    ))
    if Decimal(allocated) + payload.amount > settlement.amount:
        raise HTTPException(422, "Cumulative payment authorizations cannot exceed the accepted settlement amount")
    sequence = (db.scalar(select(func.max(PaymentAuthorization.sequence)).where(PaymentAuthorization.settlement_id == settlement.id)) or 0) + 1
    item = PaymentAuthorization(
        organization_id=claim.organization_id, claim_id=claim.id, settlement_id=settlement.id,
        created_by_id=user.id, sequence=sequence, status=PaymentStatus.DRAFT,
        payee=payload.payee.strip(), currency=settlement.currency, amount=payload.amount, purpose=payload.purpose.strip(),
    )
    db.add(item); db.flush()
    _audit(db, obj=item, user=user, action="CREATE_PAYMENT_AUTHORIZATION",
           values={"sequence": sequence, "amount": str(item.amount), "currency": item.currency})
    db.commit(); db.refresh(item)
    return item


def submit_payment(db: Session, item: PaymentAuthorization, user: User) -> PaymentAuthorization:
    if item.status not in {PaymentStatus.DRAFT, PaymentStatus.REJECTED}:
        raise HTTPException(409, "Only draft or rejected payment authorizations can be submitted")
    item.status = PaymentStatus.UNDER_REVIEW
    item.rejection_note = None
    _audit(db, obj=item, user=user, action="SUBMIT_PAYMENT_AUTHORIZATION", values={"status": item.status.value})
    db.commit(); db.refresh(item)
    return item


def approve_payment(db: Session, item: PaymentAuthorization, user: User, note: str) -> PaymentAuthorization:
    if item.created_by_id == user.id:
        raise HTTPException(409, "Payment creator cannot approve their own authorization")
    now = datetime.now(UTC)
    if item.status == PaymentStatus.UNDER_REVIEW:
        item.status = PaymentStatus.FIRST_APPROVED; item.first_approved_by_id = user.id
        item.first_approved_at = now; item.first_approval_note = note.strip()
        action = "FIRST_APPROVE_PAYMENT_AUTHORIZATION"
    elif item.status == PaymentStatus.FIRST_APPROVED:
        if item.first_approved_by_id == user.id:
            raise HTTPException(409, "Second approval must be made by a different Manager/Admin")
        item.status = PaymentStatus.AUTHORIZED; item.second_approved_by_id = user.id
        item.second_approved_at = now; item.second_approval_note = note.strip()
        item.content_hash = _hash({"id": str(item.id), "settlement_id": str(item.settlement_id),
                                   "sequence": item.sequence, "payee": item.payee, "currency": item.currency,
                                   "amount": str(item.amount), "purpose": item.purpose,
                                   "first_approved_by_id": str(item.first_approved_by_id),
                                   "second_approved_by_id": str(item.second_approved_by_id)})
        action = "SECOND_APPROVE_PAYMENT_AUTHORIZATION"
    else:
        raise HTTPException(409, "Payment authorization is not awaiting approval")
    _audit(db, obj=item, user=user, action=action, values={"status": item.status.value, "content_hash": item.content_hash},
           details="Authorization ledger only; no bank instruction or money movement occurred.")
    db.commit(); db.refresh(item)
    return item


def reject_payment(db: Session, item: PaymentAuthorization, user: User, note: str) -> PaymentAuthorization:
    if item.status not in {PaymentStatus.UNDER_REVIEW, PaymentStatus.FIRST_APPROVED}:
        raise HTTPException(409, "Payment authorization is not awaiting review")
    item.status = PaymentStatus.REJECTED; item.rejection_note = note.strip()
    item.first_approved_by_id = None; item.first_approved_at = None; item.first_approval_note = None
    _audit(db, obj=item, user=user, action="REJECT_PAYMENT_AUTHORIZATION", values={"status": item.status.value})
    db.commit(); db.refresh(item)
    return item


def record_paid(db: Session, item: PaymentAuthorization, user: User, *, channel: str, external_reference: str,
                value_date, note: str | None) -> PaymentAuthorization:
    if item.status != PaymentStatus.AUTHORIZED:
        raise HTTPException(409, "Only a fully authorized payment can be recorded as paid externally")
    item.status = PaymentStatus.PAID_EXTERNALLY; item.paid_channel = channel.strip()
    item.external_reference = external_reference.strip(); item.value_date = value_date
    item.paid_note = (note or "").strip() or None; item.paid_recorded_by_id = user.id; item.paid_recorded_at = datetime.now(UTC)
    _audit(db, obj=item, user=user, action="RECORD_PAYMENT_PAID_EXTERNALLY",
           values={"status": item.status.value, "channel": item.paid_channel, "external_reference": item.external_reference,
                   "value_date": str(item.value_date)},
           details="Payment execution occurred outside the platform and was explicitly recorded.")
    db.commit(); db.refresh(item)
    return item
