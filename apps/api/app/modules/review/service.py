from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact, ClaimFactRevision
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


def _postgresql(db: Session) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def _lock_claim_review_scope(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
) -> None:
    """Serialize canonical fact mutations for one claim on PostgreSQL.

    Different AI extractions can target the same canonical field. Locking the
    claim before the extraction avoids a reverse-order deadlock in grouped review
    and ensures only one reviewer mutates a claim's current-fact set at a time.
    SQLite test environments keep their normal transaction semantics.
    """

    if not _postgresql(db):
        return
    locked = db.scalar(
        select(Claim.id)
        .where(
            Claim.id == claim_id,
            Claim.organization_id == organization_id,
            Claim.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if locked is None:
        raise ValueError("Claim is unavailable for review.")


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

    # Pending work is operational FIFO: older unreviewed candidates stay at the
    # front until a human acts. Historical status views are the opposite: recent
    # human decisions must stay visible even when a claim has more rows than the
    # page limit, otherwise a just-approved item can disappear behind old history.
    if human_status == AIReviewStatus.PENDING:
        ordering = (DocumentExtraction.created_at.asc(), DocumentExtraction.field_path.asc())
    elif human_status is None:
        ordering = (DocumentExtraction.created_at.desc(), DocumentExtraction.field_path.asc())
    else:
        ordering = (
            DocumentExtraction.reviewed_at.desc().nullslast(),
            DocumentExtraction.created_at.desc(),
            DocumentExtraction.field_path.asc(),
        )

    rows = db.execute(
        query.order_by(*ordering)
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


def get_extraction_for_tenant(
    db: Session,
    *,
    extraction_id: UUID,
    organization_id: UUID,
    lock_for_update: bool = False,
) -> DocumentExtraction | None:
    query = (
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
    if lock_for_update and _postgresql(db):
        query = query.with_for_update(of=DocumentExtraction)
    return db.scalar(query)


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


def _latest_feedback(
    db: Session,
    *,
    extraction_id: UUID,
    organization_id: UUID,
) -> AIFeedback | None:
    return db.scalar(
        select(AIFeedback)
        .where(
            AIFeedback.extraction_id == extraction_id,
            AIFeedback.organization_id == organization_id,
        )
        .order_by(AIFeedback.created_at.desc(), AIFeedback.id.desc())
        .limit(1)
    )


def get_current_claim_fact(
    db: Session,
    *,
    claim_id: UUID,
    field_path: str,
    organization_id: UUID,
    lock_for_update: bool = False,
) -> ClaimFact | None:
    query = select(ClaimFact).where(
        ClaimFact.organization_id == organization_id,
        ClaimFact.claim_id == claim_id,
        ClaimFact.field_path == field_path,
    )
    if lock_for_update and _postgresql(db):
        query = query.with_for_update()
    return db.scalar(query)


def _latest_restorable_revision(
    db: Session,
    *,
    claim_fact: ClaimFact,
    rejected_extraction_id: UUID,
) -> ClaimFactRevision | None:
    revisions = list(
        db.scalars(
            select(ClaimFactRevision)
            .where(
                ClaimFactRevision.organization_id == claim_fact.organization_id,
                ClaimFactRevision.claim_id == claim_fact.claim_id,
                ClaimFactRevision.field_path == claim_fact.field_path,
                ClaimFactRevision.version < claim_fact.version,
                or_(
                    ClaimFactRevision.source_extraction_id.is_(None),
                    ClaimFactRevision.source_extraction_id != rejected_extraction_id,
                ),
            )
            .order_by(ClaimFactRevision.version.desc())
            .limit(50)
        )
    )
    for revision in revisions:
        if revision.provenance_kind == "intake_review":
            return revision
        if revision.provenance_kind != "ai_review" or revision.source_extraction_id is None:
            continue
        source = db.get(DocumentExtraction, revision.source_extraction_id)
        if source is not None and source.human_status in {AIReviewStatus.APPROVED, AIReviewStatus.EDITED}:
            return revision
    return None


def _fact_audit_values(claim_fact: ClaimFact) -> dict[str, Any]:
    return {
        "field_path": claim_fact.field_path,
        "value": claim_fact.value,
        "provenance_kind": claim_fact.provenance_kind,
        "source_extraction_id": str(claim_fact.source_extraction_id) if claim_fact.source_extraction_id else None,
        "source_text_extraction_id": str(claim_fact.source_text_extraction_id) if claim_fact.source_text_extraction_id else None,
        "source_document_id": str(claim_fact.source_document_id),
        "source_segment_id": str(claim_fact.source_segment_id) if claim_fact.source_segment_id else None,
        "version": claim_fact.version,
    }


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

    # Serialize all canonical-fact mutations for this claim before locking the
    # individual extraction. This keeps grouped review lock ordering stable.
    _lock_claim_review_scope(
        db,
        claim_id=extraction.claim_id,
        organization_id=reviewer.organization_id,
    )
    locked_extraction = get_extraction_for_tenant(
        db,
        extraction_id=extraction.id,
        organization_id=reviewer.organization_id,
        lock_for_update=True,
    )
    if locked_extraction is None:
        raise ValueError("Extraction is unavailable for review.")
    extraction = locked_extraction

    normalized_reason = (reason or "").strip() or None
    if not extraction.source_verified and action in {"approve", "edit"} and normalized_reason is None:
        raise ValueError(
            "A reason is required when approving or editing an extraction whose source quote is not verified."
        )

    ai_value = extraction.normalized_value if extraction.normalized_value is not None else extraction.raw_value
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

    claim_fact = get_current_claim_fact(
        db,
        claim_id=extraction.claim_id,
        field_path=extraction.field_path,
        organization_id=extraction.organization_id,
        lock_for_update=True,
    )
    latest_feedback = _latest_feedback(
        db,
        extraction_id=extraction.id,
        organization_id=extraction.organization_id,
    )

    # Exact semantic replay is a transport/client retry, not a new human
    # decision. A different reason is intentionally treated as a fresh review so
    # a reviewer can explicitly re-assert the same value with new reasoning.
    if (
        extraction.human_status == human_status
        and extraction.approved_value == approved_value
        and latest_feedback is not None
        and latest_feedback.action == human_status.value
        and latest_feedback.human_value == approved_value
        and latest_feedback.reason == normalized_reason
    ):
        currently_promoted = bool(
            claim_fact is not None
            and is_promotable(extraction)
            and claim_fact.provenance_kind == "ai_review"
            and claim_fact.source_extraction_id == extraction.id
        )
        return extraction, claim_fact, currently_promoted

    previous_status = extraction.human_status
    previous_approved_value = extraction.approved_value
    now = datetime.now(UTC)
    extraction.human_status = human_status
    extraction.approved_value = approved_value
    extraction.reviewed_by_id = reviewer.id
    extraction.reviewed_at = now

    db.add(
        AIFeedback(
            organization_id=extraction.organization_id,
            claim_id=extraction.claim_id,
            document_id=extraction.document_id,
            extraction_id=extraction.id,
            reviewer_id=reviewer.id,
            action=human_status.value,
            ai_value=ai_value,
            human_value=approved_value,
            reason=normalized_reason,
            created_at=now,
        )
    )

    promoted = False
    if human_status in {AIReviewStatus.APPROVED, AIReviewStatus.EDITED} and is_promotable(extraction):
        if claim_fact is None:
            claim_fact = ClaimFact(
                organization_id=extraction.organization_id,
                claim_id=extraction.claim_id,
                field_path=extraction.field_path,
                value=approved_value,
                provenance_kind="ai_review",
                source_extraction_id=extraction.id,
                source_text_extraction_id=None,
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
                new_values=_fact_audit_values(claim_fact),
            )
        else:
            old_fact = _fact_audit_values(claim_fact)
            claim_fact.value = approved_value
            claim_fact.provenance_kind = "ai_review"
            claim_fact.source_extraction_id = extraction.id
            claim_fact.source_text_extraction_id = None
            claim_fact.source_document_id = extraction.document_id
            claim_fact.source_segment_id = extraction.source_segment_id
            claim_fact.approved_by_id = reviewer.id
            claim_fact.approved_at = now
            claim_fact.version += 1
            db.flush()
            write_audit_log(
                db,
                organization_id=extraction.organization_id,
                user_id=reviewer.id,
                action="UPDATE_APPROVED_CLAIM_FACT",
                entity_type="claim_fact",
                entity_id=claim_fact.id,
                old_values=old_fact,
                new_values=_fact_audit_values(claim_fact),
            )
        promoted = True
    elif (
        human_status == AIReviewStatus.REJECTED
        and claim_fact is not None
        and claim_fact.provenance_kind == "ai_review"
        and claim_fact.source_extraction_id == extraction.id
    ):
        old_fact = _fact_audit_values(claim_fact)
        previous_revision = _latest_restorable_revision(
            db,
            claim_fact=claim_fact,
            rejected_extraction_id=extraction.id,
        )
        if previous_revision is None:
            db.delete(claim_fact)
            write_audit_log(
                db,
                organization_id=extraction.organization_id,
                user_id=reviewer.id,
                action="REMOVE_APPROVED_CLAIM_FACT",
                entity_type="claim_fact",
                entity_id=claim_fact.id,
                old_values=old_fact,
                details="Source extraction was rejected and no earlier still-valid canonical fact exists.",
            )
            claim_fact = None
        else:
            claim_fact.value = previous_revision.value
            claim_fact.provenance_kind = previous_revision.provenance_kind
            claim_fact.source_extraction_id = previous_revision.source_extraction_id
            claim_fact.source_text_extraction_id = previous_revision.source_text_extraction_id
            claim_fact.source_document_id = previous_revision.source_document_id
            claim_fact.source_segment_id = previous_revision.source_segment_id
            claim_fact.approved_by_id = previous_revision.approved_by_id
            claim_fact.approved_at = previous_revision.approved_at
            claim_fact.version += 1
            db.flush()
            write_audit_log(
                db,
                organization_id=extraction.organization_id,
                user_id=reviewer.id,
                action="RESTORE_APPROVED_CLAIM_FACT",
                entity_type="claim_fact",
                entity_id=claim_fact.id,
                old_values=old_fact,
                new_values=_fact_audit_values(claim_fact),
                details=(
                    f"Rejected AI extraction {extraction.id}; restored canonical revision "
                    f"{previous_revision.version} under a new current version."
                ),
            )

    write_audit_log(
        db,
        organization_id=extraction.organization_id,
        user_id=reviewer.id,
        action="REVIEW_AI_EXTRACTION",
        entity_type="document_extraction",
        entity_id=extraction.id,
        old_values={
            "human_status": previous_status.value,
            "approved_value": previous_approved_value,
        },
        new_values={
            "human_status": human_status.value,
            "approved_value": approved_value,
            "promoted_to_claim_fact": promoted,
        },
        details=normalized_reason,
    )
    db.flush()
    return extraction, claim_fact, promoted
