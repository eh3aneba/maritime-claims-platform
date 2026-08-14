from datetime import UTC, datetime
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.chronology.models import ConflictStatus, EvidenceConflict
from app.modules.claims.facts import ClaimFact
from app.modules.claims.service import get_claim
from app.modules.documents.models import Document
from app.modules.evidence_matrix.schemas import (
    EvidenceMatrixConflict,
    EvidenceMatrixResponse,
    EvidenceMatrixRow,
    EvidenceMatrixSource,
    EvidenceMatrixSummary,
)
from app.modules.intelligence.models import (
    AISemanticKind,
    AIReviewStatus,
    DocumentExtraction,
)


def _topic_label(field_path: str) -> str:
    cleaned = re.sub(r"\[\d+\]", "", field_path)
    parts = [part.replace("_", " ").strip() for part in cleaned.split(".") if part]
    return " · ".join(part[:1].upper() + part[1:] for part in parts)


def _approved_value(extraction: DocumentExtraction):
    if extraction.approved_value is not None:
        return extraction.approved_value
    return extraction.normalized_value


def _source(
    extraction: DocumentExtraction,
    *,
    document: Document,
    authoritative_extraction_id: UUID | None,
) -> EvidenceMatrixSource:
    return EvidenceMatrixSource(
        extraction_id=extraction.id,
        document_id=document.id,
        document_family_id=document.document_family_id,
        document_name=document.original_filename,
        document_type=document.document_type,
        document_version=document.version_number,
        document_is_current=document.is_current,
        document_deleted=document.deleted_at is not None,
        authoritative=extraction.id == authoritative_extraction_id,
        semantic_kind=extraction.semantic_kind.value,
        human_status=extraction.human_status.value,
        source_verified=extraction.source_verified,
        source_locator_type=extraction.source_locator_type,
        source_locator_value=extraction.source_locator_value,
        source_quote=extraction.source_quote,
    )


def _conflict(conflict: EvidenceConflict) -> EvidenceMatrixConflict:
    return EvidenceMatrixConflict(
        id=conflict.id,
        topic=conflict.topic,
        conflict_type=conflict.conflict_type,
        description=conflict.description,
        value_a=conflict.value_a,
        value_b=conflict.value_b,
        difference_minutes=conflict.difference_minutes,
        materiality=conflict.materiality.value,
        status=conflict.status.value,
        resolution_note=conflict.resolution_note,
        evidence_a_extraction_id=conflict.evidence_a_extraction_id,
        evidence_b_extraction_id=conflict.evidence_b_extraction_id,
    )


