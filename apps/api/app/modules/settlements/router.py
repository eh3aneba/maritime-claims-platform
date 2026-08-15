from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.settlements.schemas import (
    DispositionRecord, PaidRecord, PaymentCreate, PaymentResponse, ReviewNote,
    SettlementCreate, SettlementLedgerResponse, SettlementResponse, SettlementUpdate,
)
from app.modules.settlements.service import (
    approve_payment, create_payment, create_settlement, get_payment, get_settlement, list_ledger,
    record_disposition, record_paid, reject_payment, review_settlement, submit_payment,
    submit_settlement, update_settlement,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claims/{claim_id}/settlement-ledger", tags=["settlement-ledger"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]


def _claim(db: Session, claim_id: UUID, organization_id: UUID):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=organization_id)
    if claim is None:
        raise HTTPException(404, "Claim not found")
    return claim


@router.get("", response_model=SettlementLedgerResponse)
def ledger(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    settlements, payments = list_ledger(db, _claim(db, claim_id, current_user.organization_id))
    return SettlementLedgerResponse(settlements=settlements, payments=payments)


@router.post("/settlements", response_model=SettlementResponse, status_code=status.HTTP_201_CREATED)
def settlement_create(claim_id: UUID, payload: SettlementCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return create_settlement(db, _claim(db, claim_id, current_user.organization_id), current_user, payload)


@router.patch("/settlements/{item_id}", response_model=SettlementResponse)
def settlement_update(claim_id: UUID, item_id: UUID, payload: SettlementUpdate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    claim = _claim(db, claim_id, current_user.organization_id)
    return update_settlement(db, get_settlement(db, claim, item_id), current_user, payload)


@router.post("/settlements/{item_id}/submit", response_model=SettlementResponse)
def settlement_submit(claim_id: UUID, item_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    claim = _claim(db, claim_id, current_user.organization_id)
    return submit_settlement(db, get_settlement(db, claim, item_id), current_user)


@router.post("/settlements/{item_id}/{action}", response_model=SettlementResponse)
def settlement_review(claim_id: UUID, item_id: UUID, action: str, payload: ReviewNote, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    if action not in {"approve", "reject"}:
        raise HTTPException(404, "Review action not found")
    claim = _claim(db, claim_id, manager.organization_id)
    return review_settlement(db, get_settlement(db, claim, item_id), manager, action == "approve", payload.note)


@router.post("/settlements/{item_id}/disposition/record", response_model=SettlementResponse)
def settlement_disposition(claim_id: UUID, item_id: UUID, payload: DispositionRecord, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    claim = _claim(db, claim_id, manager.organization_id)
    return record_disposition(db, get_settlement(db, claim, item_id), manager, payload.disposition, payload.note)


@router.post("/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def payment_create(claim_id: UUID, payload: PaymentCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return create_payment(db, _claim(db, claim_id, current_user.organization_id), current_user, payload)


@router.post("/payments/{item_id}/submit", response_model=PaymentResponse)
def payment_submit(claim_id: UUID, item_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    claim = _claim(db, claim_id, current_user.organization_id)
    return submit_payment(db, get_payment(db, claim, item_id), current_user)


@router.post("/payments/{item_id}/approve", response_model=PaymentResponse)
def payment_approve(claim_id: UUID, item_id: UUID, payload: ReviewNote, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    claim = _claim(db, claim_id, manager.organization_id)
    return approve_payment(db, get_payment(db, claim, item_id), manager, payload.note)


@router.post("/payments/{item_id}/reject", response_model=PaymentResponse)
def payment_reject(claim_id: UUID, item_id: UUID, payload: ReviewNote, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    claim = _claim(db, claim_id, manager.organization_id)
    return reject_payment(db, get_payment(db, claim, item_id), manager, payload.note)


@router.post("/payments/{item_id}/record-paid", response_model=PaymentResponse)
def payment_paid(claim_id: UUID, item_id: UUID, payload: PaidRecord, manager: Manager, db: Annotated[Session, Depends(get_db)]):
    if not payload.confirm_paid_externally:
        raise HTTPException(422, "Explicit confirmation of external payment is required")
    claim = _claim(db, claim_id, manager.organization_id)
    return record_paid(db, get_payment(db, claim, item_id), manager, channel=payload.channel,
                       external_reference=payload.external_reference, value_date=payload.value_date, note=payload.note)
