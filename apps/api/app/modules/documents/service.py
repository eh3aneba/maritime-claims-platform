from datetime import UTC, datetime
from pathlib import Path
from typing import Never
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.malware import (
    MalwareScannerError,
    MalwareScanVerdict,
    scan_file,
)
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
    QuarantinedUpload,
    QuarantineStatus,
)
from app.modules.documents.storage import LocalDocumentStorage, StorageError, UploadTooLarge
from app.modules.processing.service import enqueue_text_extraction
from app.modules.users.models import User

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


def make_quarantine_key(*, organization_id: UUID, claim_id: UUID, upload_id: UUID, suffix: str) -> str:
    return f"_quarantine/{organization_id}/{claim_id}/{upload_id}{suffix}"


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


def _record_quarantine_and_raise(
    db: Session,
    *,
    storage: LocalDocumentStorage,
    upload_id: UUID,
    claim: Claim,
    current_user: User,
    original_filename: str,
    mime_type: str,
    file_size_bytes: int,
    file_hash: str,
    quarantine_key: str,
    quarantine_status: QuarantineStatus,
    threat_name: str | None = None,
    scan_error: str | None = None,
) -> Never:
    scanned_at = datetime.now(UTC)
    quarantined = QuarantinedUpload(
        id=upload_id,
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        uploaded_by_id=current_user.id,
        original_filename=original_filename,
        mime_type=mime_type[:150],
        file_size_bytes=file_size_bytes,
        file_hash=file_hash,
        quarantine_key=quarantine_key,
        status=quarantine_status,
        threat_name=threat_name,
        scan_error=scan_error,
        scanned_at=scanned_at,
    )
    db.add(quarantined)
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="QUARANTINE_DOCUMENT_UPLOAD",
        entity_type="quarantined_upload",
        entity_id=quarantined.id,
        new_values={
            "claim_id": str(claim.id),
            "filename": original_filename,
            "file_size_bytes": file_size_bytes,
            "file_hash": file_hash,
            "status": quarantine_status.value,
            "threat_name": threat_name,
        },
        details="Upload retained outside active evidence storage; download and processing are blocked.",
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        storage.delete_physical(quarantine_key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="These bytes already exist in the claim quarantine.",
        ) from exc

    if quarantine_status == QuarantineStatus.INFECTED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Malware was detected. The upload was blocked and quarantined. Reference: {upload_id}.",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Malware scanning could not complete. The upload remains quarantined. Reference: {upload_id}.",
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
    upload_id = uuid4()
    quarantine_key = make_quarantine_key(
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        upload_id=upload_id,
        suffix=suffix,
    )

    storage = _storage()
    try:
        stored = await storage.save_upload(upload, quarantine_key)
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
        ) from exc

    if stored.file_size_bytes == 0:
        storage.delete_physical(stored.storage_key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty files are not accepted.")
    validate_file_signature(storage, stored.storage_key, suffix)

    duplicate_document = db.scalar(
        select(Document).where(
            Document.organization_id == current_user.organization_id,
            Document.claim_id == claim.id,
            Document.file_hash == stored.file_hash,
        )
    )
    duplicate_quarantine = db.scalar(
        select(QuarantinedUpload).where(
            QuarantinedUpload.organization_id == current_user.organization_id,
            QuarantinedUpload.claim_id == claim.id,
            QuarantinedUpload.file_hash == stored.file_hash,
        )
    )
    if duplicate_document is not None or duplicate_quarantine is not None:
        storage.delete_physical(stored.storage_key)
        reference = duplicate_document.id if duplicate_document is not None else duplicate_quarantine.id
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"These bytes already exist in the claim as record {reference}.",
        )

    malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
    malware_scanned_at = None
    if settings.malware_scan_enabled:
        try:
            scan_result = scan_file(
                storage.path_for(stored.storage_key),
                host=settings.clamav_host,
                port=settings.clamav_port,
                timeout_seconds=settings.clamav_timeout_seconds,
            )
        except MalwareScannerError as exc:
            _record_quarantine_and_raise(
                db,
                storage=storage,
                upload_id=upload_id,
                claim=claim,
                current_user=current_user,
                original_filename=original_filename,
                mime_type=upload.content_type or "application/octet-stream",
                file_size_bytes=stored.file_size_bytes,
                file_hash=stored.file_hash,
                quarantine_key=stored.storage_key,
                quarantine_status=QuarantineStatus.SCAN_ERROR,
                scan_error=str(exc)[:1000],
            )
        if scan_result.verdict == MalwareScanVerdict.INFECTED:
            _record_quarantine_and_raise(
                db,
                storage=storage,
                upload_id=upload_id,
                claim=claim,
                current_user=current_user,
                original_filename=original_filename,
                mime_type=upload.content_type or "application/octet-stream",
                file_size_bytes=stored.file_size_bytes,
                file_hash=stored.file_hash,
                quarantine_key=stored.storage_key,
                quarantine_status=QuarantineStatus.INFECTED,
                threat_name=scan_result.threat_name,
            )
        malware_scan_status = DocumentMalwareScanStatus.CLEAN
        malware_scanned_at = datetime.now(UTC)

    storage_key = make_storage_key(
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        document_id=upload_id,
        suffix=suffix,
    )
    try:
        storage.promote(stored.storage_key, storage_key)
    except StorageError as exc:
        _record_quarantine_and_raise(
            db,
            storage=storage,
            upload_id=upload_id,
            claim=claim,
            current_user=current_user,
            original_filename=original_filename,
            mime_type=upload.content_type or "application/octet-stream",
            file_size_bytes=stored.file_size_bytes,
            file_hash=stored.file_hash,
            quarantine_key=stored.storage_key,
            quarantine_status=QuarantineStatus.SCAN_ERROR,
            scan_error=f"Storage promotion failed: {type(exc).__name__}",
        )

    document = Document(
        id=upload_id,
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        uploaded_by_id=current_user.id,
        filename=original_filename,
        original_filename=original_filename,
        document_type=(document_type.strip()[:100] or None) if document_type else None,
        mime_type=(upload.content_type or "application/octet-stream")[:150],
        file_size_bytes=stored.file_size_bytes,
        file_hash=stored.file_hash,
        storage_key=storage_key,
        confidentiality_level=confidentiality_level,
        malware_scan_status=malware_scan_status,
        malware_scanned_at=malware_scanned_at,
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
            "malware_scan_status": document.malware_scan_status.value,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        storage.delete_physical(storage_key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="These bytes already exist in the claim.",
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


def list_quarantined_uploads(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
) -> tuple[list[QuarantinedUpload], int]:
    conditions = (
        QuarantinedUpload.organization_id == organization_id,
        QuarantinedUpload.claim_id == claim_id,
    )
    items = list(
        db.scalars(
            select(QuarantinedUpload).where(*conditions).order_by(QuarantinedUpload.created_at.desc())
        ).all()
    )
    total = db.scalar(select(func.count(QuarantinedUpload.id)).where(*conditions)) or 0
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
