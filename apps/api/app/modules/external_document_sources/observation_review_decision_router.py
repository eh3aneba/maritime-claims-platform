from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import (
    CurrentAuthContext,
    enforce_current_mfa_for_context,
)
from app.modules.external_document_sources.connection_authorization_router import router
from app.modules.external_document_sources.observation_review_decision_schemas import (
    ExternalDocumentSourceObservationRefreshAuthorizationRead,
    ExternalDocumentSourceObservationReviewDecisionRead,
    ExternalDocumentSourceObservationReviewDecisionReceiptRead,
    ExternalDocumentSourceObservationReviewDecisionRequest,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
    get_observation_refresh_authorization_for_decision,
    get_observation_review_decision,
    list_observation_review_decision_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.users.models import User, UserRole


def require_observation_review_admin_current_mfa(
    context: CurrentAuthContext,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if context.user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    enforce_current_mfa_for_context(db, context=context)
    return context.user


ObservationReviewAdminMfa = Annotated[
    User,
    Depends(require_observation_review_admin_current_mfa),
]


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ExternalDocumentSourceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ExternalDocumentSourceValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    ) from exc


@router.post(
    "/profiles/{profile_id}/observation-review-handoffs/{handoff_id}/decisions",
    response_model=ExternalDocumentSourceObservationReviewDecisionRead,
    status_code=status.HTTP_201_CREATED,
)
def decide_observation_review_handoff_endpoint(
    profile_id: UUID,
    handoff_id: UUID,
    payload: ExternalDocumentSourceObservationReviewDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationReviewAdminMfa,
) -> ExternalDocumentSourceObservationReviewDecisionRead:
    try:
        decision, _authorization, _outcome = decide_observation_review_handoff(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=current_user.id,
            request_key=payload.request_key,
            decision_kind=payload.decision_kind,
            decision_reason=payload.reason,
        )
        return ExternalDocumentSourceObservationReviewDecisionRead.model_validate(
            decision
        )
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/observation-review-decisions/{decision_id}",
    response_model=ExternalDocumentSourceObservationReviewDecisionRead,
)
def get_observation_review_decision_endpoint(
    profile_id: UUID,
    decision_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationReviewAdminMfa,
) -> ExternalDocumentSourceObservationReviewDecisionRead:
    try:
        decision = get_observation_review_decision(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            decision_id=decision_id,
        )
        return ExternalDocumentSourceObservationReviewDecisionRead.model_validate(
            decision
        )
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/observation-review-decisions/{decision_id}/receipts",
    response_model=list[ExternalDocumentSourceObservationReviewDecisionReceiptRead],
)
def list_observation_review_decision_receipts_endpoint(
    profile_id: UUID,
    decision_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationReviewAdminMfa,
) -> list[ExternalDocumentSourceObservationReviewDecisionReceiptRead]:
    try:
        rows = list_observation_review_decision_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            decision_id=decision_id,
        )
        return [
            ExternalDocumentSourceObservationReviewDecisionReceiptRead.model_validate(
                row
            )
            for row in rows
        ]
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)


@router.get(
    "/profiles/{profile_id}/observation-review-decisions/{decision_id}/refresh-authorization",
    response_model=ExternalDocumentSourceObservationRefreshAuthorizationRead | None,
)
def get_observation_refresh_authorization_endpoint(
    profile_id: UUID,
    decision_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: ObservationReviewAdminMfa,
) -> ExternalDocumentSourceObservationRefreshAuthorizationRead | None:
    try:
        authorization = get_observation_refresh_authorization_for_decision(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            decision_id=decision_id,
        )
        if authorization is None:
            return None
        return ExternalDocumentSourceObservationRefreshAuthorizationRead.model_validate(
            authorization
        )
    except (
        ExternalDocumentSourceValidationError,
        ExternalDocumentSourceConflictError,
        ExternalDocumentSourceNotFoundError,
        IntegrityError,
        ValueError,
    ) as exc:
        db.rollback()
        _raise_service_error(exc)
