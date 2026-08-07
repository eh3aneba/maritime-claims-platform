from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.chronology.models import ChronologyEvent, ConflictStatus, EvidenceConflict, EventEvidence
from app.modules.chronology.schemas import (
    ChronologyBuildResponse,
    ChronologyEventResponse,
    ChronologyResponse,
    ConflictResolutionRequest,
    ConflictResolutionResponse,
    EventEvidenceResponse,
    EvidenceConflictResponse,
)
from app.modules.chronology.service import build_chronology, resolve_conflict
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.models import Document
from app.modules.intelligence.models import DocumentExtraction

router = APIRouter(prefix="/claims/{claim_id}/chronology", tags=["chronology"])


def _serialize_event(db: Session, event: ChronologyEvent) -> ChronologyEventResponse:
    evidence_rows = list(
        db.execute(
            select(EventEvidence, DocumentExtraction, Document)
            .join(DocumentExtraction, DocumentExtraction.id == EventEvidence.extraction_id)
            .join(Document, Document.id == EventEvidence.document_id)
            .where(EventEvidence.event_id == event.id)
            .order_by(EventEvidence.created_at.asc())
        ).all()
    )
    evidence = [
        EventEvidenceResponse(
            extraction_id=extraction.id,
            document_id=document.id,
            document_name=document.original_filename,
            document_type=document.document_type,
            field_path=extraction.field_path,
            value=extraction.approved_value if extraction.approved_value is not None else extraction.normalized_value if extraction.normalized_value is not None else extraction.raw_value,
            source_quote=extraction.source_quote,
            source_locator_type=extraction.source_locator_type,
            source_locator_value=extraction.source_locator_value,
            source_verified=extraction.source_verified,
            evidence_role=link.evidence_role,
        )
        for link, extraction, document in evidence_rows
    ]
    return ChronologyEventResponse(
        id=event.id,
        event_type=event.event_type,
        title=event.title,
        description=event.description,
        occurred_on=event.occurred_on,
        occurred_time=event.occurred_time,
        timezone_label=event.timezone_label,
        materiality=event.materiality,
        evidence=evidence,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _serialize_conflict(conflict: EvidenceConflict) -> EvidenceConflictResponse:
    return EvidenceConflictResponse(
        id=conflict.id,
        conflict_type=conflict.conflict_type,
        topic=conflict.topic,
        description=conflict.description,
        value_a=conflict.value_a,
        value_b=conflict.value_b,
        difference_minutes=conflict.difference_minutes,
        materiality=conflict.materiality,
        status=conflict.status,
        resolution_note=conflict.resolution_note,
        event_a_id=conflict.event_a_id,
        event_b_id=conflict.event_b_id,
        evidence_a_extraction_id=conflict.evidence_a_extraction_id,
        evidence_b_extraction_id=conflict.evidence_b_extraction_id,
        resolved_by_id=conflict.resolved_by_id,
        resolved_at=conflict.resolved_at,
        created_at=conflict.created_at,
        updated_at=conflict.updated_at,
    )


@router.get("", response_model=ChronologyResponse)
def chronology_summary(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> ChronologyResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    events = list(db.scalars(select(ChronologyEvent).where(ChronologyEvent.claim_id == claim.id, ChronologyEvent.organization_id == claim.organization_id, ChronologyEvent.is_active.is_(True)).order_by(ChronologyEvent.occurred_on.asc().nullslast(), ChronologyEvent.occurred_time.asc().nullslast(), ChronologyEvent.created_at.asc())))
    conflicts = list(db.scalars(select(EvidenceConflict).where(EvidenceConflict.claim_id == claim.id, EvidenceConflict.organization_id == claim.organization_id, EvidenceConflict.is_active.is_(True)).order_by(EvidenceConflict.created_at.asc())))
    return ChronologyResponse(
        events=[_serialize_event(db, event) for event in events],
        conflicts=[_serialize_conflict(conflict) for conflict in conflicts],
        event_count=len(events),
        open_conflict_count=sum(conflict.status == ConflictStatus.OPEN for conflict in conflicts),
    )


@router.post("/rebuild", response_model=ChronologyBuildResponse)
def rebuild_chronology(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> ChronologyBuildResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    events, conflicts = build_chronology(db, claim=claim, user=current_user)
    return ChronologyBuildResponse(
        events_created_or_activated=len(events),
        conflicts_created_or_activated=len(conflicts),
        event_count=len(events),
        open_conflict_count=sum(conflict.status == ConflictStatus.OPEN for conflict in conflicts),
    )


@router.post("/conflicts/{conflict_id}/resolve", response_model=ConflictResolutionResponse)
def resolve_claim_conflict(
    claim_id: UUID,
    conflict_id: UUID,
    payload: ConflictResolutionRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ConflictResolutionResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    conflict = db.scalar(select(EvidenceConflict).where(EvidenceConflict.id == conflict_id, EvidenceConflict.claim_id == claim.id, EvidenceConflict.organization_id == claim.organization_id, EvidenceConflict.is_active.is_(True)))
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence conflict not found")
    resolved = resolve_conflict(db, conflict=conflict, user=current_user, status=ConflictStatus(payload.status), note=payload.note)
    return ConflictResolutionResponse.model_validate(resolved)
