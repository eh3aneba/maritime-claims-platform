from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.ai_operations.schemas import (
    AIOperationsDashboard,
    AIOperationsEvent,
    AIOperationsExportRequest,
    AIOperationsFilters,
    AIOperationsIncidentCreate,
    AIOperationsPage,
)
from app.modules.ai_operations.service import (
    dashboard,
    export_events,
    get_event,
    handoff_incident,
    pending_review_queue,
    query_events,
    review_document_event,
)
from app.modules.ai_production_wide.schemas import AIProductionDecisionLogReview
from app.modules.auth.dependencies import require_roles
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/ai-operations", tags=["ai-operations"])
Manager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))]


def _filters(
    workflow_type: Literal["document_processing", "claim_qa_synthesis"] | None = None,
    claim_id: UUID | None = None,
    document_id: UUID | None = None,
    document_type: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=80),
    human_review_state: Literal["pending", "completed", "not_applicable"] | None = None,
    human_review_action: Literal["approve", "edit", "reject"] | None = None,
    provider: str | None = Query(default=None, max_length=80),
    model: str | None = Query(default=None, max_length=120),
    authorization_id: UUID | None = None,
    failure_code: str | None = Query(default=None, max_length=120),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    requires_attention: bool | None = None,
) -> AIOperationsFilters:
    return AIOperationsFilters(
        workflow_type=workflow_type,
        claim_id=claim_id,
        document_id=document_id,
        document_type=document_type,
        status=status,
        human_review_state=human_review_state,
        human_review_action=human_review_action,
        provider=provider,
        model=model,
        authorization_id=authorization_id,
        failure_code=failure_code,
        created_from=created_from,
        created_to=created_to,
        requires_attention=requires_attention,
    )


@router.get("", response_model=AIOperationsDashboard)
def operations_dashboard(manager: Manager, db: Annotated[Session, Depends(get_db)]):
    return dashboard(db, manager.organization_id)


@router.get("/events", response_model=AIOperationsPage)
def events_list(
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
    filters: Annotated[AIOperationsFilters, Depends(_filters)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    return query_events(db, manager.organization_id, filters, page=page, page_size=page_size)


@router.get("/events/{workflow_type}/{event_id}", response_model=AIOperationsEvent)
def event_detail(
    workflow_type: Literal["document_processing", "claim_qa_synthesis"],
    event_id: UUID,
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
):
    return get_event(db, manager.organization_id, workflow_type, event_id)


@router.get("/review-queue", response_model=AIOperationsPage)
def review_queue(
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    return pending_review_queue(db, manager.organization_id, page=page, page_size=page_size)


@router.post("/events/document_processing/{event_id}/review", response_model=AIOperationsEvent)
def event_review(
    event_id: UUID,
    payload: AIProductionDecisionLogReview,
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
):
    return review_document_event(db, manager, event_id, payload.model_dump())


@router.post("/events/{workflow_type}/{event_id}/incident")
def event_incident_handoff(
    workflow_type: Literal["document_processing", "claim_qa_synthesis"],
    event_id: UUID,
    payload: AIOperationsIncidentCreate,
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
):
    return handoff_incident(
        db,
        manager,
        workflow_type=workflow_type,
        event_id=event_id,
        **payload.model_dump(),
    )


@router.post("/export")
def operations_export(
    payload: AIOperationsExportRequest,
    manager: Manager,
    db: Annotated[Session, Depends(get_db)],
):
    content, media_type, row_count = export_events(
        db,
        manager,
        filters=payload.filters,
        export_format=payload.format,
        max_rows=payload.max_rows,
    )
    filename = f"ai-operations-content-free-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.{payload.format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AI-Operations-Row-Count": str(row_count),
            "X-AI-Operations-Content-Free": "true",
        },
    )
