from __future__ import annotations

import re
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from app.modules.audit.service import write_audit_log
from app.modules.users.models import User
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.claims.models import Claim
from app.modules.claims.service import create_claim, get_claim
from app.modules.documents.malware import MalwareScannerError, MalwareScanVerdict, scan_file
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.documents.service import (
    normalize_original_filename,
    validate_file_signature,
    validate_upload,
)
from app.modules.documents.storage import LocalDocumentStorage, StorageError, UploadTooLarge
from app.modules.intake.models import ClaimIntakeDraft, ClaimIntakeProcessingJob, ClaimIntakeStatus
from app.modules.intake.schemas import ClaimIntakeApprove
from app.modules.processing.extractors import EXTRACTOR_VERSION, extract_document_text
from app.modules.processing.models import (
    DocumentTextExtraction,
    DocumentTextSegment,
    ProcessingJobStatus,
)

settings = get_settings()
INTAKE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}


class ClaimIntakeNotFoundError(LookupError):
    pass


class ClaimIntakeStateError(ValueError):
    pass


def _storage() -> LocalDocumentStorage:
    if settings.storage_backend != "local":
        raise RuntimeError(f"Unsupported storage backend: {settings.storage_backend}")
    return LocalDocumentStorage(
        settings.local_storage_path, max_upload_bytes=settings.max_upload_bytes
    )


def _quarantine_key(*, organization_id: UUID, draft_id: UUID, suffix: str) -> str:
    return f"_quarantine/{organization_id}/claim-intake/{draft_id}{suffix}"


def _intake_key(*, organization_id: UUID, draft_id: UUID, suffix: str) -> str:
    return f"_intake/{organization_id}/{draft_id}{suffix}"


def _document_key(*, organization_id: UUID, claim_id: UUID, document_id: UUID, suffix: str) -> str:
    return f"{organization_id}/{claim_id}/{document_id}{suffix}"


def _classification(filename: str, text: str) -> tuple[str, int, str]:
    sample = f"{filename}\n{text[:12000]}".lower()
    rules = [
        (
            "claim_notification",
            96,
            "claim-notification phrase",
            ["claim notification", "notice of loss", "first notification", "اعلام خسارت"],
        ),
        (
            "chief_engineer_report",
            92,
            "chief-engineer phrase",
            ["chief engineer report", "chief engineer's report", "گزارش مهندس ارشد"],
        ),
        (
            "survey_report",
            88,
            "survey-report phrase",
            ["survey report", "surveyor report", "گزارش بازدید"],
        ),
        ("engine_log", 86, "engine-log phrase", ["engine log", "engine room log", "لاگ موتور"]),
        ("invoice", 84, "invoice phrase", ["invoice", "tax invoice", "صورتحساب"]),
        ("quotation", 82, "quotation phrase", ["quotation", "quote no", "پیشنهاد قیمت"]),
    ]
    for document_type, confidence, rule, terms in rules:
        if any(term in sample for term in terms):
            return document_type, confidence, rule
    return "unknown", 25, "no deterministic classification phrase matched"


def _first_match(
    patterns: list[str], text: str, *, flags: int = re.IGNORECASE
) -> tuple[str | None, str | None]:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = " ".join(match.group(1).strip().split())
            return value[:500], match.group(0)[:500]
    return None, None


_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().replace("/", "-")
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError:
        pass
    numeric = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", normalized)
    if numeric:
        try:
            return date(
                int(numeric.group(3)),
                int(numeric.group(2)),
                int(numeric.group(1)),
            ).isoformat()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", normalized)
    if match and match.group(2).lower() in _MONTHS:
        try:
            return date(
                int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1))
            ).isoformat()
        except ValueError:
            return None
    return None


