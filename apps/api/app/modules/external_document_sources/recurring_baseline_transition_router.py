from __future__ import annotations

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
from app.modules.external_document_sources.recurring_baseline_transition_schemas import (
    ExternalDocumentSourceRecurringBaselineTransitionRead,
    ExternalDocumentSourceRecurringBaselineTransitionReceiptRead,
    ExternalDocumentSourceRecurringBaselineTransitionRequest,
)
from app.modules.external_document_sources.recurring_baseline_transition_service import (
    establish_recurring_baseline_transition,
    get_recurring_baseline_transition,
    list_recurring_baseline_transition_receipts,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.users.models import User, UserRole


def require_recurring_baseline_admin_current_mfa(
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


RecurringBaselineAdminMfa = Annotated[
    User,
    Depends(require_recurring_baseline_admin_current_mfa),
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
    "/profiles/{profile_id}/observation-refresh-admission-executions/"
    "{execution_id}/recurring-baseline-transition",
    response_model=ExternalDocumentSourceRecurringBaselineTransitionRead,
    status_code=status.HTTP_201_CREATED,
)
def establish_recurring_baseline_transition_endpoint(
    profile_id: UUID,
    execution_id: UUID,
    payload: ExternalDocumentSourceRecurringBaselineTransitionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringBaselineAdminMfa,
) -> ExternalDocumentSourceRecurringBaselineTransitionRead:
    try:
        transition, _outcome = establish_recurring_baseline_transition(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=execution_id,
            authorized_by_id=current_user.id,
            request_key=payload.request_key,
            reason=payload.reason,
        )
        return ExternalDocumentSourceRecurringBaselineTransitionRead.model_validate(
            transition
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
    "/profiles/{profile_id}/recurring-baseline-transitions/{transition_id}",
    response_model=ExternalDocumentSourceRecurringBaselineTransitionRead,
)
def get_recurring_baseline_transition_endpoint(
    profile_id: UUID,
    transition_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringBaselineAdminMfa,
) -> ExternalDocumentSourceRecurringBaselineTransitionRead:
    try:
        transition = get_recurring_baseline_transition(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            transition_id=transition_id,
        )
        return ExternalDocumentSourceRecurringBaselineTransitionRead.model_validate(
            transition
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
    "/profiles/{profile_id}/recurring-baseline-transitions/"
    "{transition_id}/receipts",
    response_model=list[ExternalDocumentSourceRecurringBaselineTransitionReceiptRead],
)
def list_recurring_baseline_transition_receipts_endpoint(
    profile_id: UUID,
    transition_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringBaselineAdminMfa,
) -> list[ExternalDocumentSourceRecurringBaselineTransitionReceiptRead]:
    try:
        rows = list_recurring_baseline_transition_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            transition_id=transition_id,
        )
        return [
            ExternalDocumentSourceRecurringBaselineTransitionReceiptRead.model_validate(
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
