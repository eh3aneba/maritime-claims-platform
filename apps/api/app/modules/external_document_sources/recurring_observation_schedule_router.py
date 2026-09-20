from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import (
    CurrentAuthContext,
    enforce_current_mfa_for_context,
)
from app.modules.external_document_sources.connection_authorization_router import router
from app.modules.users.models import User, UserRole
from app.modules.external_document_sources.recurring_observation_schedule_schemas import (
    ExternalDocumentSourceRecurringObservationScheduleDisableRequest,
    ExternalDocumentSourceRecurringObservationScheduleRead,
    ExternalDocumentSourceRecurringObservationScheduleReceiptRead,
    ExternalDocumentSourceRecurringObservationScheduleRequest,
)
from app.modules.external_document_sources.recurring_observation_schedule_service import (
    authorize_recurring_observation_schedule,
    disable_recurring_observation_schedule,
    get_active_recurring_observation_schedule,
    get_recurring_observation_schedule,
    list_recurring_observation_schedule_receipts,
    replace_recurring_observation_schedule,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)


def require_recurring_observation_admin_current_mfa(
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


RecurringObservationAdminMfa = Annotated[
    User,
    Depends(require_recurring_observation_admin_current_mfa),
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
    "/profiles/{profile_id}/evidence-family-bindings/{binding_id}/recurring-observation-schedules",
    response_model=ExternalDocumentSourceRecurringObservationScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_recurring_observation_schedule_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    payload: ExternalDocumentSourceRecurringObservationScheduleRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringObservationAdminMfa,
) -> ExternalDocumentSourceRecurringObservationScheduleRead:
    try:
        schedule, _outcome = authorize_recurring_observation_schedule(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorized_by_id=current_user.id,
            request_key=payload.request_key,
            reason=payload.reason,
            cadence_class=payload.cadence_class,
            effective_at=payload.effective_at,
        )
        return ExternalDocumentSourceRecurringObservationScheduleRead.model_validate(
            schedule
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


@router.post(
    "/profiles/{profile_id}/recurring-observation-schedules/{schedule_id}/replace",
    response_model=ExternalDocumentSourceRecurringObservationScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def replace_recurring_observation_schedule_endpoint(
    profile_id: UUID,
    schedule_id: UUID,
    payload: ExternalDocumentSourceRecurringObservationScheduleRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringObservationAdminMfa,
) -> ExternalDocumentSourceRecurringObservationScheduleRead:
    try:
        schedule, _outcome = replace_recurring_observation_schedule(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            schedule_id=schedule_id,
            actor_id=current_user.id,
            request_key=payload.request_key,
            reason=payload.reason,
            cadence_class=payload.cadence_class,
            effective_at=payload.effective_at,
        )
        return ExternalDocumentSourceRecurringObservationScheduleRead.model_validate(
            schedule
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


@router.post(
    "/profiles/{profile_id}/recurring-observation-schedules/{schedule_id}/disable",
    response_model=ExternalDocumentSourceRecurringObservationScheduleRead,
)
def disable_recurring_observation_schedule_endpoint(
    profile_id: UUID,
    schedule_id: UUID,
    payload: ExternalDocumentSourceRecurringObservationScheduleDisableRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringObservationAdminMfa,
) -> ExternalDocumentSourceRecurringObservationScheduleRead:
    try:
        schedule, _outcome = disable_recurring_observation_schedule(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            schedule_id=schedule_id,
            actor_id=current_user.id,
            request_key=payload.request_key,
            reason=payload.reason,
        )
        return ExternalDocumentSourceRecurringObservationScheduleRead.model_validate(
            schedule
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
    "/profiles/{profile_id}/recurring-observation-schedules/{schedule_id}",
    response_model=ExternalDocumentSourceRecurringObservationScheduleRead,
)
def get_recurring_observation_schedule_endpoint(
    profile_id: UUID,
    schedule_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringObservationAdminMfa,
) -> ExternalDocumentSourceRecurringObservationScheduleRead:
    try:
        schedule = get_recurring_observation_schedule(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            schedule_id=schedule_id,
        )
        return ExternalDocumentSourceRecurringObservationScheduleRead.model_validate(
            schedule
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
    "/profiles/{profile_id}/evidence-family-bindings/{binding_id}/recurring-observation-schedules/active",
    response_model=ExternalDocumentSourceRecurringObservationScheduleRead | None,
)
def get_active_recurring_observation_schedule_endpoint(
    profile_id: UUID,
    binding_id: UUID,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringObservationAdminMfa,
) -> ExternalDocumentSourceRecurringObservationScheduleRead | None:
    try:
        schedule = get_active_recurring_observation_schedule(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
        )
        if schedule is None:
            response.status_code = status.HTTP_200_OK
            return None
        return ExternalDocumentSourceRecurringObservationScheduleRead.model_validate(
            schedule
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
    "/profiles/{profile_id}/recurring-observation-schedules/{schedule_id}/receipts",
    response_model=list[ExternalDocumentSourceRecurringObservationScheduleReceiptRead],
)
def list_recurring_observation_schedule_receipts_endpoint(
    profile_id: UUID,
    schedule_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RecurringObservationAdminMfa,
) -> list[ExternalDocumentSourceRecurringObservationScheduleReceiptRead]:
    try:
        rows = list_recurring_observation_schedule_receipts(
            db,
            organization_id=current_user.organization_id,
            profile_id=profile_id,
            schedule_id=schedule_id,
        )
        return [
            ExternalDocumentSourceRecurringObservationScheduleReceiptRead.model_validate(
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