def extract_intake_candidates(text: str) -> tuple[dict, dict]:
    vessel_name, vessel_quote = _first_match(
        [
            r"(?:vessel\s*name|name\s+of\s+vessel|ship\s*name|نام\s*کشتی)\s*[:\-]\s*([^\n\r]+)",
            r"\bM[\./]?T[\s\.]+([A-Z][A-Z0-9 '\-]{2,60})",
        ],
        text,
    )
    imo_number, imo_quote = _first_match(
        [r"\bIMO(?:\s*(?:number|no\.?))?\s*[:#\-]?\s*(\d{7})\b"],
        text,
    )
    incident_raw, incident_quote = _first_match(
        [
            r"(?:incident|casualty|loss)\s*date\s*[:\-]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            r"(?:تاریخ\s*حادثه)\s*[:\-]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        ],
        text,
    )
    notification_raw, notification_quote = _first_match(
        [
            r"(?:notification|notice)\s*date\s*[:\-]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            r"(?:تاریخ\s*اعلام)\s*[:\-]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        ],
        text,
    )
    external_reference, reference_quote = _first_match(
        [r"(?:claim|club|insurer|external)\s*(?:reference|ref\.?|no\.?)\s*[:#\-]\s*([^\n\r]+)"],
        text,
    )
    description, description_quote = _first_match(
        [
            r"(?:incident\s*(?:description|details)|description\s+of\s+loss|شرح\s*حادثه)\s*[:\-]\s*([^\n\r]{10,1200})",
        ],
        text,
    )
    if not description:
        description = " ".join(text.strip().split())[:1200] or None
        description_quote = description

    incident_date = _parse_date(incident_raw)
    notification_date = _parse_date(notification_raw)
    fields = {
        "vessel_name": vessel_name,
        "imo_number": imo_number,
        "incident_date": incident_date,
        "notification_date": notification_date,
        "incident_description": description,
        "external_reference": external_reference,
        "claim_type": "hull_machinery",
        "claim_subtype": "machinery_damage",
        "priority": "medium",
        "currency": "USD",
    }
    evidence = {
        "vessel_name": {"quote": vessel_quote, "confidence": 88 if vessel_name else 0},
        "imo_number": {"quote": imo_quote, "confidence": 99 if imo_number else 0},
        "incident_date": {"quote": incident_quote, "confidence": 90 if incident_date else 0},
        "notification_date": {
            "quote": notification_quote,
            "confidence": 90 if notification_date else 0,
        },
        "incident_description": {
            "quote": description_quote,
            "confidence": 70 if description else 0,
        },
        "external_reference": {
            "quote": reference_quote,
            "confidence": 85 if external_reference else 0,
        },
        "priority": {
            "quote": None,
            "confidence": 0,
            "note": "Default only; requires human review.",
        },
        "currency": {
            "quote": None,
            "confidence": 0,
            "note": "Default only; requires human review.",
        },
    }
    return fields, evidence


