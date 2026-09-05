from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.adjustments.schemas import (
    AdjustmentCreate,
    AdjustmentLineUpdate,
    AdjustmentListResponse,
    AdjustmentRebase,
    AdjustmentReview,
    AdjustmentStatementResponse,
    AdjustmentStatementUpdate,
)
from app.modules.adjustments.service import (
    create_statement,
    get_statement,
    list_statements,
    rebase_statement,
    review_statement,
    statement_response,
    submit_statement,
    update_line,
    update_statement,
)
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claims/{claim_id}/adjustments", tags=["adjustments"])
AdjustmentEditor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER, UserRole.CLAIMS_HANDLER)),
]


def _claim(db: Session, claim_id: UUID, organization_id: UUID):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.get("", response_model=AdjustmentListResponse)
def adjustment_list(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentListResponse:
    claim = _claim(db, claim_id, current_user.organization_id)
    items = [statement_response(db, item) for item in list_statements(db, claim=claim)]
    return AdjustmentListResponse(items=items, total=len(items))


@router.post("", response_model=AdjustmentStatementResponse, status_code=status.HTTP_201_CREATED)
def adjustment_create(
    claim_id: UUID,
    payload: AdjustmentCreate,
    editor: AdjustmentEditor,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentStatementResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    item = create_statement(db, claim=claim, user=editor, payload=payload)
    return AdjustmentStatementResponse(**statement_response(db, item))


@router.patch("/{statement_id}", response_model=AdjustmentStatementResponse)
def adjustment_update(
    claim_id: UUID,
    statement_id: UUID,
    payload: AdjustmentStatementUpdate,
    editor: AdjustmentEditor,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentStatementResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    item = get_statement(db, claim=claim, statement_id=statement_id)
    updated = update_statement(db, statement=item, user=editor, payload=payload)
    return AdjustmentStatementResponse(**statement_response(db, updated))


@router.patch("/{statement_id}/lines/{line_id}", response_model=AdjustmentStatementResponse)
def adjustment_line_update(
    claim_id: UUID,
    statement_id: UUID,
    line_id: UUID,
    payload: AdjustmentLineUpdate,
    editor: AdjustmentEditor,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentStatementResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    item = get_statement(db, claim=claim, statement_id=statement_id)
    updated = update_line(db, statement=item, line_id=line_id, user=editor, payload=payload)
    return AdjustmentStatementResponse(**statement_response(db, updated))


@router.post("/{statement_id}/rebase", response_model=AdjustmentStatementResponse, status_code=status.HTTP_201_CREATED)
def adjustment_rebase(
    claim_id: UUID,
    statement_id: UUID,
    payload: AdjustmentRebase,
    editor: AdjustmentEditor,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentStatementResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    item = get_statement(db, claim=claim, statement_id=statement_id)
    rebased = rebase_statement(db, claim=claim, statement=item, user=editor, payload=payload)
    return AdjustmentStatementResponse(**statement_response(db, rebased))


@router.post("/{statement_id}/submit", response_model=AdjustmentStatementResponse)
def adjustment_submit(
    claim_id: UUID,
    statement_id: UUID,
    editor: AdjustmentEditor,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentStatementResponse:
    claim = _claim(db, claim_id, editor.organization_id)
    item = get_statement(db, claim=claim, statement_id=statement_id)
    updated = submit_statement(db, statement=item, user=editor)
    return AdjustmentStatementResponse(**statement_response(db, updated))


@router.post("/{statement_id}/approve", response_model=AdjustmentStatementResponse)
def adjustment_approve(
    claim_id: UUID,
    statement_id: UUID,
    payload: AdjustmentReview,
    manager: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentStatementResponse:
    claim = _claim(db, claim_id, manager.organization_id)
    item = get_statement(db, claim=claim, statement_id=statement_id)
    updated = review_statement(db, statement=item, user=manager, approve=True, note=payload.note)
    return AdjustmentStatementResponse(**statement_response(db, updated))


@router.post("/{statement_id}/reject", response_model=AdjustmentStatementResponse)
def adjustment_reject(
    claim_id: UUID,
    statement_id: UUID,
    payload: AdjustmentReview,
    manager: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentStatementResponse:
    claim = _claim(db, claim_id, manager.organization_id)
    item = get_statement(db, claim=claim, statement_id=statement_id)
    updated = review_statement(db, statement=item, user=manager, approve=False, note=payload.note)
    return AdjustmentStatementResponse(**statement_response(db, updated))
