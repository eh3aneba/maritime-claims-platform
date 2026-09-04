from typing import Annotated
from uuid import UUID

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.rules.service import evaluate_claim_rules
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.modules.claims.schemas import ClaimRead
from app.modules.claims.service import ClaimPermissionError, ClaimValidationError
from app.modules.intake.maturity import retry_failed_intake_draft
from app.modules.intake.schemas import (
    ClaimIntakeApprovalResult,
    ClaimIntakeApprove,
    ClaimIntakeDocumentTypeRegistry,
    ClaimIntakeDraftList,
    ClaimIntakeDraftRead,
    ClaimIntakeReject,
)
from app.modules.intake.service import (
    ClaimIntakeNotFoundError,
    ClaimIntakeStateError,
    approve_intake_draft,
    create_intake_draft,
    get_intake_draft,
    list_intake_drafts,
    reject_intake_draft,
)

router = APIRouter(prefix="/claim-intake", tags=["claim-intake"])


@router.get("/document-types", response_model=ClaimIntakeDocumentTypeRegistry)
def intake_document_types(_current_user: CurrentUser) -> ClaimIntakeDocumentTypeRegistry:
    return ClaimIntakeDocumentTypeRegistry.current()


@router.post("/drafts", response_model=ClaimIntakeDraftRead, status_code=status.HTTP_202_ACCEPTED)
async def upload_intake_draft(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    file: Annotated[UploadFile, File(...)],
) -> ClaimIntakeDraftRead:
    draft = await create_intake_draft(db, upload=file, current_user=current_user)
    return ClaimIntakeDraftRead.model_validate(draft)


@router.get("/drafts", response_model=ClaimIntakeDraftList)
def list_intake_drafts_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimIntakeDraftList:
    items, total = list_intake_drafts(db, organization_id=current_user.organization_id)
    return ClaimIntakeDraftList(
        items=[ClaimIntakeDraftRead.model_validate(item) for item in items],
        total=total,
    )


@router.get("/drafts/{draft_id}", response_model=ClaimIntakeDraftRead)
def get_intake_draft_endpoint(
    draft_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimIntakeDraftRead:
    try:
        draft = get_intake_draft(
            db,
            draft_id=draft_id,
            organization_id=current_user.organization_id,
        )
    except ClaimIntakeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Claim intake draft not found") from exc
    return ClaimIntakeDraftRead.model_validate(draft)


@router.post("/drafts/{draft_id}/retry", response_model=ClaimIntakeDraftRead, status_code=status.HTTP_202_ACCEPTED)
def retry_intake_draft_endpoint(
    draft_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimIntakeDraftRead:
    try:
        draft = retry_failed_intake_draft(
            db,
            draft_id=draft_id,
            organization_id=current_user.organization_id,
            current_user=current_user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Claim intake draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ClaimIntakeDraftRead.model_validate(draft)


@router.post("/drafts/{draft_id}/approve", response_model=ClaimIntakeApprovalResult)
def approve_intake_draft_endpoint(
    draft_id: UUID,
    payload: ClaimIntakeApprove,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimIntakeApprovalResult:
    try:
        draft, claim = approve_intake_draft(
            db,
            draft_id=draft_id,
            organization_id=current_user.organization_id,
            current_user=current_user,
            payload=payload,
        )
    except ClaimIntakeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Claim intake draft not found") from exc
    except ClaimIntakeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ClaimPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ClaimValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    evaluate_claim_rules(db, claim=claim, user=current_user, trigger="claim_created")
    return ClaimIntakeApprovalResult(
        draft=ClaimIntakeDraftRead.model_validate(draft),
        claim=ClaimRead.model_validate(claim),
    )


@router.post("/drafts/{draft_id}/reject", response_model=ClaimIntakeDraftRead)
def reject_intake_draft_endpoint(
    draft_id: UUID,
    payload: ClaimIntakeReject,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimIntakeDraftRead:
    try:
        draft = get_intake_draft(
            db,
            draft_id=draft_id,
            organization_id=current_user.organization_id,
        )
        draft = reject_intake_draft(
            db,
            draft=draft,
            current_user=current_user,
            reason=payload.reason,
        )
    except ClaimIntakeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Claim intake draft not found") from exc
    except ClaimIntakeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ClaimIntakeDraftRead.model_validate(draft)
