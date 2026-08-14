from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.models import (
    ConfidentialityLevel,
    DocumentMalwareScanStatus,
)
from app.modules.documents.evidence_security import (
    EvidenceSecurityError,
    get_quarantined_upload_for_tenant,
    purge_quarantined_upload,
    queue_legacy_rescans,
    retry_quarantined_upload,
)
from app.modules.documents.schemas import (
    DocumentListResponse,
    DocumentResponse,
    LegacyRescanJobResponse,
    LegacyRescanRequest,
    LegacyRescanResponse,
    QuarantinePurgeRequest,
    QuarantinePurgeResponse,
    QuarantineRetryResponse,
)
from app.modules.documents.security import get_document_for_tenant
from app.modules.documents.service import (
    _storage,
    create_document_from_upload,
    list_documents,
    list_quarantined_uploads,
    soft_delete_document,
)
from app.modules.rules.service import evaluate_claim_rules
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/claims/{claim_id}/documents", tags=["documents"])


@router.get("", response_model=DocumentListResponse)
def list_claim_documents(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentListResponse:
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    items, total = list_documents(
        db, claim_id=claim.id, organization_id=current_user.organization_id
    )
    quarantined_items, quarantined_total = list_quarantined_uploads(
        db, claim_id=claim.id, organization_id=current_user.organization_id
    )
    return DocumentListResponse(
        items=items,
        total=total,
        quarantined_items=quarantined_items,
        quarantined_total=quarantined_total,
    )


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_claim_document(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    document_type: Annotated[str | None, Form()] = None,
    confidentiality_level: Annotated[ConfidentialityLevel, Form()] = ConfidentialityLevel.CONFIDENTIAL,
) -> DocumentResponse:
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = await create_document_from_upload(
        db,
        claim=claim,
        current_user=current_user,
        upload=file,
        document_type=document_type,
        confidentiality_level=confidentiality_level,
    )
    evaluate_claim_rules(db, claim=claim, user=current_user, trigger="document_upload")
    return DocumentResponse.model_validate(document)


@router.post(
    "/rescan-legacy",
    response_model=LegacyRescanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def rescan_legacy_claim_documents(
    claim_id: UUID,
    payload: LegacyRescanRequest,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> LegacyRescanResponse:
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    jobs, skipped = queue_legacy_rescans(
        db,
        claim=claim,
        current_user=current_user,
        limit=payload.limit,
    )
    return LegacyRescanResponse(
        queued_count=len(jobs),
        skipped_count=skipped,
        jobs=[
            LegacyRescanJobResponse(
                job_id=job.id,
                document_id=job.document_id,
                status=job.status.value,
            )
            for job in jobs
        ],
    )


@router.post(
    "/quarantined-uploads/{upload_id}/retry",
    response_model=QuarantineRetryResponse,
)
def retry_claim_quarantined_upload(
    claim_id: UUID,
    upload_id: UUID,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> QuarantineRetryResponse:
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    quarantined = get_quarantined_upload_for_tenant(
        db,
        upload_id=upload_id,
        claim_id=claim.id,
        organization_id=current_user.organization_id,
    )
    if quarantined is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quarantine record not found")
    try:
        released_document = retry_quarantined_upload(
            db,
            quarantined=quarantined,
            current_user=current_user,
        )
    except EvidenceSecurityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if released_document is not None:
        evaluate_claim_rules(db, claim=claim, user=current_user, trigger="document_upload")
    return QuarantineRetryResponse(
        quarantine_id=quarantined.id,
        status=quarantined.status,
        retry_count=quarantined.retry_count,
        released_document_id=released_document.id if released_document else None,
        threat_name=quarantined.threat_name,
    )


@router.post(
    "/quarantined-uploads/{upload_id}/purge",
    response_model=QuarantinePurgeResponse,
)
def purge_claim_quarantined_upload(
    claim_id: UUID,
    upload_id: UUID,
    payload: QuarantinePurgeRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> QuarantinePurgeResponse:
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    if payload.confirm_upload_id != upload_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quarantine confirmation ID does not match the requested record.",
        )
    quarantined = get_quarantined_upload_for_tenant(
        db,
        upload_id=upload_id,
        claim_id=claim.id,
        organization_id=current_user.organization_id,
    )
    if quarantined is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quarantine record not found")
    try:
        purge_quarantined_upload(
            db,
            quarantined=quarantined,
            current_user=current_user,
            reason=payload.reason,
        )
    except EvidenceSecurityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return QuarantinePurgeResponse(
        quarantine_id=quarantined.id,
        status=quarantined.status,
    )


@router.get("/{document_id}/download")
def download_claim_document(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(
        db,
        document_id=document_id,
        claim_id=claim.id,
        organization_id=current_user.organization_id,
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.malware_scan_status not in {
        DocumentMalwareScanStatus.CLEAN,
        DocumentMalwareScanStatus.LEGACY_UNSCANNED,
    }:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Document download is blocked: {document.malware_scan_status.value}.",
        )
    try:
        path = _storage().path_for(document.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Document metadata exists but the stored file is unavailable.",
        ) from exc
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="DOWNLOAD_DOCUMENT",
        entity_type="document",
        entity_id=document.id,
        details=f"Downloaded {document.original_filename}",
    )
    db.commit()
    return FileResponse(path=path, media_type=document.mime_type, filename=document.original_filename)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_claim_document(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    claim = get_claim_for_tenant(
        db, claim_id=claim_id, organization_id=current_user.organization_id
    )
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    document = get_document_for_tenant(
        db,
        document_id=document_id,
        claim_id=claim.id,
        organization_id=current_user.organization_id,
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.malware_scan_status in {
        DocumentMalwareScanStatus.INFECTED_QUARANTINED,
        DocumentMalwareScanStatus.SCAN_ERROR,
    }:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Quarantined document provenance cannot be removed from the claim record.",
        )
    soft_delete_document(db, document=document, current_user=current_user)
    evaluate_claim_rules(db, claim=claim, user=current_user, trigger="document_delete")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
