from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_disposal_manifest_schemas import (
    DisposalExecutionManifestRead,
)
from app.modules.claims.retention_disposal_manifest_service import (
    DisposalManifestPreflightError,
    create_disposal_execution_manifest,
    get_disposal_execution_manifest,
    list_disposal_execution_manifests,
    revalidate_disposal_execution_manifest,
)
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter(prefix="/claims", tags=["retention"])


def _read(manifest) -> DisposalExecutionManifestRead:
    return DisposalExecutionManifestRead.model_validate(manifest)


@router.post(
    "/{claim_id}/disposal-authorizations/{authorization_id}/execution-manifest",
    response_model=DisposalExecutionManifestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_execution_manifest_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalExecutionManifestRead:
    try:
        manifest = create_disposal_execution_manifest(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_EXECUTION_MANIFEST_CREATED",
            entity_type="disposal_execution_manifest",
            entity_id=manifest.id,
            new_values={
                "claim_id": str(manifest.claim_id),
                "disposal_authorization_id": str(manifest.disposal_authorization_id),
                "status": manifest.status,
                "retention_policy_id": str(manifest.retention_policy_id),
                "retention_policy_number": manifest.retention_policy_number,
                "retention_policy_hash": manifest.retention_policy_hash,
                "authorization_lineage_hash": manifest.authorization_lineage_hash,
                "inventory_hash": manifest.inventory_hash,
                "manifest_hash": manifest.manifest_hash,
                "document_count": manifest.document_count,
                "total_file_size_bytes": manifest.total_file_size_bytes,
                "manifest_expires_at": manifest.manifest_expires_at.isoformat(),
                "active_hold_ids": manifest.active_hold_ids,
                "pending_proposal_ids": manifest.pending_proposal_ids,
                "storage_identifiers_raw_logged": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        db.refresh(manifest)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DisposalManifestPreflightError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "disposal_execution_manifest_preflight_failed",
                "outcome": exc.outcome,
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(manifest)


@router.get(
    "/{claim_id}/disposal-execution-manifests",
    response_model=list[DisposalExecutionManifestRead],
)
def list_execution_manifests_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[DisposalExecutionManifestRead]:
    try:
        manifests = list_disposal_execution_manifests(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_read(item) for item in manifests]


@router.get(
    "/{claim_id}/disposal-execution-manifests/{manifest_id}",
    response_model=DisposalExecutionManifestRead,
)
def get_execution_manifest_endpoint(
    claim_id: UUID,
    manifest_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> DisposalExecutionManifestRead:
    try:
        manifest = get_disposal_execution_manifest(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            manifest_id=manifest_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(manifest)


@router.post(
    "/{claim_id}/disposal-execution-manifests/{manifest_id}/revalidate",
    response_model=DisposalExecutionManifestRead,
)
def revalidate_execution_manifest_endpoint(
    claim_id: UUID,
    manifest_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalExecutionManifestRead:
    try:
        manifest, outcome = revalidate_disposal_execution_manifest(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            manifest_id=manifest_id,
            actor_id=current_user.id,
        )
        if outcome != "unchanged":
            action = {
                "ready": "DISPOSAL_EXECUTION_MANIFEST_REVALIDATED",
                "blocked": "DISPOSAL_EXECUTION_MANIFEST_BLOCKED",
                "invalidated": "DISPOSAL_EXECUTION_MANIFEST_INVALIDATED",
                "expired": "DISPOSAL_EXECUTION_MANIFEST_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_execution_manifest",
                entity_id=manifest.id,
                new_values={
                    "claim_id": str(manifest.claim_id),
                    "status": manifest.status,
                    "inventory_hash": manifest.inventory_hash,
                    "manifest_hash": manifest.manifest_hash,
                    "terminal_reason": manifest.terminal_reason,
                    "storage_identifiers_raw_logged": False,
                    "destructive_action_performed": False,
                },
            )
            db.commit()
            db.refresh(manifest)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(manifest)
