from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.facts import ClaimFact
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.models import Document
from app.modules.intelligence.models import AISemanticKind, AIReviewStatus
from app.modules.pilot.service import record_active_event
from app.modules.review.schemas import (
    BulkApproveRequest,
    BulkApproveResponse,
    GroupReviewRequest,
    GroupReviewResponse,
    ReviewGroupQueueResponse,
    ClaimFactResponse,
    ExtractionReviewDetail,
    FeedbackResponse,
    ReviewQueueResponse,
    ReviewRequest,
    ReviewResult,
    SourcePreviewResponse,
)
from app.modules.users.models import User
from app.modules.review.service import (
    get_current_claim_fact,
    get_extraction_for_tenant,
    get_feedback_history,
    get_source_segment_for_extraction,
    is_bulk_approvable,
    list_review_groups,
    list_review_queue,
    validate_same_review_group,
    review_extraction,
)

router = APIRouter(prefix="/ai-review", tags=["ai-review"])


def _feedback_response(db: Session, row) -> FeedbackResponse:
    reviewer = db.get(User, row.reviewer_id) if row.reviewer_id else None
    return FeedbackResponse(
        id=row.id,
        action=row.action,
        ai_value=row.ai_value,
        human_value=row.human_value,
        reason=row.reason,
        reviewer_id=row.reviewer_id,
        reviewer_name=reviewer.full_name if reviewer else None,
        reviewer_email=reviewer.email if reviewer else None,
        created_at=row.created_at,
    )


