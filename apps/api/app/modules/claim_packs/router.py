import hashlib
import hmac
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
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


def _assert_archived_file_intact(
    path: Path, *, expected_size: int, expected_sha256: str,
) -> None:
    """Fail closed if local archive bytes drift from immutable export metadata.

    Process the file in bounded chunks rather than buffering a potentially
    large Claim Pack in memory. Checking only Content-Length or returning a
    stored SHA-256 header is insufficient: neither attests the served bytes.
    """
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stored_file:
            while chunk := stored_file.read(1024 * 1024):
                size += len(chunk)
                if size > expected_size:
                    break
                digest.update(chunk)
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
) -> FileResponse:
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

    # Compare the actual local file against its persisted generation-time
    # integrity metadata *before* producing a successful download response or
    # success audit entry. A stored hash response header alone is not evidence
    # that the current archive bytes match it.
    _assert_archived_file_intact(
        path,
        expected_size=item.file_size_bytes,
        expected_sha256=item.file_hash,
    )

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
    return FileResponse(
        path=path,
        media_type=item.mime_type,
        filename=item.filename,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "X-Claim-Pack-Snapshot-SHA256": item.snapshot_hash,
            "X-Claim-Pack-File-SHA256": item.file_hash,
            "X-Claim-Current-Unverified-OCR-Source-Report-Count": str(current_ocr_reports),
        },
    )
