from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.intelligence.models import AIFeedback, AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.processing.models import DocumentTextSegment
from app.modules.review.schemas import ReviewGroup, ReviewQueueItem
from app.modules.users.models import User
from app.modules.vessels.models import Vessel

# Bulk approval is intentionally narrower than individual review. These are
# identity/metadata fields where a verified high-confidence extraction presents
# relatively low decision risk. Incident timing, causation and operational impact
# always require individual attention.
BULK_APPROVE_FIELDS = {
    "identification.vessel_name",
    "identification.imo_number",
    "identification.report_date",
    "identification.author_name",
    "identification.author_rank",
    "equipment.type",
    "equipment.name",
    "equipment.maker",
    "equipment.model",
    "equipment.serial_number",
}

# These path fragments are never promoted to authoritative claim facts even if a
# future AI schema accidentally labels them as FACT. They may still be human-reviewed
# as extracted evidence/opinion.
NON_PROMOTABLE_PATH_FRAGMENTS = {
    "cause",
    "coverage",
    "liability",
    "fraud",
    "reserve",
    "settlement",
    "recoverability",
    "decision",
    "accepted",
    "rejected",
    "payable",
    "indemnity",
    "policy.",
    "contract.",
    "engine_log.events[",
    "reported_events[",
    "pms.records[",
    "workshop.damage_findings[",
    "workshop.repair_options[",
    "workshop.recommendations[",
    "quotation.",
    "invoice.",
}



_GROUP_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(policy\.[a-z_]+\[\d+\])"), "policy_term"),
    (re.compile(r"^(engine_log\.events\[\d+\])\."), "engine_log_row"),
    (re.compile(r"^(pms\.records\[\d+\])\."), "pms_row"),
    (re.compile(r"^((?:quotation|invoice)\.line_items\[\d+\])\."), "commercial_line_item"),
    (re.compile(r"^(workshop\.damage_findings\[\d+\])\."), "workshop_finding"),
    (re.compile(r"^(workshop\.repair_options\[\d+\])\."), "workshop_repair_option"),
    (re.compile(r"^(reported_events\[\d+\])\."), "reported_event"),
)

_GROUP_LABELS = {
    "policy_term": "Policy / contract term",
    "engine_log_row": "Engine Log row",
    "pms_row": "PMS job row",
    "commercial_line_item": "Commercial line item",
    "workshop_finding": "Workshop damage finding",
    "workshop_repair_option": "Workshop repair option",
    "reported_event": "Reported event",
    "single_field": "Single field",
}


def review_group_key(field_path: str) -> tuple[str, str]:
    for pattern, group_type in _GROUP_PATTERNS:
        match = pattern.match(field_path)
        if match:
            return match.group(1), group_type
    return field_path, "single_field"


def _attention_reasons(items: list[ReviewQueueItem]) -> list[str]:
    reasons: list[str] = []
    if any(not item.source_verified for item in items):
        reasons.append("Unverified source citation")
    if any(item.validation_warnings for item in items):
        reasons.append("Validation warning")
    if any(item.confidence < Decimal("0.800") for item in items):
        reasons.append("Low confidence")
    elif any(item.confidence < Decimal("0.900") for item in items):
        reasons.append("Medium confidence")
    if any(item.semantic_kind in {AISemanticKind.OPINION, AISemanticKind.INFERENCE} for item in items):
        reasons.append("Opinion or inference requires judgment")
    return reasons