async def create_intake_draft(
    db: Session,
    *,
    upload: UploadFile,
    current_user: User,
) -> ClaimIntakeDraft:
    filename = normalize_original_filename(upload.filename)
    suffix = validate_upload(filename, upload.content_type)
    if suffix not in INTAKE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="FNOL intake accepts PDF, JPG, PNG or DOCX.",
        )
    if not settings.malware_scan_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FNOL intake requires an enabled malware scanner.",
        )

    draft_id = uuid4()
    quarantine_key = _quarantine_key(
        organization_id=current_user.organization_id,
        draft_id=draft_id,
        suffix=suffix,
    )
    storage = _storage()
    try:
        stored = await storage.save_upload(upload, quarantine_key)
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=413, detail=f"File exceeds the {settings.max_upload_mb} MB upload limit."
        ) from exc
    if stored.file_size_bytes == 0:
        storage.delete_physical(stored.storage_key)
        raise HTTPException(status_code=400, detail="Empty files are not accepted.")
    validate_file_signature(storage, stored.storage_key, suffix)

    duplicate = db.scalar(
        select(ClaimIntakeDraft).where(
            ClaimIntakeDraft.organization_id == current_user.organization_id,
            ClaimIntakeDraft.file_hash == stored.file_hash,
        )
    )
    if duplicate is not None:
        storage.delete_physical(stored.storage_key)
        raise HTTPException(
            status_code=409, detail=f"This intake source already exists as draft {duplicate.id}."
        )

    scanned_at = datetime.now(UTC)
    try:
        result = scan_file(
            storage.path_for(stored.storage_key),
            host=settings.clamav_host,
            port=settings.clamav_port,
            timeout_seconds=settings.clamav_timeout_seconds,
        )
    except MalwareScannerError as exc:
        draft = ClaimIntakeDraft(
            id=draft_id,
            organization_id=current_user.organization_id,
            uploaded_by_id=current_user.id,
            original_filename=filename,
            mime_type=(upload.content_type or "application/octet-stream")[:150],
            file_size_bytes=stored.file_size_bytes,
            file_hash=stored.file_hash,
            storage_key=stored.storage_key,
            malware_scan_status=DocumentMalwareScanStatus.SCAN_ERROR,
            malware_scanned_at=scanned_at,
            scan_error=str(exc)[:1000],
            status=ClaimIntakeStatus.SCAN_ERROR,
        )
        db.add(draft)
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="QUARANTINE_CLAIM_INTAKE_SCAN_ERROR",
            entity_type="claim_intake_draft",
            entity_id=draft.id,
            new_values={"file_hash": draft.file_hash, "status": draft.status.value},
        )
        db.commit()
        raise HTTPException(
            status_code=503, detail=f"Scanner unavailable; intake held as {draft.id}."
        ) from exc

    if result.verdict == MalwareScanVerdict.INFECTED:
        draft = ClaimIntakeDraft(
            id=draft_id,
            organization_id=current_user.organization_id,
            uploaded_by_id=current_user.id,
            original_filename=filename,
            mime_type=(upload.content_type or "application/octet-stream")[:150],
            file_size_bytes=stored.file_size_bytes,
            file_hash=stored.file_hash,
            storage_key=stored.storage_key,
            malware_scan_status=DocumentMalwareScanStatus.INFECTED_QUARANTINED,
            malware_scanned_at=scanned_at,
            threat_name=result.threat_name,
            status=ClaimIntakeStatus.INFECTED,
        )
        db.add(draft)
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="QUARANTINE_INFECTED_CLAIM_INTAKE",
            entity_type="claim_intake_draft",
            entity_id=draft.id,
            new_values={
                "file_hash": draft.file_hash,
                "status": draft.status.value,
                "threat_name": draft.threat_name,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=422, detail=f"Malware detected; intake blocked as {draft.id}."
        )

    intake_key = _intake_key(
        organization_id=current_user.organization_id,
        draft_id=draft_id,
        suffix=suffix,
    )
    storage.promote(stored.storage_key, intake_key)
    draft = ClaimIntakeDraft(
        id=draft_id,
        organization_id=current_user.organization_id,
        uploaded_by_id=current_user.id,
        original_filename=filename,
        mime_type=(upload.content_type or "application/octet-stream")[:150],
        file_size_bytes=stored.file_size_bytes,
        file_hash=stored.file_hash,
        storage_key=intake_key,
        malware_scan_status=DocumentMalwareScanStatus.CLEAN,
        malware_scanned_at=scanned_at,
        status=ClaimIntakeStatus.PROCESSING,
    )
    job = ClaimIntakeProcessingJob(
        organization_id=current_user.organization_id,
        intake_draft_id=draft.id,
        requested_by_id=current_user.id,
        status=ProcessingJobStatus.PENDING,
        available_at=datetime.now(UTC),
        max_attempts=settings.processing_max_attempts,
    )
    db.add_all([draft, job])
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="CREATE_CLAIM_INTAKE_DRAFT",
        entity_type="claim_intake_draft",
        entity_id=draft.id,
        new_values={
            "filename": filename,
            "file_hash": draft.file_hash,
            "malware_scan_status": "clean",
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        storage.delete_physical(intake_key)
        raise HTTPException(status_code=409, detail="This intake source already exists.") from exc
    db.refresh(draft)
    return draft


def get_intake_draft(db: Session, *, draft_id: UUID, organization_id: UUID) -> ClaimIntakeDraft:
    draft = db.scalar(
        select(ClaimIntakeDraft).where(
            ClaimIntakeDraft.id == draft_id,
            ClaimIntakeDraft.organization_id == organization_id,
        )
    )
    if draft is None:
        raise ClaimIntakeNotFoundError("Claim intake draft not found")
    return draft


def list_intake_drafts(db: Session, *, organization_id: UUID) -> tuple[list[ClaimIntakeDraft], int]:
    condition = ClaimIntakeDraft.organization_id == organization_id
    items = list(
        db.scalars(
            select(ClaimIntakeDraft).where(condition).order_by(ClaimIntakeDraft.created_at.desc())
        )
    )
    total = int(db.scalar(select(func.count(ClaimIntakeDraft.id)).where(condition)) or 0)
    return items, total


def claim_next_intake_job(db: Session, *, worker_id: str) -> ClaimIntakeProcessingJob | None:
    now = datetime.now(UTC)
    stmt = (
        select(ClaimIntakeProcessingJob)
        .where(
            ClaimIntakeProcessingJob.status == ProcessingJobStatus.PENDING,
            ClaimIntakeProcessingJob.available_at <= now,
            ClaimIntakeProcessingJob.attempt_count < ClaimIntakeProcessingJob.max_attempts,
        )
        .order_by(ClaimIntakeProcessingJob.created_at.asc())
        .limit(1)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = ProcessingJobStatus.RUNNING
    job.attempt_count += 1
    job.locked_at = now
    job.locked_by = worker_id[:120]
    job.started_at = job.started_at or now
    db.commit()
    db.refresh(job)
    return job


def process_intake_job(db: Session, *, job: ClaimIntakeProcessingJob) -> None:
    draft = db.get(ClaimIntakeDraft, job.intake_draft_id)
    if draft is None or draft.status != ClaimIntakeStatus.PROCESSING:
        job.status = ProcessingJobStatus.FAILED
        job.last_error = "Intake draft is unavailable or no longer processing."
        job.completed_at = datetime.now(UTC)
        db.commit()
        return
    try:
        extraction = extract_document_text(
            _storage().path_for(draft.storage_key),
            enable_ocr=settings.ocr_enabled,
            ocr_languages=settings.ocr_languages,
            ocr_max_pages=settings.ocr_max_pages,
            ocr_timeout_seconds=settings.ocr_timeout_seconds,
        )
        text = extraction.combined_text.strip()
        if extraction.requires_ocr or len(text) < 10:
            raise ValueError("No reviewable text was extracted from the intake source.")
        classification, confidence, rule = _classification(draft.original_filename, text)
        fields, evidence = extract_intake_candidates(text)
        draft.extraction_method = extraction.method
        draft.ocr_languages = settings.ocr_languages if "tesseract" in extraction.method else None
        draft.extracted_text = text[:200000]
        draft.extracted_segments = [
            {
                "locator_type": segment.locator_type,
                "locator_value": segment.locator_value,
                "text": segment.text[:50000],
            }
            for segment in extraction.segments
        ]
        draft.extraction_warnings = extraction.warnings
        draft.classification_candidate = classification
        draft.classification_confidence = confidence
        draft.classification_rule = rule
        draft.extracted_fields = fields
        draft.field_evidence = evidence
        draft.status = ClaimIntakeStatus.PENDING_REVIEW
        job.status = ProcessingJobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.locked_at = None
        job.locked_by = None
        job.last_error = None
        job.result = {
            "extraction_method": extraction.method,
            "char_count": len(text),
            "classification_candidate": classification,
            "classification_confidence": confidence,
        }
        write_audit_log(
            db,
            organization_id=draft.organization_id,
            user_id=job.requested_by_id,
            action="EXTRACT_CLAIM_INTAKE_CANDIDATES",
            entity_type="claim_intake_draft",
            entity_id=draft.id,
            new_values=job.result,
            details="Candidates require human review and are not authoritative claim facts.",
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the durable job records extractor/runtime failures
        db.rollback()
        draft = db.get(ClaimIntakeDraft, job.intake_draft_id)
        job = db.get(ClaimIntakeProcessingJob, job.id)
        if draft is not None:
            draft.status = ClaimIntakeStatus.FAILED
            draft.extraction_warnings = [str(exc)[:1000]]
        if job is not None:
            job.status = ProcessingJobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.locked_at = None
            job.locked_by = None
            job.last_error = str(exc)[:2000]
        db.commit()


def approve_intake_draft(
    db: Session,
    *,
    draft_id: UUID,
    organization_id: UUID,
    current_user: User,
    payload: ClaimIntakeApprove,
) -> tuple[ClaimIntakeDraft, Claim]:
    stmt = select(ClaimIntakeDraft).where(
        ClaimIntakeDraft.id == draft_id,
        ClaimIntakeDraft.organization_id == organization_id,
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    draft = db.scalar(stmt)
    if draft is None:
        raise ClaimIntakeNotFoundError("Claim intake draft not found")
    if draft.status == ClaimIntakeStatus.APPROVED and draft.approved_claim_id is not None:
        return draft, get_claim(
            db, claim_id=draft.approved_claim_id, organization_id=organization_id
        )
    if draft.status != ClaimIntakeStatus.PENDING_REVIEW:
        raise ClaimIntakeStateError(f"Draft cannot be approved from status {draft.status.value}.")
    if draft.malware_scan_status != DocumentMalwareScanStatus.CLEAN:
        raise ClaimIntakeStateError("Only a clean intake source can create a claim.")

    original_intake_key = draft.storage_key
    document_id = uuid4()
    suffix = Path(original_intake_key).suffix.lower()
    active_key = ""
    storage = _storage()
    promoted = False
    try:
        claim = create_claim(
            db,
            organization_id=organization_id,
            current_user=current_user,
            payload=payload.claim,
        )
        active_key = _document_key(
            organization_id=organization_id,
            claim_id=claim.id,
            document_id=document_id,
            suffix=suffix,
        )
        storage.promote(original_intake_key, active_key)
        promoted = True
        document = Document(
            id=document_id,
            organization_id=organization_id,
            claim_id=claim.id,
            uploaded_by_id=draft.uploaded_by_id,
            filename=draft.original_filename,
            original_filename=draft.original_filename,
            document_type=payload.document_type.strip(),
            mime_type=draft.mime_type,
            file_size_bytes=draft.file_size_bytes,
            file_hash=draft.file_hash,
            storage_key=active_key,
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
            malware_scanned_at=draft.malware_scanned_at,
        )
        db.add(document)
        db.flush()
        text_extraction = DocumentTextExtraction(
            organization_id=organization_id,
            document_id=document.id,
            extraction_method=draft.extraction_method or "claim-intake",
            extractor_version=EXTRACTOR_VERSION,
            char_count=len(draft.extracted_text or ""),
            segment_count=len(draft.extracted_segments or []),
            requires_ocr=False,
            text_hash=sha256((draft.extracted_text or "").encode("utf-8")).hexdigest(),
            warnings=draft.extraction_warnings,
        )
        db.add(text_extraction)
        db.flush()
        for index, segment in enumerate(draft.extracted_segments or []):
            segment_text = str(segment.get("text") or "")
            db.add(
                DocumentTextSegment(
                    organization_id=organization_id,
                    document_id=document.id,
                    extraction_id=text_extraction.id,
                    segment_index=index,
                    locator_type=str(segment.get("locator_type") or "document")[:30],
                    locator_value=str(segment.get("locator_value") or "body")[:100],
                    text=segment_text,
                    char_count=len(segment_text),
                )
            )

        draft.status = ClaimIntakeStatus.APPROVED
        draft.approved_claim_id = claim.id
        draft.source_document_id = document.id
        draft.reviewed_by_id = current_user.id
        draft.reviewed_at = datetime.now(UTC)
        draft.review_note = payload.review_note
        draft.review_payload = payload.model_dump(mode="json")
        draft.storage_key = active_key
        write_audit_log(
            db,
            organization_id=organization_id,
            user_id=current_user.id,
            action="APPROVE_CLAIM_INTAKE_DRAFT",
            entity_type="claim_intake_draft",
            entity_id=draft.id,
            new_values={"claim_id": str(claim.id), "document_id": str(document.id)},
            details=payload.review_note,
        )
        write_audit_log(
            db,
            organization_id=organization_id,
            user_id=current_user.id,
            action="CREATE_CLAIM_FROM_INTAKE",
            entity_type="claim",
            entity_id=claim.id,
            new_values={
                "claim_reference": claim.claim_reference,
                "intake_draft_id": str(draft.id),
                "source_document_id": str(document.id),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        if promoted:
            try:
                storage.promote(active_key, original_intake_key)
            except (StorageError, FileNotFoundError):
                pass
        raise
    db.refresh(draft)
    return draft, get_claim(db, claim_id=claim.id, organization_id=organization_id)


def reject_intake_draft(
    db: Session,
    *,
    draft: ClaimIntakeDraft,
    current_user: User,
    reason: str,
) -> ClaimIntakeDraft:
    if draft.status != ClaimIntakeStatus.PENDING_REVIEW:
        raise ClaimIntakeStateError(f"Draft cannot be rejected from status {draft.status.value}.")
    draft.status = ClaimIntakeStatus.REJECTED
    draft.reviewed_by_id = current_user.id
    draft.reviewed_at = datetime.now(UTC)
    draft.review_note = reason
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="REJECT_CLAIM_INTAKE_DRAFT",
        entity_type="claim_intake_draft",
        entity_id=draft.id,
        details=reason,
    )
    db.commit()
    db.refresh(draft)
    return draft
