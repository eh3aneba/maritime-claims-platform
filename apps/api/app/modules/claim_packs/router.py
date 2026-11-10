import hashlib
import hmac
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Annotated, BinaryIO, Iterator
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser
from app.modules.claim_packs.schemas import (
    ClaimPackExportListResponse,
    ClaimPackExportResponse,
    ClaimPackGenerateRequest,
)
from app.modules.claim_packs.renderers import UnsupportedClaimPackPDFTextError
from app.modules.claim_packs.source_report_notice import current_ocr_source_report_count
from app.modules.claim_packs.recovery_service import (
    generate_claim_pack,
    get_claim_pack_export,
    list_claim_pack_exports,
)
from app.modules.claims.service import ClaimNotFoundError
from app.modules.documents.service import _storage


router = APIRouter(
    prefix="/claims/{claim_id}/claim-pack-exports",
    tags=["claim-pack-exports"],
)


def _verified_archive_copy(
    path: Path, *, expected_size: int, expected_sha256: str,
) -> BinaryIO:
    """Capture exactly the bytes whose digest was verified, then serve only those.

    A FileResponse would reopen the original archive after the check, so a
    raced-in replacement could be served under the old approved hash. A
    private, spooled copy (1 MiB RAM, then temporary disk) binds the actual
    response to the digest and bounds resident-memory use. No original source
    data or historical export metadata is modified.
    """
    verified: BinaryIO = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    digest = hashlib.sha256()
    size = 0
    try:
        try:
            with path.open("rb") as stored_file:
                while chunk := stored_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > expected_size:
                        break
                    digest.update(chunk)
                    verified.write(chunk)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Archived Claim Pack file is unavailable for integrity verification.",
            ) from exc
        if (
            size != expected_size
            or not hmac.compare_digest(digest.hexdigest(), expected_sha256)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Archived Claim Pack content no longer matches its recorded "
                    "size or SHA-256 digest. Download blocked pending archive "
                    "integrity review; the original export record was not changed."
                ),
            )
        verified.seek(0)
        return verified
    except BaseException:
        verified.close()
        raise


def _iter_verified_archive(verified: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := verified.read(1024 * 1024):
            yield chunk
    finally:
        verified.close()


def _download_disposition(filename: str) -> str:
    encoded = quote(filename)
    return (
        f"attachment; filename*=utf-8''{encoded}"
        if encoded != filename
        else f'attachment; filename="{filename}"'
    )


@router.get("", response_model=ClaimPackExportListResponse)
def list_exports(
    claim_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ClaimPackExportListResponse:
    try:
        items = list_claim_pack_exports(
            db,
            claim_id=claim_id,
            organization_id=current_user.organization_id,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found",
        ) from exc
    return ClaimPackExportListResponse(
        items=[ClaimPackExportResponse.model_validate(item) for item in items],
        total=len(items),
        current_unverified_ocr_source_report_count=current_ocr_source_report_count(
            db, claim_id=claim_id, organization_id=current_user.organization_id,
        ),
    )


@router.post(
    "",
    response_model=ClaimPackExportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_export(
    claim_id: UUID,
    payload: ClaimPackGenerateRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ClaimPackExportResponse:
    try:
        item = generate_claim_pack(
            db,
            claim_id=claim_id,
            organization_id=current_user.organization_id,
            user=current_user,
            export_format=payload.export_format,
            generation_note=payload.generation_note,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found",
        ) from exc
    except UnsupportedClaimPackPDFTextError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot generate a faithful Claim Pack PDF for these characters. "
                "Use XLSX and consult the original evidence; no PDF was saved."
            ),
        ) from exc
    return ClaimPackExportResponse.model_validate(item)


@router.get("/{export_id}/download")
def download_export(
    claim_id: UUID,
    export_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    try:
        item = get_claim_pack_export(
            db,
            export_id=export_id,
            claim_id=claim_id,
            organization_id=current_user.organization_id,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found",
        ) from exc
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim-pack export not found",
        )
    try:
        path = _storage().path_for(item.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Export metadata exists but the immutable file is unavailable.",
        ) from exc

    # Capture exactly the verified bytes before the audit and response. The
    # original archive may be renamed, replaced or edited after this point,
    # but the returned stream is isolated from those later changes.
    verified = _verified_archive_copy(
        path,
        expected_size=item.file_size_bytes,
        expected_sha256=item.file_hash,
    )
    try:
        # Read-time claim-wide advisory only. Never mutate archived snapshot
        # bytes or imply that an unverified report proves an error in this pack.
        current_ocr_reports = current_ocr_source_report_count(
            db, claim_id=claim_id, organization_id=current_user.organization_id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DOWNLOAD_CLAIM_PACK_EXPORT",
            entity_type="claim_pack_export",
            entity_id=item.id,
            details=f"Downloaded {item.filename}",
        )
        db.commit()
        return StreamingResponse(
            _iter_verified_archive(verified),
            media_type=item.mime_type,
            background=BackgroundTask(verified.close),
            headers={
                "Content-Length": str(item.file_size_bytes),
                "Content-Disposition": _download_disposition(item.filename),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
                "X-Claim-Pack-Snapshot-SHA256": item.snapshot_hash,
                "X-Claim-Pack-File-SHA256": item.file_hash,
                "X-Claim-Current-Unverified-OCR-Source-Report-Count": str(current_ocr_reports),
            },
        )
    except BaseException:
        verified.close()
        raise
