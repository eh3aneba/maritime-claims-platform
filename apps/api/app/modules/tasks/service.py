from __future__ import annotations

from datetime import UTC, datetime
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.correspondence.service import create_from_document_request
from app.modules.rules.models import ClaimDocumentRequirement, RequirementPriority, RequirementStatus
from app.modules.tasks.models import (
    ClaimTask,
    DocumentRequestBatch,
    RequestBatchStatus,
    TaskPriority,
    TaskSource,
    TaskStatus,
    TaskType,
)
from app.modules.tasks.schemas import DocumentRequestCreate
from app.modules.users.models import User


_PRIORITY_MAP = {
    RequirementPriority.CRITICAL: TaskPriority.CRITICAL,
    RequirementPriority.IMPORTANT: TaskPriority.HIGH,
    RequirementPriority.SUPPORTING: TaskPriority.MEDIUM,
}


def list_tasks(db: Session, *, claim: Claim) -> list[ClaimTask]:
    return list(db.scalars(select(ClaimTask).where(
        ClaimTask.organization_id == claim.organization_id,
        ClaimTask.claim_id == claim.id,
    ).order_by(ClaimTask.status.asc(), ClaimTask.due_date.asc().nullslast(), ClaimTask.created_at.desc())))


def _requestable_requirements(db: Session, *, claim: Claim, payload: DocumentRequestCreate) -> list[ClaimDocumentRequirement]:
    query = select(ClaimDocumentRequirement).where(
        ClaimDocumentRequirement.organization_id == claim.organization_id,
        ClaimDocumentRequirement.claim_id == claim.id,
        ClaimDocumentRequirement.is_active.is_(True),
    )
    requirements = list(db.scalars(query))
    if payload.all_critical:
        selected = [r for r in requirements if r.priority == RequirementPriority.CRITICAL and r.status in {RequirementStatus.MISSING, RequirementStatus.REJECTED}]
    else:
        ids = set(payload.requirement_ids)
        selected = [r for r in requirements if r.id in ids]
        if len(selected) != len(ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more document requirements were not found")
        bad = [r.document_label for r in selected if r.status not in {RequirementStatus.MISSING, RequirementStatus.REJECTED, RequirementStatus.REQUESTED}]
        if bad:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Already satisfied requirements cannot be requested: {', '.join(bad)}")
    if not selected:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No requestable document requirements match the selection")
    selected.sort(key=lambda r: (0 if r.priority == RequirementPriority.CRITICAL else 1, r.document_label))
    return selected


def _draft_body(claim: Claim, requirements: list[ClaimDocumentRequirement], due_date) -> str:
    lines = [
        "Dear Sir/Madam,",
        "",
        f"Further to the above matter concerning {claim.claim_reference}, kindly provide the following outstanding documents for our further review:",
        "",
    ]
    for idx, requirement in enumerate(requirements, 1):
        lines.append(f"{idx}. {requirement.document_label}")
    if due_date:
        lines.extend(["", f"We would appreciate receipt by {due_date.isoformat()} where possible."])
    lines.extend(["", "Please let us know if any item is unavailable and provide the reason or an appropriate alternative record.", "", "Kind regards,"])
    return "\n".join(lines)


def create_document_request(db: Session, *, claim: Claim, user: User, payload: DocumentRequestCreate) -> tuple[DocumentRequestBatch, list[ClaimTask]]:
    requirements = _requestable_requirements(db, claim=claim, payload=payload)
    if payload.assignee_id is not None:
        assignee = db.get(User, payload.assignee_id)
        if assignee is None or assignee.organization_id != claim.organization_id or not assignee.is_active:
            raise HTTPException(status_code=422, detail="Assignee must be an active user in the current organization")
    subject = f"{claim.claim_reference} – Outstanding claim documents"
    batch = DocumentRequestBatch(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        created_by_id=user.id,
        recipient_label=(payload.recipient_label or "Shipowner / Assured").strip() or None,
        subject=subject,
        draft_body=_draft_body(claim, requirements, payload.due_date),
        requirement_ids=[str(r.id) for r in requirements],
        status=RequestBatchStatus.DRAFT,
        due_date=payload.due_date,
    )
    db.add(batch)
    db.flush()

    tasks: list[ClaimTask] = []
    now = datetime.now(UTC)
    for requirement in requirements:
        existing = db.scalar(select(ClaimTask).where(
            ClaimTask.organization_id == claim.organization_id,
            ClaimTask.claim_id == claim.id,
            ClaimTask.requirement_id == requirement.id,
            ClaimTask.status == TaskStatus.OPEN,
            ClaimTask.task_type == TaskType.DOCUMENT_REQUEST,
        ))
        if existing is not None:
            existing.request_batch_id = batch.id
            existing.due_date = payload.due_date or existing.due_date
            existing.assignee_id = payload.assignee_id or existing.assignee_id
            tasks.append(existing)
            continue
        task = ClaimTask(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            requirement_id=requirement.id,
            request_batch_id=batch.id,
            assignee_id=payload.assignee_id or claim.handler_id or user.id,
            title=f"Obtain {requirement.document_label}",
            description=requirement.reason,
            task_type=TaskType.DOCUMENT_REQUEST,
            status=TaskStatus.OPEN,
            priority=_PRIORITY_MAP[requirement.priority],
            source=TaskSource.RULE,
            due_date=payload.due_date,
        )
        db.add(task)
        db.flush()
        tasks.append(task)

    create_from_document_request(db, claim=claim, user=user, batch=batch)

    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="CREATE_DOCUMENT_REQUEST",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "request_batch_id": str(batch.id),
            "requirement_ids": [str(r.id) for r in requirements],
            "task_ids": [str(t.id) for t in tasks],
            "due_date": payload.due_date.isoformat() if payload.due_date else None,
        },
    )
    db.commit()
    db.refresh(batch)
    for task in tasks:
        db.refresh(task)
    return batch, tasks


