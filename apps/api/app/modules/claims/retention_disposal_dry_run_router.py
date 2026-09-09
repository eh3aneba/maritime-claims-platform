from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_disposal_dry_run_schemas import (
    DisposalDryRunCeremonyDecision,
    DisposalDryRunCeremonyOpen,
    DisposalDryRunCeremonyRead,
)
from app.modules.claims.retention_disposal_dry_run_service import (
    DisposalDryRunPreflightError,
    attest_disposal_dry_run_ceremony,
    cancel_disposal_dry_run_ceremony,
    get_disposal_dry_run_ceremony,
    list_disposal_dry_run_ceremonies,
    open_disposal_dry_run_ceremony,
)
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter(tags=["retention"])


def _read(ceremony) -> DisposalDryRunCeremonyRead:
    return DisposalDryRunCeremonyRead.model_validate(ceremony)


def _audit_values(ceremony) -> dict:
    return {
        "claim_id": str(ceremony.claim_id),
        "disposal_execution_manifest_id": str(ceremony.disposal_execution_manifest_id),
        "disposal_authorization_id": str(ceremony.disposal_authorization_id),
        "status": ceremony.status,
        "manifest_hash": ceremony.manifest_hash,
        "inventory_hash": ceremony.inventory_hash,
        "plan_hash": ceremony.plan_hash,
        "ceremony_hash": ceremony.ceremony_hash,
        "document_count": ceremony.document_count,
        "total_file_size_bytes": ceremony.total_file_size_bytes,
        "ceremony_expires_at": ceremony.ceremony_expires_at.isoformat(),
        "attestation_hash": ceremony.attestation_hash,
        "terminal_reason": ceremony.terminal_reason,
        "storage_identifiers_raw_logged": False,
        "execution_authority_created": False,
        "destructive_action_performed": False,
    }


@router.post(
    "/{claim_id}/disposal-execution-manifests/{manifest_id}/dry-run-ceremony",
    response_model=DisposalDryRunCeremonyRead,
    status_code=status.HTTP_201_CREATED,
)
def open_dry_run_ceremony_endpoint(
    claim_id: UUID,
    manifest_id: UUID,
    payload: DisposalDryRunCeremonyOpen,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalDryRunCeremonyRead:
    try:
        ceremony = open_disposal_dry_run_ceremony(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            manifest_id=manifest_id,
            created_by_id=current_user.id,
            opening_reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_DRY_RUN_CEREMONY_OPENED",
            entity_type="disposal_dry_run_ceremony",
            entity_id=ceremony.id,
            new_values=_audit_values(ceremony),
        )
        db.commit()
        db.refresh(ceremony)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DisposalDryRunPreflightError as exc:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_DRY_RUN_CEREMONY_PREFLIGHT_FAILED",
            entity_type="disposal_execution_manifest",
            entity_id=exc.manifest_id,
            new_values={
                "claim_id": str(claim_id),
                "outcome": exc.outcome,
                "blocking_reasons": exc.blocking_reasons,
                "manifest_state_changed": exc.manifest_state_changed,
                "execution_authority_created": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "disposal_dry_run_preflight_failed",
                "outcome": exc.outcome,
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(ceremony)


@router.get(
    "/{claim_id}/disposal-dry-run-ceremonies",
    response_model=list[DisposalDryRunCeremonyRead],
)
def list_dry_run_ceremonies_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[DisposalDryRunCeremonyRead]:
    try:
        ceremonies = list_disposal_dry_run_ceremonies(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_read(item) for item in ceremonies]


@router.get(
    "/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}",
    response_model=DisposalDryRunCeremonyRead,
)
def get_dry_run_ceremony_endpoint(
    claim_id: UUID,
    ceremony_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> DisposalDryRunCeremonyRead:
    try:
        ceremony = get_disposal_dry_run_ceremony(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            ceremony_id=ceremony_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(ceremony)


@router.post(
    "/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/attest",
    response_model=DisposalDryRunCeremonyRead,
)
def attest_dry_run_ceremony_endpoint(
    claim_id: UUID,
    ceremony_id: UUID,
    payload: DisposalDryRunCeremonyDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalDryRunCeremonyRead:
    try:
        ceremony, outcome = attest_disposal_dry_run_ceremony(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            ceremony_id=ceremony_id,
            attested_by_id=current_user.id,
            attestation_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = {
                "attested": "DISPOSAL_DRY_RUN_CEREMONY_ATTESTED",
                "blocked": "DISPOSAL_DRY_RUN_CEREMONY_BLOCKED",
                "invalidated": "DISPOSAL_DRY_RUN_CEREMONY_INVALIDATED",
                "expired": "DISPOSAL_DRY_RUN_CEREMONY_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_dry_run_ceremony",
                entity_id=ceremony.id,
                old_values={"status": "pending_attestation"},
                new_values=_audit_values(ceremony),
            )
            db.commit()
            db.refresh(ceremony)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(ceremony)


@router.post(
    "/{claim_id}/disposal-dry-run-ceremonies/{ceremony_id}/cancel",
    response_model=DisposalDryRunCeremonyRead,
)
def cancel_dry_run_ceremony_endpoint(
    claim_id: UUID,
    ceremony_id: UUID,
    payload: DisposalDryRunCeremonyDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalDryRunCeremonyRead:
    try:
        ceremony, outcome = cancel_disposal_dry_run_ceremony(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            ceremony_id=ceremony_id,
            cancelled_by_id=current_user.id,
            cancellation_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = (
                "DISPOSAL_DRY_RUN_CEREMONY_CANCELLED"
                if outcome == "cancelled"
                else "DISPOSAL_DRY_RUN_CEREMONY_EXPIRED"
            )
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_dry_run_ceremony",
                entity_id=ceremony.id,
                old_values={"status": "pending_attestation"},
                new_values=_audit_values(ceremony),
            )
            db.commit()
            db.refresh(ceremony)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(ceremony)
