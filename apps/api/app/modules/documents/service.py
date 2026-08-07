from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.documents.storage import LocalDocumentStorage, UploadTooLarge
from app.modules.users.models import User
from app.modules.processing.service import enqueue_text_extraction

settings = get_settings()

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Browser/OS fallbacks seen for Office uploads. Extension validation still applies.
    "application/octet-stream",
}


def _storage() -> LocalDocumentStorage:
    if settings.storage_backend != "local":
        raise RuntimeError(f"Unsupported storage backend: {settings.storage_backend}")
    return LocalDocumentStorage(
        settings.local_storage_path,
        max_upload_bytes=settings.max_upload_bytes,
    )


def normalize_original_filename(filename: str | None) -> str:
    cleaned = Path(filename or "document").name.strip().replace("\x00", "")
    if not cleaned:
        cleaned = "document"
    return cleaned[:255]


def validate_upload(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Allowed: PDF, JPG, PNG, DOCX, XLSX.",
        )
    if content_type and content_type.lower() not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded file content type is not supported.",
        )
    return suffix


def make_storage_key(*, organization_id: UUID, claim_id: UUID, document_id: UUID, suffix: str) -> str:
    return f"{organization_id}/{claim_id}/{document_id}{suffix}"


def validate_file_signature(storage: LocalDocumentStorage, storage_key: str, suffix: str) -> None:
    path = storage.path_for(storage_key)
    with path.open("rb") as source:
        header = source.read(16)
    valid = {
        ".pdf": header.startswith(b"%PDF-"),
        ".jpg": header.startswith(b"\xff\xd8\xff"),
        ".jpeg": header.startswith(b"\xff\xd8\xff"),
        ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        ".docx": header.startswith(b"PK\x03\x04"),
        ".xlsx": header.startswith(b"PK\x03\x04"),
    }.get(suffix, False)
    if not valid:
        storage.delete_physical(storage_key)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File content does not match the declared file type.",
        )


async def create_document_from_upload(
    db: Session,
    *,
    claim: Claim,
    current_user: User,
    upload: UploadFile,
    document_type: str | None,
    confidentiality_level: ConfidentialityLevel,
) -> Document:
    original_filename = normalize_original_filename(upload.filename)
    suffix = validate_upload(original_filename, upload.content_type)
    document_id = uuid4()
    storage_key = make_storage_key(
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        document_id=document_id,
        suffix=suffix,
    )

    storage = _storage()
    try:
        stored = await storage.save_upload(upload, storage_key)
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
        ) from exc

    if stored.file_size_bytes == 0:
        storage.delete_physical(stored.storage_key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty files are not accepted.")
    validate_file_signature(storage, stored.storage_key, suffix)

    duplicate = db.scalar(
        select(Document).where(
            Document.organization_id == current_user.organization_id,
            Document.claim_id == claim.id,
            Document.file_hash == stored.file_hash,
        )
    )
    if duplicate is not None:
        storage.delete_physical(stored.storage_key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This file already exists in the claim as document {duplicate.id}.",
        )

    document = Document(
        id=document_id,
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        uploaded_by_id=current_user.id,
        filename=original_filename,
        original_filename=original_filename,
        document_type=(document_type.strip()[:100] or None) if document_type else None,
        mime_type=(upload.content_type or "application/octet-stream")[:150],
        file_size_bytes=stored.file_size_bytes,
        file_hash=stored.file_hash,
        storage_key=stored.storage_key,
        confidentiality_level=confidentiality_level,
    )
    db.add(document)
    enqueue_text_extraction(db, document=document, requested_by_id=current_user.id)
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="UPLOAD_DOCUMENT",
        entity_type="document",
        entity_id=document.id,
        new_values={
            "claim_id": str(claim.id),
            "filename": original_filename,
            "file_size_bytes": stored.file_size_bytes,
            "file_hash": stored.file_hash,
            "document_type": document.document_type,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        storage.delete_physical(stored.storage_key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This file already exists in the claim.",
        ) from exc
    db.refresh(document)
    return document


def list_documents(db: Session, *, claim_id: UUID, organization_id: UUID) -> tuple[list[Document], int]:
    conditions = (
        Document.organization_id == organization_id,
        Document.claim_id == claim_id,
        Document.deleted_at.is_(None),
    )
    items = list(db.scalars(select(Document).where(*conditions).order_by(Document.created_at.desc())).all())
    total = db.scalar(select(func.count(Document.id)).where(*conditions)) or 0
    return items, total


def soft_delete_document(db: Session, *, document: Document, current_user: User) -> None:
    document.deleted_at = datetime.now(UTC)
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="DELETE_DOCUMENT",
        entity_type="document",
        entity_id=document.id,
        old_values={
            "claim_id": str(document.claim_id),
            "filename": document.original_filename,
            "file_hash": document.file_hash,
        },
        details="Soft delete only; evidence bytes retained in storage.",
    )
    db.commit()
