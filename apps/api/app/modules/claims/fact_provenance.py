from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.users.models import User

AI_REVIEW_PROVENANCE = "ai_review"
INTAKE_REVIEW_PROVENANCE = "intake_review"

# Intake creates the claim itself, so these are the stable canonical claim fields
# represented by the human-approved form. Null optional values are omitted rather
# than creating noisy null facts.
_INTAKE_CLAIM_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("vessel_id", None),
    ("incident_date", "incident_date"),
    ("notification_date", "notification_date"),
    ("incident_description", "incident_description"),
    ("external_reference", "external_reference"),
    ("claim_type", "claim_type"),
    ("claim_subtype", "claim_subtype"),
    ("priority", "priority"),
    ("estimated_loss", None),
    ("currency", "currency"),
    ("handler_id", None),
)


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _values_match(approved_value: Any, candidate_value: Any) -> bool:
    return _json_value(approved_value) == _json_value(candidate_value)


def _supported_segment_id(
    *,
    approved_value: Any,
    candidate_key: str | None,
    extracted_fields: dict[str, Any],
    field_evidence: dict[str, Any],
    segments: list[DocumentTextSegment],
) -> UUID | None:
    """Return a segment only when direct evidence supports the approved value.

    Human edits, defaults and relationship identifiers deliberately remain at
    document/text-extraction provenance only. We never infer a segment from a
    nearby value or fabricate an evidence pointer.
    """

    if candidate_key is None:
        return None
    candidate_value = extracted_fields.get(candidate_key)
    if candidate_value is None or not _values_match(approved_value, candidate_value):
        return None
    evidence = field_evidence.get(candidate_key)
    if not isinstance(evidence, dict):
        return None
    quote = _normalized_text(evidence.get("quote"))
    if not quote:
        return None
    for segment in segments:
        if quote in _normalized_text(segment.text):
            return segment.id
    return None


def _current_fact(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    field_path: str,
) -> ClaimFact | None:
    return db.scalar(
        select(ClaimFact).where(
            ClaimFact.organization_id == organization_id,
            ClaimFact.claim_id == claim_id,
            ClaimFact.field_path == field_path,
        )
    )


def promote_human_approved_intake_facts(
    db: Session,
    *,
    claim: Claim,
    text_extraction: DocumentTextExtraction,
    segments: list[DocumentTextSegment],
    source_document_id: UUID,
    reviewer: User,
    extracted_fields: dict[str, Any] | None,
    field_evidence: dict[str, Any] | None,
    approved_at: datetime | None = None,
) -> list[ClaimFact]:
    """Promote one approved intake form into the canonical ClaimFact table.

    This function accepts only the already-human-approved/persisted Claim model;
    deterministic intake candidates are used solely to decide whether a direct
    source segment can be cited. No AI run or DocumentExtraction is created.
    """

    if claim.organization_id != reviewer.organization_id:
        raise ValueError("Claim and reviewer must belong to the same organization.")
    if text_extraction.organization_id != claim.organization_id:
        raise ValueError("Text extraction does not belong to the claim organization.")
    if text_extraction.document_id != source_document_id:
        raise ValueError("Text extraction does not belong to the intake source document.")
    if any(
        segment.organization_id != claim.organization_id
        or segment.document_id != source_document_id
        or segment.extraction_id != text_extraction.id
        for segment in segments
    ):
        raise ValueError("Intake source segments do not share the approved text-extraction lineage.")

    extracted_fields = extracted_fields or {}
    field_evidence = field_evidence or {}
    approved_at = approved_at or datetime.now(UTC)
    promoted: list[ClaimFact] = []

    for attribute, candidate_key in _INTAKE_CLAIM_FIELDS:
        approved_value = _json_value(getattr(claim, attribute))
        if approved_value is None:
            continue
        field_path = f"claim.{attribute}"
        source_segment_id = _supported_segment_id(
            approved_value=approved_value,
            candidate_key=candidate_key,
            extracted_fields=extracted_fields,
            field_evidence=field_evidence,
            segments=segments,
        )
        fact = _current_fact(
            db,
            organization_id=claim.organization_id,
            claim_id=claim.id,
            field_path=field_path,
        )

        if fact is not None:
            # A repeated intake approval should be a semantic no-op. The normal
            # approval path already short-circuits, but this guard also protects
            # against accidental direct re-entry into the promotion helper.
            if (
                fact.value == approved_value
                and fact.provenance_kind == INTAKE_REVIEW_PROVENANCE
                and fact.source_extraction_id is None
                and fact.source_text_extraction_id == text_extraction.id
                and fact.source_document_id == source_document_id
                and fact.source_segment_id == source_segment_id
                and fact.approved_by_id == reviewer.id
            ):
                promoted.append(fact)
                continue
            old_values = {
                "value": fact.value,
                "provenance_kind": fact.provenance_kind,
                "source_extraction_id": str(fact.source_extraction_id) if fact.source_extraction_id else None,
                "source_text_extraction_id": str(fact.source_text_extraction_id) if fact.source_text_extraction_id else None,
                "source_document_id": str(fact.source_document_id),
                "source_segment_id": str(fact.source_segment_id) if fact.source_segment_id else None,
                "version": fact.version,
            }
            fact.value = approved_value
            fact.provenance_kind = INTAKE_REVIEW_PROVENANCE
            fact.source_extraction_id = None
            fact.source_text_extraction_id = text_extraction.id
            fact.source_document_id = source_document_id
            fact.source_segment_id = source_segment_id
            fact.approved_by_id = reviewer.id
            fact.approved_at = approved_at
            fact.version += 1
            write_audit_log(
                db,
                organization_id=claim.organization_id,
                user_id=reviewer.id,
                action="UPDATE_APPROVED_CLAIM_FACT",
                entity_type="claim_fact",
                entity_id=fact.id,
                old_values=old_values,
                new_values={
                    "field_path": field_path,
                    "value": approved_value,
                    "provenance_kind": INTAKE_REVIEW_PROVENANCE,
                    "source_text_extraction_id": str(text_extraction.id),
                    "source_document_id": str(source_document_id),
                    "source_segment_id": str(source_segment_id) if source_segment_id else None,
                    "version": fact.version,
                },
                details="Canonical fact refreshed from a human-approved claim intake.",
            )
        else:
            fact = ClaimFact(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                field_path=field_path,
                value=approved_value,
                provenance_kind=INTAKE_REVIEW_PROVENANCE,
                source_extraction_id=None,
                source_text_extraction_id=text_extraction.id,
                source_document_id=source_document_id,
                source_segment_id=source_segment_id,
                approved_by_id=reviewer.id,
                approved_at=approved_at,
                version=1,
            )
            db.add(fact)
            db.flush()
            write_audit_log(
                db,
                organization_id=claim.organization_id,
                user_id=reviewer.id,
                action="CREATE_APPROVED_CLAIM_FACT",
                entity_type="claim_fact",
                entity_id=fact.id,
                new_values={
                    "field_path": field_path,
                    "value": approved_value,
                    "provenance_kind": INTAKE_REVIEW_PROVENANCE,
                    "source_text_extraction_id": str(text_extraction.id),
                    "source_document_id": str(source_document_id),
                    "source_segment_id": str(source_segment_id) if source_segment_id else None,
                    "version": fact.version,
                },
                details="Canonical fact created from a human-approved claim intake.",
            )
        promoted.append(fact)

    db.flush()
    return promoted