def list_review_groups(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID | None = None,
    document_id: UUID | None = None,
    human_status: AIReviewStatus | None = AIReviewStatus.PENDING,
    attention_only: bool = False,
    limit_groups: int = 100,
) -> list[ReviewGroup]:
    items, _ = list_review_queue(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        human_status=human_status,
        limit=500,
        offset=0,
    )
    buckets: dict[tuple[UUID, UUID, str], tuple[str, list[ReviewQueueItem]]] = {}
    for item in items:
        key, group_type = review_group_key(item.field_path)
        bucket_key = (item.claim_id, item.document_id, key)
        if bucket_key not in buckets:
            buckets[bucket_key] = (group_type, [])
        buckets[bucket_key][1].append(item)

    groups: list[ReviewGroup] = []
    for (_, _, key), (group_type, group_items) in buckets.items():
        group_items.sort(key=lambda item: item.field_path)
        reasons = _attention_reasons(group_items)
        pending = [item for item in group_items if item.human_status == AIReviewStatus.PENDING]
        group = ReviewGroup(
            group_key=key,
            group_type=group_type,
            label=f"{_GROUP_LABELS[group_type]} · {key}",
            claim_id=group_items[0].claim_id,
            claim_reference=group_items[0].claim_reference,
            vessel_name=group_items[0].vessel_name,
            document_id=group_items[0].document_id,
            document_name=group_items[0].document_name,
            items=group_items,
            pending_count=len(pending),
            needs_attention=bool(reasons),
            attention_reasons=reasons,
            group_approvable=bool(pending),
            requires_reason=any(not item.source_verified for item in pending),
            min_confidence=min(item.confidence for item in group_items),
        )
        if not attention_only or group.needs_attention:
            groups.append(group)

    groups.sort(
        key=lambda group: (
            0 if group.needs_attention else 1,
            float(group.min_confidence),
            group.document_name.lower(),
            group.group_key,
        )
    )
    return groups[:limit_groups]


def validate_same_review_group(extractions: list[DocumentExtraction]) -> tuple[str, str]:
    if not extractions:
        raise ValueError("Grouped review requires at least one extraction.")
    claim_ids = {row.claim_id for row in extractions}
    document_ids = {row.document_id for row in extractions}
    keys = {review_group_key(row.field_path) for row in extractions}
    if len(claim_ids) != 1 or len(document_ids) != 1 or len(keys) != 1:
        raise ValueError("Grouped review may only contain fields from the same review row/group.")
    return next(iter(keys))

def is_bulk_approvable(extraction: DocumentExtraction) -> bool:
    return (
        extraction.human_status == AIReviewStatus.PENDING
        and extraction.semantic_kind == AISemanticKind.FACT
        and extraction.field_path in BULK_APPROVE_FIELDS
        and extraction.source_verified
        and extraction.source_segment_id is not None
        and extraction.confidence >= Decimal("0.900")
    )


def is_promotable(extraction: DocumentExtraction) -> bool:
    if extraction.semantic_kind != AISemanticKind.FACT:
        return False
    path = extraction.field_path.lower()
    return not any(fragment in path for fragment in NON_PROMOTABLE_PATH_FRAGMENTS)


def _queue_query(*, organization_id: UUID):
    return (
        select(DocumentExtraction, Claim, Vessel, Document)
        .join(Claim, Claim.id == DocumentExtraction.claim_id)
        .join(Vessel, Vessel.id == Claim.vessel_id)
        .join(Document, Document.id == DocumentExtraction.document_id)
        .where(
            DocumentExtraction.organization_id == organization_id,
            Claim.organization_id == organization_id,
            Document.organization_id == organization_id,
            Claim.deleted_at.is_(None),
            Document.deleted_at.is_(None),
        )
    )


