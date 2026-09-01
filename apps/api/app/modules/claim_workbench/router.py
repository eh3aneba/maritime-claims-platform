from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.claim_workbench.schemas import (
    PriorityTier,
    WorkbenchClaimRow,
    WorkbenchDashboard,
    WorkbenchFilters,
    WorkbenchPage,
)
from app.modules.claim_workbench.service import dashboard, get_claim_row, query_workbench
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claim-workbench", tags=["claim-workbench"])
Operator = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER, UserRole.CLAIMS_HANDLER)),
]


def _filters(
    priority: PriorityTier | None = None,
    claim_status: str | None = Query(default=None, max_length=80),
    claim_type: str | None = Query(default=None, max_length=80),
    attention_category: str | None = Query(default=None, max_length=100),
    source_type: str | None = Query(default=None, max_length=100),
    handler_id: UUID | None = None,
    requires_action: bool | None = None,
    overdue_or_due_soon: bool | None = None,
) -> WorkbenchFilters:
    return WorkbenchFilters(
        priority=priority,
        claim_status=claim_status,
        claim_type=claim_type,
        attention_category=attention_category,
        source_type=source_type,
        handler_id=handler_id,
        requires_action=requires_action,
        overdue_or_due_soon=overdue_or_due_soon,
    )


@router.get("", response_model=WorkbenchDashboard)
def workbench_dashboard(operator: Operator, db: Annotated[Session, Depends(get_db)]):
    return dashboard(db, operator)


@router.get("/queue", response_model=WorkbenchPage)
def workbench_queue(
    operator: Operator,
    db: Annotated[Session, Depends(get_db)],
    filters: Annotated[WorkbenchFilters, Depends(_filters)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    return query_workbench(db, operator, filters, page=page, page_size=page_size)


@router.get("/claims/{claim_id}", response_model=WorkbenchClaimRow)
def workbench_claim(
    claim_id: UUID,
    operator: Operator,
    db: Annotated[Session, Depends(get_db)],
):
    return get_claim_row(db, operator, claim_id)
