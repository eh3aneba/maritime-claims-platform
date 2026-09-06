from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.correspondence.models import (
    ClaimCorrespondence,
    CorrespondenceDirection,
    CorrespondenceStatus,
)
from app.modules.correspondence.schemas import CorrespondenceTransition
from app.modules.correspondence.service import (
    _assert_expected_state,
    _audit,
    _locked,
    review_history,
)
from app.modules.users.models import User


def reopen_correspondence_for_revision(
    db: Session,
    *,
    item: ClaimCorrespondence,
    user: User,
    payload: CorrespondenceTransition,
) -> ClaimCorrespondence:
    """Return one approved, unsent outbound communication to draft for deliberate revision.

    The transition never rewrites or deletes review decisions. It only clears the flat current-
    approval pointers so any later material edit is assigned a new state identity and must pass
    submit/re-review again before an external-dispatch record can be created.
    """

    item = _locked(db, item)
    _assert_expected_state(
        item,
        expected_state_fingerprint=payload.expected_state_fingerprint,
        expected_state_version=payload.expected_state_version,
    )
    if item.direction != CorrespondenceDirection.OUTBOUND:
        raise HTTPException(status_code=409, detail="Only outbound correspondence can be reopened for revision")
    if item.status == CorrespondenceStatus.SENT_EXTERNALLY or item.sent_at or item.sent_review_hash:
        raise HTTPException(status_code=409, detail="Sent correspondence is immutable and cannot be reopened for revision")

    history = review_history(db, item=item)
    latest = history[-1] if history else None
    current_approval = bool(
        latest is not None
        and latest.action == "approve"
        and latest.correspondence_state_fingerprint == item.state_fingerprint
        and latest.state_version == item.state_version
    )

    # Safe replay: the exact approved state was already deliberately reopened and has not yet
    # been materially edited. Do not create duplicate audit/recovery transitions.
    if item.status == CorrespondenceStatus.DRAFT and current_approval:
        return item

    if item.status != CorrespondenceStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Only approved unsent correspondence can be reopened for revision")
    if not current_approval:
        raise HTTPException(status_code=409, detail="A current human approval is required before revision recovery")

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
        action="REOPEN_APPROVED_CORRESPONDENCE_FOR_REVISION",
        values={
            "status": item.status.value,
            "state_fingerprint": item.state_fingerprint,
            "state_version": item.state_version,
            "historical_approval_review_hash": latest.review_hash,
            "historical_review_number": latest.review_number,
        },
        details=(
            "User deliberately reopened approved unsent correspondence for revision. The historical "
            "human approval remains immutable; any material edit must receive a new state identity "
            "and explicit human re-review before external dispatch can be recorded."
        ),
    )
    db.commit()
    db.refresh(item)
    return item