def list_review_queue(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID | None = None,
    document_id: UUID | None = None,
    human_status: AIReviewStatus | None = AIReviewStatus.PENDING,
    semantic_kind: AISemanticKind | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ReviewQueueItem], int]:
    query = _queue_query(organization_id=organization_id)
    if claim_id is not None:
        query = query.where(DocumentExtraction.claim_id == claim_id)
    if document_id is not None:
        query = query.where(DocumentExtraction.document_id == document_id)
    if human_status is not None:
        query = query.where(DocumentExtraction.human_status == human_status)
    if semantic_kind is not None:
        query = query.where(DocumentExtraction.semantic_kind == semantic_kind)

    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = int(db.scalar(count_query) or 0)
    rows = db.execute(
        query.order_by(DocumentExtraction.created_at.asc(), DocumentExtraction.field_path.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        ReviewQueueItem(
            extraction_id=extraction.id,
            claim_id=claim.id,
            claim_reference=claim.claim_reference,
            vessel_name=vessel.name,
            document_id=document.id,
            document_name=document.original_filename,
            field_path=extraction.field_path,
            semantic_kind=extraction.semantic_kind,
            ai_value=extraction.raw_value,
            normalized_value=extraction.normalized_value,
            confidence=extraction.confidence,
            source_locator_type=extraction.source_locator_type,
            source_locator_value=extraction.source_locator_value,
            source_quote=extraction.source_quote,
            source_verified=extraction.source_verified,
            validation_warnings=extraction.validation_warnings,
            human_status=extraction.human_status,
            approved_value=extraction.approved_value,
            reviewed_at=extraction.reviewed_at,
            bulk_approvable=is_bulk_approvable(extraction),
            created_at=extraction.created_at,
        )
        for extraction, claim, vessel, document in rows
    ]
    return items, total


def get_extraction_for_tenant(db: Session, *, extraction_id: UUID, organization_id: UUID) -> DocumentExtraction | None:
    return db.scalar(
        select(DocumentExtraction)
        .join(Claim, Claim.id == DocumentExtraction.claim_id)
        .join(Document, Document.id == DocumentExtraction.document_id)
        .where(
            DocumentExtraction.id == extraction_id,
            DocumentExtraction.organization_id == organization_id,
            Claim.organization_id == organization_id,
            Document.organization_id == organization_id,
            Claim.deleted_at.is_(None),
            Document.deleted_at.is_(None),
        )
    )


def get_source_segment_for_extraction(
    db: Session,
    *,
    extraction: DocumentExtraction,
    organization_id: UUID,
) -> DocumentTextSegment | None:
    if extraction.source_segment_id is None:
        return None
    return db.scalar(
        select(DocumentTextSegment).where(
            DocumentTextSegment.id == extraction.source_segment_id,
            DocumentTextSegment.organization_id == organization_id,
            DocumentTextSegment.document_id == extraction.document_id,
        )
    )


def get_feedback_history(db: Session, *, extraction_id: UUID, organization_id: UUID) -> list[AIFeedback]:
    return list(
        db.scalars(
            select(AIFeedback)
            .where(AIFeedback.extraction_id == extraction_id, AIFeedback.organization_id == organization_id)
            .order_by(AIFeedback.created_at.asc(), AIFeedback.id.asc())
        )
    )


def get_current_claim_fact(
    db: Session,
    *,
    claim_id: UUID,
    field_path: str,
    organization_id: UUID,
) -> ClaimFact | None:
    return db.scalar(
        select(ClaimFact).where(
            ClaimFact.organization_id == organization_id,
            ClaimFact.claim_id == claim_id,
            ClaimFact.field_path == field_path,
        )
    )


def review_extraction(
    db: Session,
    *,
    extraction: DocumentExtraction,
    reviewer: User,
    action: str,
    value: Any | None = None,
    reason: str | None = None,
) -> tuple[DocumentExtraction, ClaimFact | None, bool]:
    if extraction.organization_id != reviewer.organization_id:
        raise ValueError("Extraction does not belong to the current organization.")

    if not extraction.source_verified and action in {"approve", "edit"} and not (reason or "").strip():
        raise ValueError("A reason is required when approving or editing an extraction whose source quote is not verified.")

    previous_status = extraction.human_status
    previous_approved_value = extraction.approved_value
    ai_value = extraction.normalized_value if extraction.normalized_value is not None else extraction.raw_value
    now = datetime.now(UTC)

    if action == "approve":
        human_status = AIReviewStatus.APPROVED
        approved_value = ai_value
    elif action == "edit":
        if value is None:
            raise ValueError("Edited reviews require a replacement value.")
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 20000:
            raise ValueError("Edited review value is too large for a structured claim fact.")
        human_status = AIReviewStatus.EDITED
        approved_value = value
    elif action == "reject":
        human_status = AIReviewStatus.REJECTED
        approved_value = None
    else:
        raise ValueError("Unsupported review action.")

    extraction.human_status = human_status
    extraction.approved_value = approved_value
    extraction.reviewed_by_id = reviewer.id
    extraction.reviewed_at = now

    feedback = AIFeedback(
        organization_id=extraction.organization_id,
        claim_id=extraction.claim_id,
        document_id=extraction.document_id,
        extraction_id=extraction.id,
        reviewer_id=reviewer.id,
        action=human_status.value,
        ai_value=ai_value,
        human_value=approved_value,
        reason=(reason or "").strip() or None,
        created_at=now,
    )
    db.add(feedback)

    promoted = False
    claim_fact = get_current_claim_fact(
        db,
        claim_id=extraction.claim_id,
        field_path=extraction.field_path,
        organization_id=extraction.organization_id,
    )

    if human_status in {AIReviewStatus.APPROVED, AIReviewStatus.EDITED} and is_promotable(extraction):
        if claim_fact is None:
            claim_fact = ClaimFact(
                organization_id=extraction.organization_id,
                claim_id=extraction.claim_id,
                field_path=extraction.field_path,
                value=approved_value,
                source_extraction_id=extraction.id,
                source_document_id=extraction.document_id,
                source_segment_id=extraction.source_segment_id,
                approved_by_id=reviewer.id,
                approved_at=now,
                version=1,
            )
            db.add(claim_fact)
            db.flush()
            write_audit_log(
                db,
                organization_id=extraction.organization_id,
                user_id=reviewer.id,
                action="CREATE_APPROVED_CLAIM_FACT",
                entity_type="claim_fact",
                entity_id=claim_fact.id,
                new_values={
                    "field_path": claim_fact.field_path,
                    "value": approved_value,
                    "source_extraction_id": str(extraction.id),
                    "version": claim_fact.version,
                },
            )
        else:
            old_fact = {
                "value": claim_fact.value,
                "source_extraction_id": str(claim_fact.source_extraction_id),
                "version": claim_fact.version,
            }
            claim_fact.value = approved_value
            claim_fact.source_extraction_id = extraction.id
            claim_fact.source_document_id = extraction.document_id
            claim_fact.source_segment_id = extraction.source_segment_id
            claim_fact.approved_by_id = reviewer.id
            claim_fact.approved_at = now
            claim_fact.version += 1
            write_audit_log(
                db,
                organization_id=extraction.organization_id,
                user_id=reviewer.id,
                action="UPDATE_APPROVED_CLAIM_FACT",
                entity_type="claim_fact",
                entity_id=claim_fact.id,
                old_values=old_fact,
                new_values={"value": approved_value, "source_extraction_id": str(extraction.id), "version": claim_fact.version},
            )
        promoted = True
    elif human_status == AIReviewStatus.REJECTED and claim_fact is not None and claim_fact.source_extraction_id == extraction.id:
        old_fact = {
            "field_path": claim_fact.field_path,
            "value": claim_fact.value,
            "source_extraction_id": str(claim_fact.source_extraction_id),
            "version": claim_fact.version,
        }
        db.delete(claim_fact)
        write_audit_log(
            db,
            organization_id=extraction.organization_id,
            user_id=reviewer.id,
            action="REMOVE_APPROVED_CLAIM_FACT",
            entity_type="claim_fact",
            entity_id=claim_fact.id,
            old_values=old_fact,
            details="Source extraction was rejected by a human reviewer.",
        )
        claim_fact = None

    write_audit_log(
        db,
        organization_id=extraction.organization_id,
        user_id=reviewer.id,
        action="REVIEW_AI_EXTRACTION",
        entity_type="document_extraction",
        entity_id=extraction.id,
        old_values={"human_status": previous_status.value, "approved_value": previous_approved_value},
        new_values={
            "human_status": human_status.value,
            "approved_value": approved_value,
            "promoted_to_claim_fact": promoted,
        },
        details=(reason or "").strip() or None,
    )
    db.flush()
    return extraction, claim_fact, promoted
