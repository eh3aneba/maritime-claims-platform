from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_disposal_quarantine_schemas import (
    DisposalQuarantineStageDecision,
    DisposalQuarantineStageOpen,
    DisposalQuarantineStageRead,
)
from app.modules.claims.retention_disposal_quarantine_service import (
    DisposalQuarantinePreflightError,
    cancel_disposal_quarantine_stage,
    create_disposal_quarantine_stage,
    get_disposal_quarantine_stage,
    list_disposal_quarantine_stages,
    restore_disposal_quarantine_stage,
    revalidate_disposal_quarantine_stage,
)
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter(tags=["retention"])


def _read(stage) -> DisposalQuarantineStageRead:
    return DisposalQuarantineStageRead.model_validate(stage)


def _audit_values(stage) -> dict:
    return {
        "claim_id": str(stage.claim_id),
        "disposal_dry_run_ceremony_id": str(stage.disposal_dry_run_ceremony_id),
        "disposal_execution_manifest_id": str(stage.disposal_execution_manifest_id),
        "disposal_authorization_id": str(stage.disposal_authorization_id),
        "status": stage.status,
        "manifest_hash": stage.manifest_hash,
        "inventory_hash": stage.inventory_hash,
        "ceremony_hash": stage.ceremony_hash,
        "plan_hash": stage.plan_hash,
        "attestation_hash": stage.attestation_hash,
        "overlay_hash": stage.overlay_hash,
        "stage_hash": stage.stage_hash,
        "document_count": stage.document_count,
        "total_file_size_bytes": stage.total_file_size_bytes,
        "stage_expires_at": stage.stage_expires_at.isoformat(),
        "restored_by_id": None if stage.restored_by_id is None else str(stage.restored_by_id),
        "restored_at": None if stage.restored_at is None else stage.restored_at.isoformat(),
        "terminal_reason": stage.terminal_reason,
        "logical_overlay_only": True,
        "logical_overlay_active": stage.status == "staged",
        "storage_identifiers_raw_logged": False,
        "physical_quarantine_performed": False,
        "execution_authority_created": False,
        "destructive_action_performed": False,
    }


@router.post(
    "/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/quarantine-stage",
    response_model=DisposalQuarantineStageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_quarantine_stage_endpoint(
    claim_id: UUID,
    ceremony_id: UUID,
    payload: DisposalQuarantineStageOpen,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalQuarantineStageRead:
    try:
        stage = create_disposal_quarantine_stage(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            ceremony_id=ceremony_id,
            staged_by_id=current_user.id,
            staging_reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_QUARANTINE_STAGE_CREATED",
            entity_type="disposal_quarantine_stage",
            entity_id=stage.id,
            new_values=_audit_values(stage),
        )
        db.commit()
        db.refresh(stage)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DisposalQuarantinePreflightError as exc:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_QUARANTINE_STAGE_PREFLIGHT_FAILED",
            entity_type="disposal_dry_run_ceremony",
            entity_id=exc.ceremony_id,
            new_values={
                "claim_id": str(claim_id),
                "manifest_id": None if exc.manifest_id is None else str(exc.manifest_id),
                "outcome": exc.outcome,
                "blocking_reasons": exc.blocking_reasons,
                "manifest_state_changed": exc.manifest_state_changed,
                "logical_overlay_only": True,
                "physical_quarantine_performed": False,
                "execution_authority_created": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "disposal_quarantine_preflight_failed",
                "outcome": exc.outcome,
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(stage)


@router.get(
    "/{claim_id}/disposal-quarantine-stages",
    response_model=list[DisposalQuarantineStageRead],
)
def list_quarantine_stages_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[DisposalQuarantineStageRead]:
    try:
        stages = list_disposal_quarantine_stages(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_read(item) for item in stages]


@router.get(
    "/{claim_id}/disposal-quarantine-stages/{stage_id}",
    response_model=DisposalQuarantineStageRead,
)
def get_quarantine_stage_endpoint(
    claim_id: UUID,
    stage_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> DisposalQuarantineStageRead:
    try:
        stage = get_disposal_quarantine_stage(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            stage_id=stage_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(stage)


@router.post(
    "/{claim_id}/disposal-quarantine-stages/{stage_id}/revalidate",
    response_model=DisposalQuarantineStageRead,
)
def revalidate_quarantine_stage_endpoint(
    claim_id: UUID,
    stage_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalQuarantineStageRead:
    try:
        stage, outcome = revalidate_disposal_quarantine_stage(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            stage_id=stage_id,
            actor_id=current_user.id,
        )
        if outcome != "unchanged":
            action = {
                "revalidated": "DISPOSAL_QUARANTINE_STAGE_REVALIDATED",
                "invalidated": "DISPOSAL_QUARANTINE_STAGE_INVALIDATED",
                "expired": "DISPOSAL_QUARANTINE_STAGE_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_quarantine_stage",
                entity_id=stage.id,
                new_values=_audit_values(stage),
            )
            db.commit()
            db.refresh(stage)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(stage)


@router.post(
    "/{claim_id}/disposal-quarantine-stages/{stage_id}/restore",
    response_model=DisposalQuarantineStageRead,
)
def restore_quarantine_stage_endpoint(
    claim_id: UUID,
    stage_id: UUID,
    payload: DisposalQuarantineStageDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalQuarantineStageRead:
    try:
        stage, outcome = restore_disposal_quarantine_stage(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            stage_id=stage_id,
            restored_by_id=current_user.id,
            restoration_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = {
                "restored": "DISPOSAL_QUARANTINE_STAGE_RESTORED",
                "invalidated": "DISPOSAL_QUARANTINE_STAGE_INVALIDATED",
                "expired": "DISPOSAL_QUARANTINE_STAGE_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_quarantine_stage",
                entity_id=stage.id,
                new_values=_audit_values(stage),
            )
            db.commit()
            db.refresh(stage)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(stage)


@router.post(
    "/{claim_id}/disposal-quarantine-stages/{stage_id}/cancel",
    response_model=DisposalQuarantineStageRead,
)
def cancel_quarantine_stage_endpoint(
    claim_id: UUID,
    stage_id: UUID,
    payload: DisposalQuarantineStageDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalQuarantineStageRead:
    try:
        stage, outcome = cancel_disposal_quarantine_stage(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            stage_id=stage_id,
            cancelled_by_id=current_user.id,
            cancellation_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = {
                "cancelled": "DISPOSAL_QUARANTINE_STAGE_CANCELLED",
                "invalidated": "DISPOSAL_QUARANTINE_STAGE_INVALIDATED",
                "expired": "DISPOSAL_QUARANTINE_STAGE_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_quarantine_stage",
                entity_id=stage.id,
                new_values=_audit_values(stage),
            )
            db.commit()
            db.refresh(stage)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(stage)