def build_evidence_matrix(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
) -> EvidenceMatrixResponse:
    # Reuse claim access semantics so deleted or cross-tenant claims remain hidden.
    get_claim(db, claim_id=claim_id, organization_id=organization_id)

    facts = list(
        db.scalars(
            select(ClaimFact)
            .where(
                ClaimFact.organization_id == organization_id,
                ClaimFact.claim_id == claim_id,
            )
            .order_by(ClaimFact.field_path.asc())
        )
    )
    reviewed_extractions = list(
        db.scalars(
            select(DocumentExtraction).where(
                DocumentExtraction.organization_id == organization_id,
                DocumentExtraction.claim_id == claim_id,
                DocumentExtraction.human_status.in_(
                    [AIReviewStatus.APPROVED, AIReviewStatus.EDITED]
                ),
            )
        )
    )
    conflicts = list(
        db.scalars(
            select(EvidenceConflict)
            .where(
                EvidenceConflict.organization_id == organization_id,
                EvidenceConflict.claim_id == claim_id,
                EvidenceConflict.is_active.is_(True),
            )
            .order_by(EvidenceConflict.created_at.asc())
        )
    )

    extraction_by_id = {row.id: row for row in reviewed_extractions}
    document_ids = {row.document_id for row in reviewed_extractions}
    documents = (
        list(
            db.scalars(
                select(Document).where(
                    Document.organization_id == organization_id,
                    Document.claim_id == claim_id,
                    Document.id.in_(document_ids),
                )
            )
        )
        if document_ids
        else []
    )
    document_by_id = {row.id: row for row in documents}

    rows: list[EvidenceMatrixRow] = []
    attached_conflict_ids: set[UUID] = set()
    source_extraction_ids: set[UUID] = set()
    source_document_ids: set[UUID] = set()
    superseded_fact_source_count = 0

    for fact in facts:
        candidates = [
            extraction
            for extraction in reviewed_extractions
            if extraction.semantic_kind == AISemanticKind.FACT
            and extraction.field_path == fact.field_path
            and _approved_value(extraction) == fact.value
            and extraction.document_id in document_by_id
        ]
        primary = extraction_by_id.get(fact.source_extraction_id)
        if (
            primary is not None
            and primary.document_id in document_by_id
            and all(item.id != primary.id for item in candidates)
        ):
            candidates.insert(0, primary)
        candidates.sort(
            key=lambda item: (
                item.id != fact.source_extraction_id,
                not document_by_id[item.document_id].is_current,
                document_by_id[item.document_id].version_number,
                str(item.id),
            )
        )
        sources = [
            _source(
                extraction,
                document=document_by_id[extraction.document_id],
                authoritative_extraction_id=fact.source_extraction_id,
            )
            for extraction in candidates
        ]
        related_ids = {item.extraction_id for item in sources}
        related_conflicts = [
            conflict
            for conflict in conflicts
            if {
                conflict.evidence_a_extraction_id,
                conflict.evidence_b_extraction_id,
            }
            & related_ids
        ]
        attached_conflict_ids.update(item.id for item in related_conflicts)
        source_extraction_ids.update(related_ids)
        source_document_ids.update(item.document_id for item in sources)

        primary_document = (
            document_by_id.get(primary.document_id) if primary is not None else None
        )
        if any(item.status == ConflictStatus.OPEN for item in related_conflicts):
            row_status = "conflict_open"
        elif primary_document is None:
            row_status = "unsupported"
        elif primary_document.deleted_at is not None:
            row_status = "source_deleted"
        elif not primary_document.is_current:
            row_status = "source_superseded"
            superseded_fact_source_count += 1
        elif related_conflicts:
            row_status = "conflict_reviewed"
        else:
            row_status = "supported"

        rows.append(
            EvidenceMatrixRow(
                row_key=f"fact:{fact.id}",
                topic=_topic_label(fact.field_path),
                field_path=fact.field_path,
                fact_id=fact.id,
                fact_value=fact.value,
                fact_version=fact.version,
                approved_at=fact.approved_at,
                supporting_evidence=sources,
                conflicting_evidence=[_conflict(item) for item in related_conflicts],
                status=row_status,
            )
        )

    # Active conflicts without an approved Claim Fact remain visible. They are
    # review issues only and never populate the authoritative Fact column.
    for conflict in conflicts:
        if conflict.id in attached_conflict_ids:
            continue
        conflict_extraction_ids = {
            item
            for item in (
                conflict.evidence_a_extraction_id,
                conflict.evidence_b_extraction_id,
            )
            if item is not None
        }
        conflict_sources = []
        for extraction_id in sorted(conflict_extraction_ids, key=str):
            extraction = extraction_by_id.get(extraction_id)
            if extraction is None:
                continue
            document = document_by_id.get(extraction.document_id)
            if document is None:
                continue
            conflict_sources.append(
                _source(
                    extraction,
                    document=document,
                    authoritative_extraction_id=None,
                )
            )
        source_extraction_ids.update(item.extraction_id for item in conflict_sources)
        source_document_ids.update(item.document_id for item in conflict_sources)
        rows.append(
            EvidenceMatrixRow(
                row_key=f"conflict:{conflict.id}",
                topic=conflict.topic,
                field_path=None,
                fact_id=None,
                fact_value=None,
                fact_version=None,
                approved_at=None,
                supporting_evidence=conflict_sources,
                conflicting_evidence=[_conflict(conflict)],
                status=(
                    "conflict_open"
                    if conflict.status == ConflictStatus.OPEN
                    else "conflict_only"
                ),
            )
        )

    current_document_ids = {
        document_id
        for document_id in source_document_ids
        if document_by_id[document_id].is_current
        and document_by_id[document_id].deleted_at is None
    }
    historical_document_ids = source_document_ids - current_document_ids
    open_conflicts = sum(
        1 for item in conflicts if item.status == ConflictStatus.OPEN
    )

    return EvidenceMatrixResponse(
        claim_id=claim_id,
        generated_at=datetime.now(UTC),
        rows=rows,
        summary=EvidenceMatrixSummary(
            approved_fact_count=len(facts),
            matrix_row_count=len(rows),
            supporting_source_count=len(source_extraction_ids),
            current_source_document_count=len(current_document_ids),
            historical_source_document_count=len(historical_document_ids),
            open_conflict_count=open_conflicts,
            reviewed_conflict_count=len(conflicts) - open_conflicts,
            superseded_fact_source_count=superseded_fact_source_count,
        ),
    )
