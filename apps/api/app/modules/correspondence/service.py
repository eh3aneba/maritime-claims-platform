from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.correspondence.models import (
    ClaimCorrespondence,
    CorrespondenceDirection,
    CorrespondenceSensitivity,
    CorrespondenceStatus,
)
from app.modules.correspondence.schemas import (
    CorrespondenceCreate,
    CorrespondenceMarkSent,
    CorrespondenceUpdate,
)
from app.modules.rules.models import ClaimDocumentRequirement, RequirementStatus
from app.modules.tasks.models import DocumentRequestBatch, RequestBatchStatus
from app.modules.users.models import User


_SENSITIVE_HEADINGS = {
    CorrespondenceSensitivity.CONFIDENTIAL: "CONFIDENTIAL",
    CorrespondenceSensitivity.PRIVILEGED_CONFIDENTIAL: "PRIVILEGED & CONFIDENTIAL",
    CorrespondenceSensitivity.WITHOUT_PREJUDICE: "WITHOUT PREJUDICE",
}


def _normalise_body(body: str, sensitivity: CorrespondenceSensitivity) -> str:
    value = body.strip()
    heading = _SENSITIVE_HEADINGS.get(sensitivity)
    if heading and not value.upper().startswith(heading):
        value = f"{heading}\n\n{value}"
    return value


def _content_hash(item: ClaimCorrespondence) -> str:
    canonical = "\n".join([
        item.direction.value,
        item.kind.value,
        item.sensitivity.value,
        item.sender_label or "",
        item.recipient_label or "",
        item.subject.strip(),
        item.body.strip(),
    ])
    return sha256(canonical.encode("utf-8")).hexdigest()


def _audit(db: Session, *, item: ClaimCorrespondence, user: User, action: str, values: dict, details: str | None = None) -> None:
    write_audit_log(
        db,
        organization_id=item.organization_id,
        user_id=user.id,
        action=action,
        entity_type="claim_correspondence",
        entity_id=item.id,
        new_values=values,
        details=details,
    )


def list_correspondence(db: Session, *, claim: Claim) -> list[ClaimCorrespondence]:
    return list(db.scalars(select(ClaimCorrespondence).where(
        ClaimCorrespondence.organization_id == claim.organization_id,
        ClaimCorrespondence.claim_id == claim.id,
    ).order_by(ClaimCorrespondence.created_at.desc())))


