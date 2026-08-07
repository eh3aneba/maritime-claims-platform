from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.gateway.base import AIProvider, AIProviderUnavailable, AIRequest
from app.ai.gateway.registry import get_ai_provider
from app.ai.prompts.ce_report import (
    PROMPT_NAME,
    PROMPT_VERSION,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    SYSTEM_INSTRUCTIONS,
)
from app.ai.schemas.ce_report import ChiefEngineerReportExtraction, SourcedBoolean, SourcedString
from app.core.config import get_settings
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import Document
from app.modules.intelligence.models import AIRun, AIRunStatus, AISemanticKind, DocumentExtraction
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment

settings = get_settings()
TASK_CE_REPORT = "chief_engineer_report_extract"


def build_segmented_input(segments: list[DocumentTextSegment], *, max_chars: int) -> tuple[str, list[str]]:
    blocks: list[str] = []
    warnings: list[str] = []
    used = 0
    for segment in sorted(segments, key=lambda item: item.segment_index):
        header = f"[SEGMENT {segment.segment_index} | {segment.locator_type}={segment.locator_value}]\n"
        block = header + segment.text.strip() + "\n"
        if used + len(block) > max_chars:
            warnings.append(
                f"Input truncated at {max_chars} characters; later source segments were not sent to the AI provider."
            )
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks), warnings


def create_ai_run(
    db: Session,
    *,
    document: Document,
    requested_by_id: UUID | None,
    provider_name: str,
    model: str,
    input_text: str,
    warnings: list[str],
) -> AIRun:
    run = AIRun(
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        requested_by_id=requested_by_id,
        task=TASK_CE_REPORT,
        status=AIRunStatus.PENDING,
        provider=provider_name,
        model=model,
        prompt_name=PROMPT_NAME,
        prompt_version=PROMPT_VERSION,
        schema_name=SCHEMA_NAME,
        schema_version=SCHEMA_VERSION,
        input_text_hash=hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
        input_char_count=len(input_text),
        warnings=warnings or None,
    )
    db.add(run)
    db.flush()
    return run


def run_ce_report_intelligence(
    db: Session,
    *,
    document: Document,
    requested_by_id: UUID | None,
    provider: AIProvider | None = None,
) -> AIRun:
    text_extraction = db.scalar(
        select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == document.id,
            DocumentTextExtraction.organization_id == document.organization_id,
        )
    )
    if text_extraction is None:
        raise ValueError("Document text extraction has not completed.")
    if text_extraction.requires_ocr:
        raise ValueError("Document requires OCR before AI extraction can run.")
    if text_extraction.char_count <= 0:
        raise ValueError("Document contains no extracted text.")

    segments = list(
        db.scalars(
            select(DocumentTextSegment)
            .where(
                DocumentTextSegment.document_id == document.id,
                DocumentTextSegment.organization_id == document.organization_id,
            )
            .order_by(DocumentTextSegment.segment_index.asc())
        )
    )
    input_text, warnings = build_segmented_input(segments, max_chars=settings.ai_max_input_chars)
    if not input_text.strip():
        raise ValueError("Document contains no usable source segments.")

    provider = provider or get_ai_provider()
    provider_name = provider.name
    model = getattr(provider, "_model", None) or settings.ai_model or "unknown"
    run = create_ai_run(
        db,
        document=document,
        requested_by_id=requested_by_id,
        provider_name=provider_name,
        model=model,
        input_text=input_text,
        warnings=warnings,
    )
    run.status = AIRunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    db.commit()

    try:
        request = AIRequest(
            task=TASK_CE_REPORT,
            system_instructions=SYSTEM_INSTRUCTIONS,
            input_text=input_text,
            schema_name=SCHEMA_NAME,
            output_schema=ChiefEngineerReportExtraction.model_json_schema(),
            metadata={
                "document_id": str(document.id),
                "claim_id": str(document.claim_id),
                "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION,
            },
        )
        response = provider.generate(request)
        if response.structured_output is None:
            raise RuntimeError("AI provider did not return structured output.")
        parsed = ChiefEngineerReportExtraction.model_validate(response.structured_output)

        db.execute(delete(DocumentExtraction).where(DocumentExtraction.ai_run_id == run.id))
        run.provider = response.provider
        run.model = response.model
        run.raw_output = parsed.model_dump(mode="json")
        run.raw_response_id = response.raw_response_id
        run.usage = response.usage or None
        run.document_type_candidate = parsed.classification.document_type
        run.classification_confidence = Decimal(str(parsed.classification.confidence))

        run_warnings = list(run.warnings or [])
        if parsed.classification.document_type == "chief_engineer_report":
            _persist_ce_extractions(
                db,
                run=run,
                parsed=parsed,
                segments=segments,
                run_warnings=run_warnings,
            )
        else:
            run_warnings.append(
                "Document was not classified as a Chief Engineer Report; field extraction rows were not persisted."
            )

        run.warnings = run_warnings or None
        run.status = AIRunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.error = None
        write_audit_log(
            db,
            organization_id=document.organization_id,
            user_id=requested_by_id,
            action="RUN_CE_REPORT_AI_EXTRACTION",
            entity_type="document",
            entity_id=document.id,
            new_values={
                "ai_run_id": str(run.id),
                "classification": run.document_type_candidate,
                "classification_confidence": float(run.classification_confidence or 0),
                "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "provider": run.provider,
                "model": run.model,
            },
        )
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        failed = db.get(AIRun, run.id)
        if failed is not None:
            failed.status = AIRunStatus.FAILED
            failed.completed_at = datetime.now(UTC)
            failed.error = str(exc)[:4000]
            db.commit()
        if isinstance(exc, AIProviderUnavailable):
            raise
        raise


