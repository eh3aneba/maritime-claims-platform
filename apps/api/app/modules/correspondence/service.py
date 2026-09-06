from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.correspondence.models import (
    ClaimCorrespondence,
    CorrespondenceDirection,
    CorrespondenceKind,
    CorrespondenceReviewDecision,
    CorrespondenceSensitivity,
    CorrespondenceStatus,
)
from app.modules.correspondence.schemas import (
    CorrespondenceCreate,
    CorrespondenceMarkSent,
    CorrespondenceReview,
    CorrespondenceTransition,
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


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


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
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _state_fingerprint(item: ClaimCorrespondence) -> str:
    """Identity of the exact communication state a human reviews.

    Dispatch metadata (channel/reference/sent timestamp) is deliberately excluded because it is
    recorded only after approval. Dynamic requirement status is also excluded here and will be
    handled as request-context binding in Phase 13.9B rather than invalidating unrelated free-form
    correspondence when the claim changes elsewhere.
    """

    return _canonical_hash({
        "direction": item.direction.value,
        "kind": item.kind.value,
        "sensitivity": item.sensitivity.value,
        "sender_label": item.sender_label or "",
        "recipient_label": item.recipient_label or "",
        "subject": item.subject.strip(),
        "body": item.body.strip(),
        "request_batch_id": str(item.request_batch_id) if item.request_batch_id else None,
        "requirement_ids": sorted(str(value) for value in (item.requirement_ids or [])),
    })


def _review_hash(
    *,
    item: ClaimCorrespondence,
    review_number: int,
    action: str,
    note: str,
    content_hash: str | None,
    reviewed_by_id: UUID | None,
    previous_review_hash: str | None,
) -> str:
    return _canonical_hash({
        "organization_id": str(item.organization_id),
        "claim_id": str(item.claim_id),
        "correspondence_id": str(item.id),
        "correspondence_state_fingerprint": item.state_fingerprint,
        "state_version": item.state_version,
        "review_number": review_number,
        "action": action,
        "note": note,
        "content_hash": content_hash,
        "reviewed_by_id": str(reviewed_by_id) if reviewed_by_id else None,
        "previous_review_hash": previous_review_hash,
    })


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


def _locked(db: Session, item: ClaimCorrespondence) -> ClaimCorrespondence:
    locked = db.scalar(
        select(ClaimCorrespondence).where(
            ClaimCorrespondence.id == item.id,
            ClaimCorrespondence.organization_id == item.organization_id,
            ClaimCorrespondence.claim_id == item.claim_id,
        ).with_for_update()
    )
    if locked is None:
        raise HTTPException(status_code=404, detail="Correspondence record not found")
    return locked


def _assert_expected_state(
    item: ClaimCorrespondence,
    *,
    expected_state_fingerprint: str,
    expected_state_version: int,
) -> None:
    if (
        item.state_fingerprint != expected_state_fingerprint
        or item.state_version != expected_state_version
    ):
        raise HTTPException(
            status_code=409,
            detail="Correspondence content or linked context changed. Refresh before continuing.",
        )


def review_history(db: Session, *, item: ClaimCorrespondence) -> list[CorrespondenceReviewDecision]:
    return list(
        db.scalars(
            select(CorrespondenceReviewDecision)
            .where(
                CorrespondenceReviewDecision.organization_id == item.organization_id,
                CorrespondenceReviewDecision.claim_id == item.claim_id,
                CorrespondenceReviewDecision.correspondence_id == item.id,
            )
            .order_by(CorrespondenceReviewDecision.review_number.asc())
        )
    )


def _review_payload(decision: CorrespondenceReviewDecision) -> dict:
    return {
        "id": decision.id,
        "correspondence_id": decision.correspondence_id,
        "reviewed_by_id": decision.reviewed_by_id,
        "correspondence_state_fingerprint": decision.correspondence_state_fingerprint,
        "state_version": decision.state_version,
        "review_number": decision.review_number,
        "action": decision.action,
        "note": decision.note,
        "content_hash": decision.content_hash,
        "previous_review_hash": decision.previous_review_hash,
        "review_hash": decision.review_hash,
        "reviewed_at": decision.reviewed_at,
    }


def correspondence_response(db: Session, *, item: ClaimCorrespondence) -> dict:
    history = review_history(db, item=item)
    latest = history[-1] if history else None
    if not item.state_fingerprint:
        review_state = "legacy_unbound"
    elif latest is None:
        review_state = "none"
    elif (
        latest.correspondence_state_fingerprint == item.state_fingerprint
        and latest.state_version == item.state_version
    ):
        review_state = "current"
    else:
        review_state = "stale"
    return {
        "id": item.id,
        "claim_id": item.claim_id,
        "request_batch_id": item.request_batch_id,
        "created_by_id": item.created_by_id,
        "reviewed_by_id": item.reviewed_by_id,
        "sent_by_id": item.sent_by_id,
        "direction": item.direction,
        "kind": item.kind,
        "status": item.status,
        "sensitivity": item.sensitivity,
        "channel": item.channel,
        "sender_label": item.sender_label,
        "recipient_label": item.recipient_label,
        "subject": item.subject,
        "body": item.body,
        "requirement_ids": item.requirement_ids,
        "review_note": item.review_note,
        "external_reference": item.external_reference,
        "content_hash": item.content_hash,
        "state_fingerprint": item.state_fingerprint,
        "state_version": item.state_version,
        "sent_review_hash": item.sent_review_hash,
        "review_state": review_state,
        "latest_review": _review_payload(latest) if latest else None,
        "review_history": [_review_payload(decision) for decision in history],
        "occurred_at": item.occurred_at,
        "reviewed_at": item.reviewed_at,
        "sent_at": item.sent_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


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
        state_fingerprint="0" * 64,
        state_version=1,
    )
    item.state_fingerprint = _state_fingerprint(item)
    db.add(item)
    db.flush()
    _audit(
        db,
        item=item,
        user=user,
        action="CREATE_CORRESPONDENCE",
        values={
            "direction": item.direction.value,
            "status": item.status.value,
            "sensitivity": item.sensitivity.value,
            "state_fingerprint": item.state_fingerprint,
            "state_version": item.state_version,
        },
    )
    db.commit()
    db.refresh(item)
    return item


def create_from_document_request(db: Session, *, claim: Claim, user: User, batch: DocumentRequestBatch) -> ClaimCorrespondence:
    existing = db.scalar(select(ClaimCorrespondence).where(
        ClaimCorrespondence.request_batch_id == batch.id,
        ClaimCorrespondence.organization_id == claim.organization_id,
        ClaimCorrespondence.claim_id == claim.id,
    ))
    if existing is not None:
        return existing
    item = ClaimCorrespondence(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        request_batch_id=batch.id,
        created_by_id=user.id,
        direction=CorrespondenceDirection.OUTBOUND,
        kind=CorrespondenceKind.DOCUMENT_REQUEST,
        status=CorrespondenceStatus.DRAFT,
        sensitivity=CorrespondenceSensitivity.STANDARD,
        recipient_label=batch.recipient_label,
        subject=batch.subject,
        body=batch.draft_body,
        requirement_ids=list(batch.requirement_ids or []),
        state_fingerprint="0" * 64,
        state_version=1,
    )
    item.state_fingerprint = _state_fingerprint(item)
    db.add(item)
    db.flush()
    _audit(
        db,
        item=item,
        user=user,
        action="CREATE_CORRESPONDENCE_FROM_DOCUMENT_REQUEST",
        values={
            "request_batch_id": str(batch.id),
            "requirement_ids": item.requirement_ids,
            "state_fingerprint": item.state_fingerprint,
            "state_version": item.state_version,
        },
    )
    return item


def update_correspondence(db: Session, *, item: ClaimCorrespondence, user: User, payload: CorrespondenceUpdate) -> ClaimCorrespondence:
    item = _locked(db, item)
    _assert_expected_state(
        item,
        expected_state_fingerprint=payload.expected_state_fingerprint,
        expected_state_version=payload.expected_state_version,
    )
    if item.status not in {CorrespondenceStatus.DRAFT, CorrespondenceStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="Only draft or rejected correspondence can be edited")

    fields = payload.model_fields_set
    for name in ("kind", "sensitivity"):
        if name in fields:
            value = getattr(payload, name)
            if value is not None:
                setattr(item, name, value)
    for name in ("sender_label", "recipient_label"):
        if name in fields:
            value = getattr(payload, name)
            setattr(item, name, (value or "").strip() or None)
    for name in ("subject", "body"):
        if name in fields:
            value = getattr(payload, name)
            if value is not None:
                setattr(item, name, value.strip())

    item.body = _normalise_body(item.body, item.sensitivity)
    next_fingerprint = _state_fingerprint(item)
    if next_fingerprint == item.state_fingerprint:
        return item

    previous_fingerprint = item.state_fingerprint
    previous_version = item.state_version
    item.state_version += 1
    item.state_fingerprint = next_fingerprint
    item.status = CorrespondenceStatus.DRAFT
    item.review_note = None
    item.reviewed_by_id = None
    item.reviewed_at = None
    item.content_hash = None
    item.sent_review_hash = None
    _audit(
        db,
        item=item,
        user=user,
        action="UPDATE_CORRESPONDENCE_DRAFT",
        values={
            "status": item.status.value,
            "sensitivity": item.sensitivity.value,
            "previous_state_fingerprint": previous_fingerprint,
            "previous_state_version": previous_version,
            "state_fingerprint": item.state_fingerprint,
            "state_version": item.state_version,
        },
        details="Material correspondence content changed; prior human review lineage was preserved as historical and the new state requires review.",
    )
    db.commit()
    db.refresh(item)
    return item


def submit_correspondence(
    db: Session,
    *,
    item: ClaimCorrespondence,
    user: User,
    payload: CorrespondenceTransition,
) -> ClaimCorrespondence:
    item = _locked(db, item)
    _assert_expected_state(
        item,
        expected_state_fingerprint=payload.expected_state_fingerprint,
        expected_state_version=payload.expected_state_version,
    )
    if item.direction != CorrespondenceDirection.OUTBOUND:
        raise HTTPException(status_code=409, detail="Only outbound correspondence can be submitted for review")
    if item.status == CorrespondenceStatus.UNDER_REVIEW:
        return item
    if item.status != CorrespondenceStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Only outbound drafts can be submitted for review")
    item.status = CorrespondenceStatus.UNDER_REVIEW
    _audit(
        db,
        item=item,
        user=user,
        action="SUBMIT_CORRESPONDENCE_FOR_REVIEW",
        values={
            "status": item.status.value,
            "state_fingerprint": item.state_fingerprint,
            "state_version": item.state_version,
        },
    )
    db.commit()
    db.refresh(item)
    return item


def review_correspondence(
    db: Session,
    *,
    item: ClaimCorrespondence,
    user: User,
    approve: bool,
    payload: CorrespondenceReview,
) -> ClaimCorrespondence:
    item = _locked(db, item)
    _assert_expected_state(
        item,
        expected_state_fingerprint=payload.expected_state_fingerprint,
        expected_state_version=payload.expected_state_version,
    )
    history = review_history(db, item=item)
    latest = history[-1] if history else None
    action = "approve" if approve else "reject"
    clean_note = payload.note.strip()
    resulting_status = CorrespondenceStatus.APPROVED if approve else CorrespondenceStatus.REJECTED

    if (
        latest is not None
        and latest.correspondence_state_fingerprint == item.state_fingerprint
        and latest.state_version == item.state_version
        and latest.action == action
        and latest.note == clean_note
        and latest.reviewed_by_id == user.id
        and item.status == resulting_status
    ):
        return item

    if item.status != CorrespondenceStatus.UNDER_REVIEW:
        raise HTTPException(status_code=409, detail="Only correspondence under review can be approved or rejected")
    if latest is not None and not payload.confirm_re_review:
        raise HTTPException(
            status_code=409,
            detail="A prior human correspondence review exists. Explicit re-review confirmation is required for the revised state.",
        )

    review_number = latest.review_number + 1 if latest is not None else 1
    previous_hash = latest.review_hash if latest is not None else None
    approved_content_hash = _content_hash(item) if approve else None
    reviewed_at = datetime.now(UTC)
    review_hash = _review_hash(
        item=item,
        review_number=review_number,
        action=action,
        note=clean_note,
        content_hash=approved_content_hash,
        reviewed_by_id=user.id,
        previous_review_hash=previous_hash,
    )
    decision = CorrespondenceReviewDecision(
        organization_id=item.organization_id,
        claim_id=item.claim_id,
        correspondence_id=item.id,
        reviewed_by_id=user.id,
        correspondence_state_fingerprint=item.state_fingerprint,
        state_version=item.state_version,
        review_number=review_number,
        action=action,
        note=clean_note,
        content_hash=approved_content_hash,
        previous_review_hash=previous_hash,
        review_hash=review_hash,
        reviewed_at=reviewed_at,
    )
    db.add(decision)
    item.status = resulting_status
    item.review_note = clean_note
    item.reviewed_by_id = user.id
    item.reviewed_at = reviewed_at
    item.content_hash = approved_content_hash
    item.sent_review_hash = None
    db.flush()
    _audit(
        db,
        item=item,
        user=user,
        action="APPROVE_CORRESPONDENCE" if approve else "REJECT_CORRESPONDENCE",
        values={
            "status": item.status.value,
            "content_hash": item.content_hash,
            "state_fingerprint": item.state_fingerprint,
            "state_version": item.state_version,
            "review_number": decision.review_number,
            "review_hash": decision.review_hash,
            "previous_review_hash": decision.previous_review_hash,
        },
        details="Human correspondence review was appended to immutable review lineage and bound to the exact reviewed communication state.",
    )
    db.commit()
    db.refresh(item)
    return item


def mark_correspondence_sent(db: Session, *, claim: Claim, item: ClaimCorrespondence, user: User, payload: CorrespondenceMarkSent) -> ClaimCorrespondence:
    if not payload.confirm_sent:
        raise HTTPException(status_code=422, detail="Explicit confirmation that the correspondence was sent is required")
    item = _locked(db, item)
    _assert_expected_state(
        item,
        expected_state_fingerprint=payload.expected_state_fingerprint,
        expected_state_version=payload.expected_state_version,
    )
    clean_reference = (payload.external_reference or "").strip() or None

    if item.status == CorrespondenceStatus.SENT_EXTERNALLY:
        sent_at_matches = payload.sent_at is None or item.sent_at == payload.sent_at
        if (
            item.sent_review_hash == payload.expected_review_hash
            and item.channel == payload.channel
            and item.external_reference == clean_reference
            and sent_at_matches
        ):
            return item
        raise HTTPException(
            status_code=409,
            detail="This correspondence already has a different external-dispatch record.",
        )

    if item.status != CorrespondenceStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Only approved correspondence can be marked Sent Externally")

    history = review_history(db, item=item)
    latest = history[-1] if history else None
    if (
        latest is None
        or latest.action != "approve"
        or latest.correspondence_state_fingerprint != item.state_fingerprint
        or latest.state_version != item.state_version
    ):
        raise HTTPException(status_code=409, detail="A current human approval is required before external dispatch can be recorded")
    if latest.review_hash != payload.expected_review_hash:
        raise HTTPException(status_code=409, detail="The approved review changed. Refresh before recording external dispatch")
    if (
        not item.content_hash
        or item.content_hash != _content_hash(item)
        or latest.content_hash != item.content_hash
    ):
        raise HTTPException(status_code=409, detail="Approved content has changed and must be reviewed again")

    item.status = CorrespondenceStatus.SENT_EXTERNALLY
    item.channel = payload.channel
    item.external_reference = clean_reference
    item.sent_by_id = user.id
    item.sent_at = payload.sent_at or datetime.now(UTC)
    item.occurred_at = item.sent_at
    item.sent_review_hash = latest.review_hash

    if item.request_batch_id:
        batch = db.scalar(select(DocumentRequestBatch).where(
            DocumentRequestBatch.id == item.request_batch_id,
            DocumentRequestBatch.organization_id == claim.organization_id,
            DocumentRequestBatch.claim_id == claim.id,
        ).with_for_update())
        if batch is None or batch.status != RequestBatchStatus.DRAFT:
            raise HTTPException(status_code=409, detail="Linked document request is unavailable or no longer a draft")
        ids = {UUID(value) for value in item.requirement_ids}
        requirements = list(db.scalars(select(ClaimDocumentRequirement).where(
            ClaimDocumentRequirement.organization_id == claim.organization_id,
            ClaimDocumentRequirement.claim_id == claim.id,
            ClaimDocumentRequirement.id.in_(ids),
        ).with_for_update())) if ids else []
        if len(requirements) != len(ids):
            raise HTTPException(status_code=409, detail="One or more linked document requirements are no longer available")
        for requirement in requirements:
            if requirement.status in {RequirementStatus.MISSING, RequirementStatus.REJECTED}:
                requirement.status = RequirementStatus.REQUESTED
        batch.status = RequestBatchStatus.SENT_EXTERNALLY

    _audit(
        db,
        item=item,
        user=user,
        action="MARK_CORRESPONDENCE_SENT_EXTERNALLY",
        values={
            "status": item.status.value,
            "channel": item.channel.value,
            "external_reference": item.external_reference,
            "state_fingerprint": item.state_fingerprint,
            "state_version": item.state_version,
            "approved_review_hash": latest.review_hash,
            "content_hash": item.content_hash,
        },
        details="User explicitly confirmed dispatch outside the platform; the platform did not send this correspondence. Dispatch was bound to the exact current human approval and content state.",
    )
    db.commit()
    db.refresh(item)
    return item
