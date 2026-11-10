from datetime import UTC
from email.utils import format_datetime
import hashlib
import hmac
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
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
from app.modules.claim_packs.service import _snapshot_hash
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
) -> tuple[Path, TemporaryDirectory]:
    """Return a private file containing only digest-verified archive bytes.

    FileResponse supplies full/single-range/multipart-range and conditional
    download semantics. Crucially its path points to an isolated, mode-0600
    copy in a private temporary directory, never the mutable source archive.
    Copying in 1 MiB chunks bounds application memory. The caller must clean
    up the returned directory after the response completes (also on failure).
    """
    private = TemporaryDirectory(prefix="seeclaims-verified-archive-")
    digest = hashlib.sha256()
    size = 0
    try:
        try:
            with path.open("rb") as source:
                # NamedTemporaryFile uses private 0600 permissions. The parent
                # TemporaryDirectory is 0700, restricting access while an
                # async FileResponse streams bytes from this one verified copy.
                with NamedTemporaryFile(
                    mode="w+b", dir=private.name, prefix="verified-", delete=False,
                ) as capture:
                    verified_path = Path(capture.name)
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > expected_size:
                            break
                        digest.update(chunk)
                        capture.write(chunk)
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
        return verified_path, private
    except BaseException:
        private.cleanup()
        raise


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

    # Both the archived file and its stored source snapshot need an exact
    # generation-time attestation. Otherwise a later JSON change could be
    # served alongside the original, now-misleading snapshot SHA-256 header.
    if not hmac.compare_digest(_snapshot_hash(item.snapshot), item.snapshot_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Archived Claim Pack snapshot no longer matches its recorded "
                "SHA-256 digest. Download blocked pending archive integrity "
                "review; the original export record was not changed."
            ),
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
    verified_path, private = _verified_archive_copy(
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
        # A stable content-derived ETag preserves If-Range resume requests
        # even though every download gets its own private temporary pathname.
        created_at = item.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return FileResponse(
            path=verified_path,
            media_type=item.mime_type,
            filename=item.filename,
            background=BackgroundTask(private.cleanup),
            headers={
                "ETag": f'"{item.file_hash}"',
                "Last-Modified": format_datetime(created_at.astimezone(UTC), usegmt=True),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
                "X-Claim-Pack-Snapshot-SHA256": item.snapshot_hash,
                "X-Claim-Pack-File-SHA256": item.file_hash,
                "X-Claim-Current-Unverified-OCR-Source-Report-Count": str(current_ocr_reports),
            },
        )
    except BaseException:
        private.cleanup()
        raise