def _persist_ce_extractions(
    db: Session,
    *,
    run: AIRun,
    parsed: ChiefEngineerReportExtraction,
    segments: list[DocumentTextSegment],
    run_warnings: list[str],
) -> None:
    scalar_fields: list[tuple[str, AISemanticKind, SourcedString | SourcedBoolean]] = [
        ("identification.vessel_name", AISemanticKind.FACT, parsed.identification.vessel_name),
        ("identification.imo_number", AISemanticKind.FACT, parsed.identification.imo_number),
        ("identification.report_date", AISemanticKind.FACT, parsed.identification.report_date),
        ("identification.author_name", AISemanticKind.FACT, parsed.identification.author_name),
        ("identification.author_rank", AISemanticKind.FACT, parsed.identification.author_rank),
        ("incident.date", AISemanticKind.FACT, parsed.incident.date),
        ("incident.time", AISemanticKind.FACT, parsed.incident.time),
        ("incident.timezone", AISemanticKind.FACT, parsed.incident.timezone),
        ("incident.location", AISemanticKind.FACT, parsed.incident.location),
        ("incident.voyage_from", AISemanticKind.FACT, parsed.incident.voyage_from),
        ("incident.voyage_to", AISemanticKind.FACT, parsed.incident.voyage_to),
        ("incident.cargo_status", AISemanticKind.FACT, parsed.incident.cargo_status),
        ("incident.first_observation", AISemanticKind.FACT, parsed.incident.first_observation),
        ("equipment.type", AISemanticKind.FACT, parsed.equipment.equipment_type),
        ("equipment.name", AISemanticKind.FACT, parsed.equipment.equipment_name),
        ("equipment.maker", AISemanticKind.FACT, parsed.equipment.maker),
        ("equipment.model", AISemanticKind.FACT, parsed.equipment.model),
        ("equipment.serial_number", AISemanticKind.FACT, parsed.equipment.serial_number),
        ("operational_impact.engine_stopped", AISemanticKind.FACT, parsed.operational_impact.engine_stopped),
        ("operational_impact.load_reduced", AISemanticKind.FACT, parsed.operational_impact.load_reduced),
        ("operational_impact.speed_reduced", AISemanticKind.FACT, parsed.operational_impact.speed_reduced),
        ("operational_impact.immobilized", AISemanticKind.FACT, parsed.operational_impact.immobilized),
        ("operational_impact.deviation", AISemanticKind.FACT, parsed.operational_impact.deviation),
        ("operational_impact.towage", AISemanticKind.FACT, parsed.operational_impact.towage),
    ]
    for field_path, semantic_kind, item in scalar_fields:
        if item.value is not None:
            _persist_item(db, run=run, field_path=field_path, semantic_kind=semantic_kind, item=item, segments=segments, run_warnings=run_warnings)

    for index, item in enumerate(parsed.symptoms):
        _persist_item(db, run=run, field_path=f"symptoms[{index}]", semantic_kind=AISemanticKind.FACT, item=item, segments=segments, run_warnings=run_warnings)
    for index, item in enumerate(parsed.immediate_actions):
        _persist_item(db, run=run, field_path=f"immediate_actions[{index}]", semantic_kind=AISemanticKind.FACT, item=item, segments=segments, run_warnings=run_warnings)
    for index, item in enumerate(parsed.suspected_cause_opinions):
        _persist_item(db, run=run, field_path=f"suspected_cause_opinions[{index}]", semantic_kind=AISemanticKind.OPINION, item=item, segments=segments, run_warnings=run_warnings)
    for index, item in enumerate(parsed.recommendations):
        _persist_item(db, run=run, field_path=f"recommendations[{index}]", semantic_kind=AISemanticKind.OPINION, item=item, segments=segments, run_warnings=run_warnings)


