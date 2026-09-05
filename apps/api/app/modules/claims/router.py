from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.models import ClaimPriority, ClaimStatus
from app.modules.claims.reserve_lineage import (
    ReserveLineageError,
    record_authoritative_reserve,
    reserve_history_response,
)
from app.modules.claims.schemas import (
    ClaimAssign,
    ClaimCreate,
    ClaimFactListResponse,
    ClaimFactRead,
    ClaimListResponse,
    ClaimRead,
    ClaimReserveChange,
    ClaimStatusChange,
    ClaimUpdate,
    ReserveHistoryResponse,
)
from app.modules.claims.service import (
    ClaimNotFoundError,
    ClaimPermissionError,
    ClaimValidationError,
    InvalidStatusTransitionError,
    assign_claim,
    change_claim_status,
    create_claim,
    get_claim,
    list_claims,
    list_claim_facts,
    update_claim_details,
)
from app.modules.rules.service import evaluate_claim_rules
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claims", tags=["claims"])


def _read(claim) -> ClaimRead:
    return ClaimRead.model_validate(claim)


@router.post("", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
def create_claim_endpoint(
    payload: ClaimCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimRead:
    try:
        claim = create_claim(
            db,
            organization_id=current_user.organization_id,
            current_user=current_user,
            payload=payload,
        )
    except ClaimPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ClaimValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="CREATE_CLAIM",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "claim_reference": claim.claim_reference,
            "vessel_id": str(claim.vessel_id),
            "status": claim.status.value,
            "priority": claim.priority.value,
        },
    )
    db.commit()
    return _read(claim)


@router.get("", response_model=ClaimListResponse)
def list_claims_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    claim_status: Annotated[ClaimStatus | None, Query(alias="status")] = None,
    priority: ClaimPriority | None = None,
    vessel_id: UUID | None = None,
    handler_id: UUID | None = None,
    incident_from: date | None = None,
    incident_to: date | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClaimListResponse:
    if incident_from and incident_to and incident_from > incident_to:
        raise HTTPException(status_code=422, detail="incident_from cannot be after incident_to")
    claims, total = list_claims(
        db,
        organization_id=current_user.organization_id,
        status=claim_status,
        priority=priority,
        vessel_id=vessel_id,
        handler_id=handler_id,
        incident_from=incident_from,
        incident_to=incident_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ClaimListResponse(
        items=[ClaimRead.model_validate(claim) for claim in claims],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{claim_id}", response_model=ClaimRead)
def get_claim_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimRead:
    try:
        claim = get_claim(db, claim_id=claim_id, organization_id=current_user.organization_id)
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    return _read(claim)


@router.get("/{claim_id}/facts", response_model=ClaimFactListResponse)
def list_claim_facts_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimFactListResponse:
    try:
        facts = list_claim_facts(db, claim_id=claim_id, organization_id=current_user.organization_id)
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    return ClaimFactListResponse(items=[ClaimFactRead.model_validate(fact) for fact in facts], total=len(facts))


@router.patch("/{claim_id}", response_model=ClaimRead)
def update_claim_endpoint(
    claim_id: UUID,
    payload: ClaimUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimRead:
    try:
        claim = get_claim(db, claim_id=claim_id, organization_id=current_user.organization_id)
        claim, old_values, new_values = update_claim_details(
            db,
            claim=claim,
            organization_id=current_user.organization_id,
            payload=payload,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    except ClaimValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    if new_values:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="UPDATE_CLAIM",
            entity_type="claim",
            entity_id=claim.id,
            old_values=old_values,
            new_values=new_values,
        )
    db.commit()
    return _read(claim)


@router.post("/{claim_id}/assign", response_model=ClaimRead)
def assign_claim_endpoint(
    claim_id: UUID,
    payload: ClaimAssign,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))],
) -> ClaimRead:
    try:
        claim = get_claim(db, claim_id=claim_id, organization_id=current_user.organization_id)
        claim, old_handler_id = assign_claim(
            db,
            claim=claim,
            organization_id=current_user.organization_id,
            handler_id=payload.handler_id,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    except ClaimValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="ASSIGN_CLAIM",
        entity_type="claim",
        entity_id=claim.id,
        old_values={"handler_id": str(old_handler_id) if old_handler_id else None},
        new_values={"handler_id": str(claim.handler_id) if claim.handler_id else None},
    )
    db.commit()
    return _read(claim)


@router.post("/{claim_id}/status", response_model=ClaimRead)
def change_claim_status_endpoint(
    claim_id: UUID,
    payload: ClaimStatusChange,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ClaimRead:
    try:
        claim = get_claim(db, claim_id=claim_id, organization_id=current_user.organization_id)
        old_status = change_claim_status(db, claim=claim, new_status=payload.status, current_user=current_user)
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ClaimPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if old_status != claim.status:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="CHANGE_CLAIM_STATUS",
            entity_type="claim",
            entity_id=claim.id,
            old_values={"status": old_status.value},
            new_values={"status": claim.status.value},
            details=payload.reason,
        )
    db.commit()
    if old_status != claim.status:
        evaluate_claim_rules(db, claim=claim, user=current_user, trigger="status_change")
    return _read(claim)


@router.get("/{claim_id}/reserve-history", response_model=ReserveHistoryResponse)
def reserve_history_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> ReserveHistoryResponse:
    try:
        claim = get_claim(db, claim_id=claim_id, organization_id=current_user.organization_id)
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    return ReserveHistoryResponse.model_validate(reserve_history_response(db, claim=claim))


@router.post("/{claim_id}/reserve", response_model=ClaimRead)
def change_reserve_endpoint(
    claim_id: UUID,
    payload: ClaimReserveChange,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))],
) -> ClaimRead:
    """Append one versioned authoritative human reserve change."""
    try:
        claim = get_claim(db, claim_id=claim_id, organization_id=current_user.organization_id)
        locked_claim, _entry, replayed = record_authoritative_reserve(
            db,
            claim=claim,
            user=current_user,
            payload=payload,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found") from exc
    except ReserveLineageError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not replayed:
        db.commit()
    return _read(locked_claim)