@router.get("", response_model=ReviewQueueResponse)
def review_queue(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    claim_id: UUID | None = None,
    document_id: UUID | None = None,
    review_status: str = "pending",
    semantic_kind: AISemanticKind | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewQueueResponse:
    if claim_id is not None and get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    if review_status == "all":
        parsed_review_status = None
    else:
        try:
            parsed_review_status = AIReviewStatus(review_status)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid review status") from exc
    items, total = list_review_queue(
        db,
        organization_id=current_user.organization_id,
        claim_id=claim_id,
        document_id=document_id,
        human_status=parsed_review_status,
        semantic_kind=semantic_kind,
        limit=limit,
        offset=offset,
    )
    return ReviewQueueResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/groups", response_model=ReviewGroupQueueResponse)
def review_groups(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    claim_id: UUID | None = None,
    document_id: UUID | None = None,
    review_status: str = "pending",
    attention_only: bool = False,
    limit_groups: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ReviewGroupQueueResponse:
    if claim_id is not None and get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    if review_status == "all":
        parsed_status = None
    else:
        try:
            parsed_status = AIReviewStatus(review_status)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid review status") from exc
    groups = list_review_groups(
        db,
        organization_id=current_user.organization_id,
        claim_id=claim_id,
        document_id=document_id,
        human_status=parsed_status,
        attention_only=attention_only,
        limit_groups=limit_groups,
    )
    return ReviewGroupQueueResponse(
        groups=groups,
        total_groups=len(groups),
        total_extractions=sum(len(group.items) for group in groups),
        attention_groups=sum(1 for group in groups if group.needs_attention),
    )


@router.post("/groups/review", response_model=GroupReviewResponse)
def review_group(
    payload: GroupReviewRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> GroupReviewResponse:
    extractions = []
    for extraction_id in payload.extraction_ids:
        extraction = get_extraction_for_tenant(db, extraction_id=extraction_id, organization_id=current_user.organization_id)
        if extraction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI extraction not found")
        if extraction.human_status != AIReviewStatus.PENDING:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Grouped review only accepts pending extraction fields.")
        extractions.append(extraction)
    try:
        validate_same_review_group(extractions)
        if payload.action == "approve" and any(not row.source_verified for row in extractions) and not (payload.reason or "").strip():
            raise ValueError("A reason is required when grouped approval contains an unverified source citation.")
        reviewed: list[ReviewResult] = []
        for extraction in extractions:
            extraction, fact, promoted = review_extraction(
                db,
                extraction=extraction,
                reviewer=current_user,
                action=payload.action,
                reason=payload.reason,
            )
            reviewed.append(ReviewResult(
                extraction_id=extraction.id,
                human_status=extraction.human_status,
                approved_value=extraction.approved_value,
                promoted=promoted,
                claim_fact=ClaimFactResponse.model_validate(fact) if fact else None,
            ))
        record_active_event(
            db,
            organization_id=current_user.organization_id,
            claim_id=extractions[0].claim_id,
            user_id=current_user.id,
            event_type="ai_review_approved" if payload.action == "approve" else "ai_review_rejected",
            entity_type="review_group",
            event_data={"count": len(extractions), "grouped": True},
        )
        db.commit()
        return GroupReviewResponse(reviewed=reviewed)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{extraction_id}", response_model=ExtractionReviewDetail)
def review_detail(
    extraction_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ExtractionReviewDetail:
    extraction = get_extraction_for_tenant(db, extraction_id=extraction_id, organization_id=current_user.organization_id)
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI extraction not found")
    items, _ = list_review_queue(
        db,
        organization_id=current_user.organization_id,
        claim_id=extraction.claim_id,
        document_id=extraction.document_id,
        human_status=None,
        limit=500,
    )
    item = next((candidate for candidate in items if candidate.extraction_id == extraction.id), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI extraction not found")
    feedback = get_feedback_history(db, extraction_id=extraction.id, organization_id=current_user.organization_id)
    fact = get_current_claim_fact(
        db,
        claim_id=extraction.claim_id,
        field_path=extraction.field_path,
        organization_id=current_user.organization_id,
    )
    return ExtractionReviewDetail(
        item=item,
        feedback=[_feedback_response(db, row) for row in feedback],
        current_claim_fact=ClaimFactResponse.model_validate(fact) if fact else None,
    )


@router.get("/{extraction_id}/source", response_model=SourcePreviewResponse)
def source_preview(
    extraction_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> SourcePreviewResponse:
    extraction = get_extraction_for_tenant(db, extraction_id=extraction_id, organization_id=current_user.organization_id)
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI extraction not found")
    document = db.scalar(
        select(Document).where(
            Document.id == extraction.document_id,
            Document.organization_id == current_user.organization_id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    segment = get_source_segment_for_extraction(db, extraction=extraction, organization_id=current_user.organization_id)
    return SourcePreviewResponse(
        extraction_id=extraction.id,
        claim_id=extraction.claim_id,
        document_id=extraction.document_id,
        document_name=document.original_filename,
        field_path=extraction.field_path,
        source_locator_type=extraction.source_locator_type,
        source_locator_value=extraction.source_locator_value,
        source_quote=extraction.source_quote,
        source_verified=extraction.source_verified,
        segment_id=segment.id if segment else None,
        segment_text=segment.text if segment else None,
    )


@router.post("/{extraction_id}", response_model=ReviewResult)
def review_one(
    extraction_id: UUID,
    payload: ReviewRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ReviewResult:
    extraction = get_extraction_for_tenant(db, extraction_id=extraction_id, organization_id=current_user.organization_id)
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI extraction not found")
    try:
        extraction, fact, promoted = review_extraction(
            db,
            extraction=extraction,
            reviewer=current_user,
            action=payload.action,
            value=payload.value,
            reason=payload.reason,
        )
        event_type = {"approve": "ai_review_approved", "edit": "ai_review_edited", "reject": "ai_review_rejected"}[payload.action]
        record_active_event(
            db,
            organization_id=current_user.organization_id,
            claim_id=extraction.claim_id,
            user_id=current_user.id,
            event_type=event_type,
            entity_type="document_extraction",
            entity_id=extraction.id,
            event_data={"count": 1, "promoted": promoted},
        )
        db.commit()
        db.refresh(extraction)
        if fact is not None:
            db.refresh(fact)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ReviewResult(
        extraction_id=extraction.id,
        human_status=extraction.human_status,
        approved_value=extraction.approved_value,
        promoted=promoted,
        claim_fact=ClaimFactResponse.model_validate(fact) if fact else None,
    )


@router.post("/bulk/approve", response_model=BulkApproveResponse)
def bulk_approve(
    payload: BulkApproveRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> BulkApproveResponse:
    # Validate the complete batch before mutating anything. Bulk review is intentionally
    # all-or-nothing so a reviewer never mistakes a partial approval for a full one.
    extractions = []
    for extraction_id in payload.extraction_ids:
        extraction = get_extraction_for_tenant(db, extraction_id=extraction_id, organization_id=current_user.organization_id)
        if extraction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI extraction not found")
        if not is_bulk_approvable(extraction):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Extraction {extraction.id} is not eligible for bulk approval.",
            )
        extractions.append(extraction)

    reviewed: list[ReviewResult] = []
    try:
        for extraction in extractions:
            extraction, fact, promoted = review_extraction(
                db,
                extraction=extraction,
                reviewer=current_user,
                action="approve",
                reason=payload.reason,
            )
            reviewed.append(
                ReviewResult(
                    extraction_id=extraction.id,
                    human_status=extraction.human_status,
                    approved_value=extraction.approved_value,
                    promoted=promoted,
                    claim_fact=ClaimFactResponse.model_validate(fact) if fact else None,
                )
            )
        if extractions:
            record_active_event(
                db,
                organization_id=current_user.organization_id,
                claim_id=extractions[0].claim_id,
                user_id=current_user.id,
                event_type="ai_review_approved",
                entity_type="bulk_review",
                event_data={"count": len(extractions), "bulk": True},
            )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return BulkApproveResponse(reviewed=reviewed)
