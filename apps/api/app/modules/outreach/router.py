from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.outreach.models import DesignPartnerAccount, DesignPartnerContact, OutreachTouch, PaidPilotOffer
from app.modules.outreach.schemas import *
from app.modules.outreach.service import build_cohort_summary, create_account, next_offer_version, update_account

router = APIRouter(prefix="/outreach", tags=["outreach"])


def account_or_404(db, account_id, organization_id):
    row = db.scalar(select(DesignPartnerAccount).where(DesignPartnerAccount.id == account_id, DesignPartnerAccount.organization_id == organization_id))
    if not row: raise HTTPException(status_code=404, detail="Design partner account not found")
    return row


@router.get("/cohort", response_model=CohortSummary)
def cohort(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return build_cohort_summary(db, organization_id=current_user.organization_id)


@router.post("/accounts", response_model=DesignPartnerAccountRead, status_code=201)
def account_create(payload: DesignPartnerAccountCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    try:
        row = create_account(db, organization_id=current_user.organization_id, payload=payload); db.commit(); db.refresh(row); return row
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail="Account already exists") from exc


@router.patch("/accounts/{account_id}", response_model=DesignPartnerAccountRead)
def account_update(account_id: UUID, payload: DesignPartnerAccountUpdate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    row = account_or_404(db, account_id, current_user.organization_id); update_account(db, row=row, payload=payload); db.commit(); db.refresh(row); return row


@router.post("/accounts/{account_id}/contacts", response_model=DesignPartnerContactRead, status_code=201)
def contact_create(account_id: UUID, payload: DesignPartnerContactCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    account_or_404(db, account_id, current_user.organization_id)
    row=DesignPartnerContact(organization_id=current_user.organization_id, account_id=account_id, **payload.model_dump()); db.add(row); db.commit(); db.refresh(row); return row


@router.post("/accounts/{account_id}/touches", response_model=OutreachTouchRead, status_code=201)
def touch_create(account_id: UUID, payload: OutreachTouchCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    account_or_404(db, account_id, current_user.organization_id)
    if payload.contact_id:
        contact = db.scalar(select(DesignPartnerContact).where(DesignPartnerContact.id==payload.contact_id, DesignPartnerContact.account_id==account_id, DesignPartnerContact.organization_id==current_user.organization_id))
        if not contact: raise HTTPException(status_code=404, detail="Contact not found")
    row=OutreachTouch(organization_id=current_user.organization_id, account_id=account_id, created_by_id=current_user.id, **payload.model_dump()); db.add(row); db.commit(); db.refresh(row); return row


@router.post("/accounts/{account_id}/pilot-offers", response_model=PaidPilotOfferRead, status_code=201)
def offer_create(account_id: UUID, payload: PaidPilotOfferCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    account_or_404(db, account_id, current_user.organization_id)
    row=PaidPilotOffer(organization_id=current_user.organization_id, account_id=account_id, created_by_id=current_user.id, version=next_offer_version(db, organization_id=current_user.organization_id, account_id=account_id), **payload.model_dump()); db.add(row); db.commit(); db.refresh(row); return row
