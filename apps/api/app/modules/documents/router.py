from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.models import ConfidentialityLevel
from app.modules.documents.schemas import DocumentListResponse, DocumentResponse
from app.modules.documents.security import get_document_for_tenant
from app.modules.documents.service import (
    _storage,
    create_document_from_upload,
    list_documents,
    soft_delete_document,
)

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
    return DocumentListResponse(items=items, total=total)


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
    return DocumentResponse.model_validate(document)


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
    soft_delete_document(db, document=document, current_user=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