def _persist_item(
    db: Session,
    *,
    run: AIRun,
    field_path: str,
    semantic_kind: AISemanticKind,
    item: SourcedString | SourcedBoolean,
    segments: list[DocumentTextSegment],
    run_warnings: list[str],
) -> None:
    if item.value is None:
        return
    segment = None
    warnings: list[str] = []
    source_verified = False
    if item.source.segment_index is None:
        warnings.append("No source segment was supplied for a non-null value.")
    else:
        segment = next((candidate for candidate in segments if candidate.segment_index == item.source.segment_index), None)
        if segment is None:
            warnings.append(f"Source segment {item.source.segment_index} does not exist in the supplied document text.")
        elif not item.source.quote:
            warnings.append("No source quote was supplied for a non-null value.")
        else:
            source_verified = _quote_in_text(item.source.quote, segment.text)
            if not source_verified:
                warnings.append("Source quote could not be verified against the referenced segment.")
    if warnings:
        run_warnings.append(f"{field_path}: " + " ".join(warnings))

    db.add(
        DocumentExtraction(
            organization_id=run.organization_id,
            claim_id=run.claim_id,
            document_id=run.document_id,
            ai_run_id=run.id,
            source_segment_id=segment.id if segment is not None else None,
            field_path=field_path,
            semantic_kind=semantic_kind,
            raw_value=item.value,
            normalized_value=_normalize_value(field_path, item.value),
            confidence=Decimal(str(item.confidence)),
            source_locator_type=segment.locator_type if segment is not None else None,
            source_locator_value=segment.locator_value if segment is not None else None,
            source_quote=item.source.quote,
            source_verified=source_verified,
            validation_warnings=warnings or None,
        )
    )


def _quote_in_text(quote: str, text: str) -> bool:
    normalize = lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    return normalize(quote) in normalize(text)


def _normalize_value(field_path: str, value: Any) -> Any:
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value).strip()
        if field_path == "identification.imo_number":
            digits = re.sub(r"\D", "", normalized)
            if len(digits) == 7:
                return digits
        return normalized
    return value


def get_latest_ai_result(db: Session, *, document_id: UUID, organization_id: UUID) -> tuple[AIRun | None, list[DocumentExtraction]]:
    run = db.scalar(
        select(AIRun)
        .where(AIRun.document_id == document_id, AIRun.organization_id == organization_id)
        .order_by(AIRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return None, []
    extractions = list(
        db.scalars(
            select(DocumentExtraction)
            .where(DocumentExtraction.ai_run_id == run.id, DocumentExtraction.organization_id == organization_id)
            .order_by(DocumentExtraction.field_path.asc())
        )
    )
    return run, extractions