def mark_request_sent(db: Session, *, claim: Claim, batch: DocumentRequestBatch, user: User) -> DocumentRequestBatch:
    del db, claim, batch, user
    raise HTTPException(
        status_code=409,
        detail="Use the Correspondence Centre review and explicit Sent Externally confirmation workflow",
    )


def complete_task(db: Session, *, task: ClaimTask, user: User, reason: str) -> ClaimTask:
    if task.status != TaskStatus.OPEN:
        raise HTTPException(status_code=409, detail="Only open tasks can be completed")
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(UTC)
    task.completed_by_id = user.id
    task.completion_reason = reason.strip()
    write_audit_log(db, organization_id=task.organization_id, user_id=user.id, action="COMPLETE_CLAIM_TASK", entity_type="claim_task", entity_id=task.id, new_values={"status": "completed", "reason": task.completion_reason})
    db.commit(); db.refresh(task)
    return task


def sync_requirement_tasks(db: Session, *, claim: Claim, user: User | None = None) -> int:
    satisfied = list(db.scalars(select(ClaimDocumentRequirement).where(
        ClaimDocumentRequirement.organization_id == claim.organization_id,
        ClaimDocumentRequirement.claim_id == claim.id,
        ClaimDocumentRequirement.status.in_([RequirementStatus.RECEIVED, RequirementStatus.UNDER_REVIEW, RequirementStatus.ACCEPTED]),
    )))
    count = 0
    now = datetime.now(UTC)
    for requirement in satisfied:
        tasks = list(db.scalars(select(ClaimTask).where(
            ClaimTask.organization_id == claim.organization_id,
            ClaimTask.claim_id == claim.id,
            ClaimTask.requirement_id == requirement.id,
            ClaimTask.status == TaskStatus.OPEN,
        )))
        for task in tasks:
            task.status = TaskStatus.COMPLETED
            task.completed_at = now
            task.completed_by_id = user.id if user else None
            task.completion_reason = (
                "Automatically completed because human-approved equivalent evidence satisfied the document requirement."
                if requirement.satisfaction_basis == "equivalent_evidence"
                else "Automatically completed because the required document was received."
            )
            count += 1
            write_audit_log(db, organization_id=claim.organization_id, user_id=user.id if user else None, action="AUTO_COMPLETE_DOCUMENT_TASK", entity_type="claim_task", entity_id=task.id, new_values={"requirement_id": str(requirement.id), "status": "completed"})
    return count
