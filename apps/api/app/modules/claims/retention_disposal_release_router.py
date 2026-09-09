from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_disposal_release_schemas import (
    DisposalReleaseReviewDecision,
    DisposalReleaseReviewRead,
    DisposalReleaseReviewRequest,
)
from app.modules.claims.retention_disposal_release_service import (
    DisposalReleasePreflightError,
    approve_disposal_release_review,
    cancel_disposal_release_review,
    get_disposal_release_review,
    list_disposal_release_reviews,
    reject_disposal_release_review,
    request_disposal_release_review,
)
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter(tags=["retention"])


def _read(review) -> DisposalReleaseReviewRead:
    return DisposalReleaseReviewRead.model_validate(review)


def _audit_values(review) -> dict:
    return {
        "claim_id": str(review.claim_id),
        "disposal_quarantine_stage_id": str(review.disposal_quarantine_stage_id),
        "disposal_dry_run_ceremony_id": str(review.disposal_dry_run_ceremony_id),
        "disposal_execution_manifest_id": str(review.disposal_execution_manifest_id),
        "disposal_authorization_id": str(review.disposal_authorization_id),
        "status": review.status,
        "manifest_hash": review.manifest_hash,
        "inventory_hash": review.inventory_hash,
        "ceremony_hash": review.ceremony_hash,
        "attestation_hash": review.attestation_hash,
        "overlay_hash": review.overlay_hash,
        "stage_hash": review.stage_hash,
        "release_snapshot_hash": review.release_snapshot_hash,
        "review_hash": review.review_hash,
        "approval_hash": review.approval_hash,
        "document_count": review.document_count,
        "total_file_size_bytes": review.total_file_size_bytes,
        "minimum_release_eligible_at": review.minimum_release_eligible_at.isoformat(),
        "review_expires_at": review.review_expires_at.isoformat(),
        "terminal_reason": review.terminal_reason,
        "storage_identifiers_raw_logged": False,
        "logical_overlay_only": True,
        "physical_quarantine_performed": False,
        "execution_authority_created": False,
        "destructive_action_performed": False,
    }


@router.post(
    "/{claim_id}/disposal-quarantine-stages/{stage_id}/release-review",
    response_model=DisposalReleaseReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def request_release_review_endpoint(
    claim_id: UUID,
    stage_id: UUID,
    payload: DisposalReleaseReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalReleaseReviewRead:
    try:
        review = request_disposal_release_review(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            stage_id=stage_id,
            requested_by_id=current_user.id,
            request_reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_RELEASE_REVIEW_REQUESTED",
            entity_type="disposal_release_review",
            entity_id=review.id,
            new_values=_audit_values(review),
        )
        db.commit()
        db.refresh(review)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DisposalReleasePreflightError as exc:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_RELEASE_REVIEW_PREFLIGHT_FAILED",
            entity_type="disposal_quarantine_stage",
            entity_id=exc.stage_id,
            new_values={
                "claim_id": str(claim_id),
                "outcome": exc.outcome,
                "blocking_reasons": exc.blocking_reasons,
                "stage_state_changed": exc.stage_state_changed,
                "execution_authority_created": False,
                "physical_quarantine_performed": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "disposal_release_review_preflight_failed",
                "outcome": exc.outcome,
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(review)


@router.get(
    "/{claim_id}/disposal-release-reviews",
    response_model=list[DisposalReleaseReviewRead],
)
def list_release_reviews_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[DisposalReleaseReviewRead]:
    try:
        reviews = list_disposal_release_reviews(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_read(item) for item in reviews]


@router.get(
    "/{claim_id}/disposal-release-reviews/{review_id}",
    response_model=DisposalReleaseReviewRead,
)
def get_release_review_endpoint(
    claim_id: UUID,
    review_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> DisposalReleaseReviewRead:
    try:
        review = get_disposal_release_review(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            review_id=review_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(review)


@router.post(
    "/{claim_id}/disposal-release-reviews/{review_id}/approve",
    response_model=DisposalReleaseReviewRead,
)
def approve_release_review_endpoint(
    claim_id: UUID,
    review_id: UUID,
    payload: DisposalReleaseReviewDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalReleaseReviewRead:
    try:
        review, outcome = approve_disposal_release_review(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            review_id=review_id,
            approved_by_id=current_user.id,
            approval_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = {
                "approved": "DISPOSAL_RELEASE_REVIEW_APPROVED",
                "invalidated": "DISPOSAL_RELEASE_REVIEW_INVALIDATED",
                "expired": "DISPOSAL_RELEASE_REVIEW_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_release_review",
                entity_id=review.id,
                new_values=_audit_values(review),
            )
            db.commit()
            db.refresh(review)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(review)


@router.post(
    "/{claim_id}/disposal-release-reviews/{review_id}/reject",
    response_model=DisposalReleaseReviewRead,
)
def reject_release_review_endpoint(
    claim_id: UUID,
    review_id: UUID,
    payload: DisposalReleaseReviewDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalReleaseReviewRead:
    try:
        review, outcome = reject_disposal_release_review(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            review_id=review_id,
            rejected_by_id=current_user.id,
            rejection_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = (
                "DISPOSAL_RELEASE_REVIEW_REJECTED"
                if outcome == "rejected"
                else "DISPOSAL_RELEASE_REVIEW_EXPIRED"
            )
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_release_review",
                entity_id=review.id,
                new_values=_audit_values(review),
            )
            db.commit()
            db.refresh(review)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(review)


@router.post(
    "/{claim_id}/disposal-release-reviews/{review_id}/cancel",
    response_model=DisposalReleaseReviewRead,
)
def cancel_release_review_endpoint(
    claim_id: UUID,
    review_id: UUID,
    payload: DisposalReleaseReviewDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalReleaseReviewRead:
    try:
        review, outcome = cancel_disposal_release_review(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            review_id=review_id,
            cancelled_by_id=current_user.id,
            cancellation_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = (
                "DISPOSAL_RELEASE_REVIEW_CANCELLED"
                if outcome == "cancelled"
                else "DISPOSAL_RELEASE_REVIEW_EXPIRED"
            )
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_release_review",
                entity_id=review.id,
                new_values=_audit_values(review),
            )
            db.commit()
            db.refresh(review)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(review)