def get_correspondence(db: Session, *, claim: Claim, correspondence_id: UUID) -> ClaimCorrespondence:
    item = db.scalar(select(ClaimCorrespondence).where(
        ClaimCorrespondence.id == correspondence_id,
        ClaimCorrespondence.organization_id == claim.organization_id,
        ClaimCorrespondence.claim_id == claim.id,
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Correspondence record not found")
    return item


def create_correspondence(db: Session, *, claim: Claim, user: User, payload: CorrespondenceCreate) -> ClaimCorrespondence:
    if payload.direction == CorrespondenceDirection.OUTBOUND:
        item_status = CorrespondenceStatus.DRAFT
    elif payload.direction == CorrespondenceDirection.INBOUND:
        item_status = CorrespondenceStatus.RECEIVED_EXTERNAL
    else:
        item_status = CorrespondenceStatus.FILED_INTERNAL
    item = ClaimCorrespondence(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        created_by_id=user.id,
        direction=payload.direction,
        kind=payload.kind,
        status=item_status,
        sensitivity=payload.sensitivity,
        channel=payload.channel,
        sender_label=(payload.sender_label or "").strip() or None,
        recipient_label=(payload.recipient_label or "").strip() or None,
        subject=payload.subject.strip(),
        body=_normalise_body(payload.body, payload.sensitivity),
        requirement_ids=[],
        external_reference=(payload.external_reference or "").strip() or None,
        occurred_at=payload.occurred_at or (datetime.now(UTC) if payload.direction != CorrespondenceDirection.OUTBOUND else None),
    )
    db.add(item)
    db.flush()
    _audit(db, item=item, user=user, action="CREATE_CORRESPONDENCE", values={"direction": item.direction.value, "status": item.status.value, "sensitivity": item.sensitivity.value})
    db.commit()
    db.refresh(item)
    return item


def create_from_document_request(db: Session, *, claim: Claim, user: User, batch: DocumentRequestBatch) -> ClaimCorrespondence:
    existing = db.scalar(select(ClaimCorrespondence).where(ClaimCorrespondence.request_batch_id == batch.id))
    if existing is not None:
        return existing
    item = ClaimCorrespondence(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        request_batch_id=batch.id,
        created_by_id=user.id,
        direction=CorrespondenceDirection.OUTBOUND,
        kind="document_request",
        status=CorrespondenceStatus.DRAFT,
        sensitivity=CorrespondenceSensitivity.STANDARD,
        recipient_label=batch.recipient_label,
        subject=batch.subject,
        body=batch.draft_body,
        requirement_ids=list(batch.requirement_ids or []),
    )
    db.add(item)
    db.flush()
    _audit(db, item=item, user=user, action="CREATE_CORRESPONDENCE_FROM_DOCUMENT_REQUEST", values={"request_batch_id": str(batch.id), "requirement_ids": item.requirement_ids})
    return item


def update_correspondence(db: Session, *, item: ClaimCorrespondence, user: User, payload: CorrespondenceUpdate) -> ClaimCorrespondence:
    if item.status not in {CorrespondenceStatus.DRAFT, CorrespondenceStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="Only draft or rejected correspondence can be edited")
    for name in ("kind", "sensitivity", "sender_label", "recipient_label", "subject", "body"):
        value = getattr(payload, name)
        if value is not None:
            setattr(item, name, value.strip() if isinstance(value, str) else value)
    item.body = _normalise_body(item.body, item.sensitivity)
    item.status = CorrespondenceStatus.DRAFT
    item.review_note = None
    item.reviewed_by_id = None
    item.reviewed_at = None
    item.content_hash = None
    _audit(db, item=item, user=user, action="UPDATE_CORRESPONDENCE_DRAFT", values={"status": item.status.value, "sensitivity": item.sensitivity.value})
    db.commit()
    db.refresh(item)
    return item


def submit_correspondence(db: Session, *, item: ClaimCorrespondence, user: User) -> ClaimCorrespondence:
    if item.direction != CorrespondenceDirection.OUTBOUND or item.status != CorrespondenceStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Only outbound drafts can be submitted for review")
    item.status = CorrespondenceStatus.UNDER_REVIEW
    _audit(db, item=item, user=user, action="SUBMIT_CORRESPONDENCE_FOR_REVIEW", values={"status": item.status.value})
    db.commit()
    db.refresh(item)
    return item


def review_correspondence(db: Session, *, item: ClaimCorrespondence, user: User, approve: bool, note: str) -> ClaimCorrespondence:
    if item.status != CorrespondenceStatus.UNDER_REVIEW:
        raise HTTPException(status_code=409, detail="Only correspondence under review can be approved or rejected")
    item.status = CorrespondenceStatus.APPROVED if approve else CorrespondenceStatus.REJECTED
    item.review_note = note.strip()
    item.reviewed_by_id = user.id
    item.reviewed_at = datetime.now(UTC)
    item.content_hash = _content_hash(item) if approve else None
    _audit(db, item=item, user=user, action="APPROVE_CORRESPONDENCE" if approve else "REJECT_CORRESPONDENCE", values={"status": item.status.value, "content_hash": item.content_hash})
    db.commit()
    db.refresh(item)
    return item


def mark_correspondence_sent(db: Session, *, claim: Claim, item: ClaimCorrespondence, user: User, payload: CorrespondenceMarkSent) -> ClaimCorrespondence:
    if not payload.confirm_sent:
        raise HTTPException(status_code=422, detail="Explicit confirmation that the correspondence was sent is required")
    if item.status != CorrespondenceStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Only approved correspondence can be marked Sent Externally")
    if not item.content_hash or item.content_hash != _content_hash(item):
        raise HTTPException(status_code=409, detail="Approved content has changed and must be reviewed again")
    item.status = CorrespondenceStatus.SENT_EXTERNALLY
    item.channel = payload.channel
    item.external_reference = (payload.external_reference or "").strip() or None
    item.sent_by_id = user.id
    item.sent_at = payload.sent_at or datetime.now(UTC)
    item.occurred_at = item.sent_at

    if item.request_batch_id:
        batch = db.scalar(select(DocumentRequestBatch).where(
            DocumentRequestBatch.id == item.request_batch_id,
            DocumentRequestBatch.organization_id == claim.organization_id,
            DocumentRequestBatch.claim_id == claim.id,
        ))
        if batch is None or batch.status != RequestBatchStatus.DRAFT:
            raise HTTPException(status_code=409, detail="Linked document request is unavailable or no longer a draft")
        ids = {UUID(value) for value in item.requirement_ids}
        requirements = list(db.scalars(select(ClaimDocumentRequirement).where(
            ClaimDocumentRequirement.organization_id == claim.organization_id,
            ClaimDocumentRequirement.claim_id == claim.id,
            ClaimDocumentRequirement.id.in_(ids),
        ))) if ids else []
        if len(requirements) != len(ids):
            raise HTTPException(status_code=409, detail="One or more linked document requirements are no longer available")
        for requirement in requirements:
            if requirement.status in {RequirementStatus.MISSING, RequirementStatus.REJECTED}:
                requirement.status = RequirementStatus.REQUESTED
        batch.status = RequestBatchStatus.SENT_EXTERNALLY

    _audit(db, item=item, user=user, action="MARK_CORRESPONDENCE_SENT_EXTERNALLY", values={"status": item.status.value, "channel": item.channel.value, "external_reference": item.external_reference}, details="User explicitly confirmed dispatch outside the platform; the platform did not send this correspondence.")
    db.commit()
    db.refresh(item)
    return item
