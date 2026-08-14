from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.correspondence.schemas import (
    CorrespondenceCreate,
    CorrespondenceListResponse,
    CorrespondenceMarkSent,
    CorrespondenceResponse,
    CorrespondenceReview,
    CorrespondenceUpdate,
)
from app.modules.correspondence.service import (
    create_correspondence,
    get_correspondence,
    list_correspondence,
    mark_correspondence_sent,
    review_correspondence,
    submit_correspondence,
    update_correspondence,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claims/{claim_id}/correspondence", tags=["correspondence"])


def _claim(db: Session, claim_id: UUID, organization_id: UUID):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.get("", response_model=CorrespondenceListResponse)
def correspondence_list(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> CorrespondenceListResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    items = list_correspondence(db, claim=claim)
    return CorrespondenceListResponse(items=items, total=len(items))


@router.post("", response_model=CorrespondenceResponse, status_code=status.HTTP_201_CREATED)
def correspondence_create(claim_id: UUID, payload: CorrespondenceCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> CorrespondenceResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    return create_correspondence(db, claim=claim, user=current_user, payload=payload)


@router.patch("/{correspondence_id}", response_model=CorrespondenceResponse)
def correspondence_update(claim_id: UUID, correspondence_id: UUID, payload: CorrespondenceUpdate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> CorrespondenceResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    item = get_correspondence(db, claim=claim, correspondence_id=correspondence_id)
    return update_correspondence(db, item=item, user=current_user, payload=payload)


@router.post("/{correspondence_id}/submit", response_model=CorrespondenceResponse)
def correspondence_submit(claim_id: UUID, correspondence_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> CorrespondenceResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    item = get_correspondence(db, claim=claim, correspondence_id=correspondence_id)
    return submit_correspondence(db, item=item, user=current_user)


@router.post("/{correspondence_id}/approve", response_model=CorrespondenceResponse)
def correspondence_approve(
    claim_id: UUID,
    correspondence_id: UUID,
    payload: CorrespondenceReview,
    manager: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
) -> CorrespondenceResponse:
    claim = _claim(db, claim_id, manager.organization_id)
    item = get_correspondence(db, claim=claim, correspondence_id=correspondence_id)
    return review_correspondence(db, item=item, user=manager, approve=True, note=payload.note)


@router.post("/{correspondence_id}/reject", response_model=CorrespondenceResponse)
def correspondence_reject(
    claim_id: UUID,
    correspondence_id: UUID,
    payload: CorrespondenceReview,
    manager: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
) -> CorrespondenceResponse:
    claim = _claim(db, claim_id, manager.organization_id)
    item = get_correspondence(db, claim=claim, correspondence_id=correspondence_id)
    return review_correspondence(db, item=item, user=manager, approve=False, note=payload.note)


@router.post("/{correspondence_id}/mark-sent", response_model=CorrespondenceResponse)
def correspondence_mark_sent(claim_id: UUID, correspondence_id: UUID, payload: CorrespondenceMarkSent, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> CorrespondenceResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    item = get_correspondence(db, claim=claim, correspondence_id=correspondence_id)
    return mark_correspondence_sent(db, claim=claim, item=item, user=current_user, payload=payload)
