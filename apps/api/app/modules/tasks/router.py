from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.tasks.models import ClaimTask, DocumentRequestBatch
from app.modules.tasks.schemas import ClaimTaskResponse, DocumentRequestBatchResponse, DocumentRequestCreate, DocumentRequestResult, TaskCompleteRequest, TaskListResponse
from app.modules.tasks.service import complete_task, create_document_request, list_tasks, mark_request_sent

router = APIRouter(prefix="/claims/{claim_id}", tags=["tasks"])


@router.get("/tasks", response_model=TaskListResponse)
def claim_tasks(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> TaskListResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    items = list_tasks(db, claim=claim)
    return TaskListResponse(items=items, total=len(items))


@router.post("/document-requests", response_model=DocumentRequestResult, status_code=status.HTTP_201_CREATED)
def create_request(claim_id: UUID, payload: DocumentRequestCreate, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> DocumentRequestResult:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    batch, tasks = create_document_request(db, claim=claim, user=current_user, payload=payload)
    return DocumentRequestResult(batch=batch, tasks=tasks)


@router.post("/document-requests/{batch_id}/mark-sent", response_model=DocumentRequestBatchResponse)
def mark_request_as_sent(claim_id: UUID, batch_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> DocumentRequestBatchResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    batch = db.scalar(select(DocumentRequestBatch).where(
        DocumentRequestBatch.id == batch_id,
        DocumentRequestBatch.claim_id == claim.id,
        DocumentRequestBatch.organization_id == current_user.organization_id,
    ))
    if batch is None:
        raise HTTPException(status_code=404, detail="Document request draft not found")
    return mark_request_sent(db, claim=claim, batch=batch, user=current_user)


@router.post("/tasks/{task_id}/complete", response_model=ClaimTaskResponse)
def complete_claim_task(claim_id: UUID, task_id: UUID, payload: TaskCompleteRequest, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    task = db.scalar(select(ClaimTask).where(ClaimTask.id == task_id, ClaimTask.claim_id == claim.id, ClaimTask.organization_id == current_user.organization_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return complete_task(db, task=task, user=current_user, reason=payload.reason)
