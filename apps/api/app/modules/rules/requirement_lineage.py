from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document, DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.rules.models import ClaimDocumentRequirement, RequirementStatus
from app.modules.users.models import User


class ClaimDocumentRequirementState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current evidence-state identity for one deterministic document requirement.

    The requirement row remains the operational read model. This companion row
    gives human review writes a stable optimistic-concurrency token without
    turning mutable workflow status into the identity of the underlying evidence.
    """

    __tablename__ = "claim_document_requirement_states"
    __table_args__ = (
        UniqueConstraint("requirement_id", name="uq_claim_document_requirement_state_requirement"),
        Index(
            "ix_claim_document_requirement_states_org_claim_requirement",
            "organization_id",
            "claim_id",
            "requirement_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("claim_document_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class ClaimDocumentRequirementDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only human disposition history for requirement evidence review."""

    __tablename__ = "claim_document_requirement_decisions"
    __table_args__ = (
        UniqueConstraint("requirement_id", "decision_number", name="uq_claim_document_requirement_decision_number"),
        Index(
            "ix_claim_document_requirement_decisions_org_claim_requirement",
            "organization_id",
            "claim_id",
            "requirement_id",
            "decision_number",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("claim_document_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    claim_fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claim_facts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    claim_fact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    source_document_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _allowed_fact_paths(requirement: ClaimDocumentRequirement) -> tuple[str, ...]:
    # Local import avoids introducing a circular dependency while service_core
    # remains the deterministic rule-definition owner.
    from app.modules.rules.service_core import EQUIVALENT_EVIDENCE_FACTS

    return EQUIVALENT_EVIDENCE_FACTS.get(requirement.document_type, ())


def _candidate_facts(db: Session, *, claim: Claim, requirement: ClaimDocumentRequirement) -> list[ClaimFact]:
    allowed = _allowed_fact_paths(requirement)
    if not allowed:
        return []
    return list(
        db.scalars(
            select(ClaimFact)
            .where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
                ClaimFact.field_path.in_(allowed),
            )
            .order_by(ClaimFact.field_path.asc(), ClaimFact.id.asc())
        )
    )


def _document_payload(document: Document | None) -> dict[str, Any] | None:
    if document is None:
        return None
    return {
        "id": document.id,
        "family_id": document.document_family_id,
        "version": document.version_number,
        "file_hash": document.file_hash,
        "document_type": document.document_type,
        "processing_status": document.processing_status,
        "malware_scan_status": document.malware_scan_status,
        "is_current": document.is_current,
        "deleted_at": document.deleted_at,
    }


def _fact_payload(fact: ClaimFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "field_path": fact.field_path,
        "version": fact.version,
        "value": fact.value,
        "provenance_kind": fact.provenance_kind,
        "source_document_id": fact.source_document_id,
        "source_extraction_id": fact.source_extraction_id,
        "source_text_extraction_id": fact.source_text_extraction_id,
        "source_segment_id": fact.source_segment_id,
        "approved_at": fact.approved_at,
    }


def requirement_state_payload(
    db: Session,
    *,
    claim: Claim,
    requirement: ClaimDocumentRequirement,
) -> dict[str, Any]:
    document = db.get(Document, requirement.matched_document_id) if requirement.matched_document_id else None
    return {
        "rule_id": requirement.rule_id,
        "rule_version": requirement.rule_version,
        "document_type": requirement.document_type,
        "priority": requirement.priority,
        "required_from_status": requirement.required_from_status,
        "is_active": requirement.is_active,
        "matched_document": _document_payload(document),
        "equivalent_candidates": [_fact_payload(row) for row in _candidate_facts(db, claim=claim, requirement=requirement)],
    }


def requirement_state_fingerprint(
    db: Session,
    *,
    claim: Claim,
    requirement: ClaimDocumentRequirement,
) -> str:
    return _canonical_hash(requirement_state_payload(db, claim=claim, requirement=requirement))


def get_requirement_state(
    db: Session,
    *,
    requirement: ClaimDocumentRequirement,
) -> ClaimDocumentRequirementState | None:
    return db.scalar(
        select(ClaimDocumentRequirementState).where(
            ClaimDocumentRequirementState.organization_id == requirement.organization_id,
            ClaimDocumentRequirementState.claim_id == requirement.claim_id,
            ClaimDocumentRequirementState.requirement_id == requirement.id,
        )
    )


def latest_requirement_decision(
    db: Session,
    *,
    requirement: ClaimDocumentRequirement,
) -> ClaimDocumentRequirementDecision | None:
    return db.scalar(
        select(ClaimDocumentRequirementDecision)
        .where(
            ClaimDocumentRequirementDecision.organization_id == requirement.organization_id,
            ClaimDocumentRequirementDecision.claim_id == requirement.claim_id,
            ClaimDocumentRequirementDecision.requirement_id == requirement.id,
        )
        .order_by(ClaimDocumentRequirementDecision.decision_number.desc())
        .limit(1)
    )


def list_requirement_decisions(
    db: Session,
    *,
    requirement: ClaimDocumentRequirement,
) -> list[ClaimDocumentRequirementDecision]:
    return list(
        db.scalars(
            select(ClaimDocumentRequirementDecision)
            .where(
                ClaimDocumentRequirementDecision.organization_id == requirement.organization_id,
                ClaimDocumentRequirementDecision.claim_id == requirement.claim_id,
                ClaimDocumentRequirementDecision.requirement_id == requirement.id,
            )
            .order_by(ClaimDocumentRequirementDecision.decision_number.asc())
        )
    )


def _latest_equivalent_decision(
    db: Session,
    *,
    requirement: ClaimDocumentRequirement,
) -> ClaimDocumentRequirementDecision | None:
    return db.scalar(
        select(ClaimDocumentRequirementDecision)
        .where(
            ClaimDocumentRequirementDecision.organization_id == requirement.organization_id,
            ClaimDocumentRequirementDecision.claim_id == requirement.claim_id,
            ClaimDocumentRequirementDecision.requirement_id == requirement.id,
            ClaimDocumentRequirementDecision.action == "accept_equivalent",
        )
        .order_by(ClaimDocumentRequirementDecision.decision_number.desc())
        .limit(1)
    )


def _valid_decision_fact(
    db: Session,
    *,
    claim: Claim,
    requirement: ClaimDocumentRequirement,
    decision: ClaimDocumentRequirementDecision,
) -> ClaimFact | None:
    if decision.claim_fact_id is None or decision.claim_fact_version is None:
        return None
    fact = db.scalar(
        select(ClaimFact).where(
            ClaimFact.id == decision.claim_fact_id,
            ClaimFact.organization_id == claim.organization_id,
            ClaimFact.claim_id == claim.id,
        )
    )
    if fact is None:
        return None
    if fact.version != decision.claim_fact_version:
        return None
    if fact.field_path not in _allowed_fact_paths(requirement):
        return None
    return fact


def _direct_document_is_usable(db: Session, requirement: ClaimDocumentRequirement) -> bool:
    if requirement.matched_document_id is None:
        return False
    document = db.get(Document, requirement.matched_document_id)
    if document is None or document.deleted_at is not None or not document.is_current:
        return False
    if document.processing_status != DocumentProcessingStatus.PROCESSED:
        return False
    return document.malware_scan_status not in {
        DocumentMalwareScanStatus.INFECTED_QUARANTINED,
        DocumentMalwareScanStatus.SCAN_ERROR,
    }


def _apply_equivalent_continuity(
    db: Session,
    *,
    claim: Claim,
    requirement: ClaimDocumentRequirement,
) -> None:
    """Preserve a still-valid human equivalent decision across evidence evolution.

    A usable direct document remains the preferred current evidence state. If it
    disappears or a replacement is still pending/failed, the last explicit human
    equivalent decision can resume only when the exact canonical ClaimFact version
    reviewed by the handler is still current. A changed fact becomes SUPERSEDED and
    therefore cannot silently continue to satisfy readiness.
    """

    if _direct_document_is_usable(db, requirement):
        return
    decision = _latest_equivalent_decision(db, requirement=requirement)
    if decision is None:
        return
    fact = _valid_decision_fact(db, claim=claim, requirement=requirement, decision=decision)
    if fact is not None:
        requirement.status = RequirementStatus.ACCEPTED
        requirement.satisfaction_basis = "equivalent_evidence"
        requirement.satisfaction_note = decision.note
        requirement.equivalent_claim_fact_id = fact.id
        requirement.satisfied_by_id = decision.decided_by_id
        requirement.satisfied_at = decision.decided_at
        return

    requirement.status = RequirementStatus.SUPERSEDED
    requirement.satisfaction_basis = "equivalent_evidence_stale"
    requirement.satisfaction_note = (
        "The previously accepted equivalent evidence no longer matches the current canonical ClaimFact state; "
        "explicit re-review is required."
    )
    requirement.equivalent_claim_fact_id = decision.claim_fact_id
    requirement.satisfied_by_id = None
    requirement.satisfied_at = None


def sync_requirement_state(
    db: Session,
    *,
    claim: Claim,
    requirement: ClaimDocumentRequirement,
    user: User | None = None,
) -> tuple[ClaimDocumentRequirementState, bool]:
    fingerprint = requirement_state_fingerprint(db, claim=claim, requirement=requirement)
    state = get_requirement_state(db, requirement=requirement)
    changed = False
    old_status = requirement.status.value
    if state is None:
        state = ClaimDocumentRequirementState(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            requirement_id=requirement.id,
            state_fingerprint=fingerprint,
            state_version=1,
        )
        db.add(state)
        db.flush()
        changed = True
    elif state.state_fingerprint != fingerprint:
        old_fingerprint = state.state_fingerprint
        old_version = state.state_version
        state.state_fingerprint = fingerprint
        state.state_version += 1
        changed = True
        write_audit_log(
            db,
            organization_id=claim.organization_id,
            user_id=user.id if user else None,
            action="ADVANCE_REQUIREMENT_EVIDENCE_STATE",
            entity_type="claim_document_requirement",
            entity_id=requirement.id,
            old_values={"state_fingerprint": old_fingerprint, "state_version": old_version},
            new_values={"state_fingerprint": fingerprint, "state_version": state.state_version},
        )

    _apply_equivalent_continuity(db, claim=claim, requirement=requirement)
    if requirement.status.value != old_status:
        changed = True
        write_audit_log(
            db,
            organization_id=claim.organization_id,
            user_id=user.id if user else None,
            action="RECONCILE_REQUIREMENT_EVIDENCE_LINEAGE",
            entity_type="claim_document_requirement",
            entity_id=requirement.id,
            old_values={"status": old_status},
            new_values={
                "status": requirement.status.value,
                "satisfaction_basis": requirement.satisfaction_basis,
                "equivalent_claim_fact_id": (
                    str(requirement.equivalent_claim_fact_id) if requirement.equivalent_claim_fact_id else None
                ),
            },
        )
    return state, changed


def sync_claim_requirement_states(
    db: Session,
    *,
    claim: Claim,
    user: User | None = None,
) -> bool:
    requirements = list(
        db.scalars(
            select(ClaimDocumentRequirement).where(
                ClaimDocumentRequirement.organization_id == claim.organization_id,
                ClaimDocumentRequirement.claim_id == claim.id,
                ClaimDocumentRequirement.is_active.is_(True),
            )
        )
    )
    changed = False
    for requirement in requirements:
        _, item_changed = sync_requirement_state(db, claim=claim, requirement=requirement, user=user)
        changed = changed or item_changed
    return changed


def _decision_hash(
    *,
    requirement_id: UUID,
    state_fingerprint: str,
    state_version: int,
    decision_number: int,
    action: str,
    note: str,
    claim_fact_id: UUID | None,
    claim_fact_version: int | None,
    source_document_id: UUID | None,
    source_document_version: int | None,
    decided_by_id: UUID | None,
    previous_decision_hash: str | None,
) -> str:
    return _canonical_hash(
        {
            "requirement_id": requirement_id,
            "state_fingerprint": state_fingerprint,
            "state_version": state_version,
            "decision_number": decision_number,
            "action": action,
            "note": note,
            "claim_fact_id": claim_fact_id,
            "claim_fact_version": claim_fact_version,
            "source_document_id": source_document_id,
            "source_document_version": source_document_version,
            "decided_by_id": decided_by_id,
            "previous_decision_hash": previous_decision_hash,
        }
    )


def accept_equivalent_evidence_with_lineage(
    db: Session,
    *,
    claim: Claim,
    requirement: ClaimDocumentRequirement,
    claim_fact: ClaimFact,
    user: User,
    note: str,
    expected_state_fingerprint: str,
    expected_state_version: int,
    expected_claim_fact_version: int,
    re_review: bool = False,
) -> tuple[ClaimDocumentRequirement, ClaimDocumentRequirementDecision]:
    stmt = select(ClaimDocumentRequirement).where(
        ClaimDocumentRequirement.id == requirement.id,
        ClaimDocumentRequirement.organization_id == claim.organization_id,
        ClaimDocumentRequirement.claim_id == claim.id,
        ClaimDocumentRequirement.is_active.is_(True),
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    locked = db.scalar(stmt)
    if locked is None:
        raise ValueError("Document requirement not found for this claim.")

    state, _ = sync_requirement_state(db, claim=claim, requirement=locked, user=user)
    if state.state_fingerprint != expected_state_fingerprint or state.state_version != expected_state_version:
        raise ValueError(
            "The requirement evidence state changed after it was reviewed. Refresh the requirement and review the current evidence before deciding."
        )
    if _direct_document_is_usable(db, locked):
        raise ValueError("A usable direct document is now available for this requirement; review the direct evidence instead.")

    current_fact = db.scalar(
        select(ClaimFact).where(
            ClaimFact.id == claim_fact.id,
            ClaimFact.organization_id == claim.organization_id,
            ClaimFact.claim_id == claim.id,
        )
    )
    if current_fact is None:
        raise ValueError("Equivalent evidence is no longer available for this claim.")
    if current_fact.version != expected_claim_fact_version:
        raise ValueError(
            "The selected canonical ClaimFact changed after it was reviewed. Refresh the requirement and explicitly re-review the current fact version."
        )
    if current_fact.field_path not in _allowed_fact_paths(locked):
        raise ValueError("The selected approved claim fact is not an accepted equivalent for this requirement.")
    normalized_note = (note or "").strip()
    if len(normalized_note) < 5:
        raise ValueError("A short justification is required when accepting equivalent evidence.")

    existing_same_state = db.scalar(
        select(ClaimDocumentRequirementDecision)
        .where(
            ClaimDocumentRequirementDecision.organization_id == claim.organization_id,
            ClaimDocumentRequirementDecision.claim_id == claim.id,
            ClaimDocumentRequirementDecision.requirement_id == locked.id,
            ClaimDocumentRequirementDecision.state_fingerprint == state.state_fingerprint,
            ClaimDocumentRequirementDecision.state_version == state.state_version,
            ClaimDocumentRequirementDecision.action == "accept_equivalent",
        )
        .order_by(ClaimDocumentRequirementDecision.decision_number.desc())
        .limit(1)
    )
    if existing_same_state is not None and not re_review:
        exact_replay = (
            existing_same_state.claim_fact_id == current_fact.id
            and existing_same_state.claim_fact_version == current_fact.version
            and existing_same_state.note == normalized_note
            and existing_same_state.decided_by_id == user.id
        )
        if exact_replay:
            locked.status = RequirementStatus.ACCEPTED
            locked.satisfaction_basis = "equivalent_evidence"
            locked.satisfaction_note = existing_same_state.note
            locked.equivalent_claim_fact_id = current_fact.id
            locked.satisfied_by_id = existing_same_state.decided_by_id
            locked.satisfied_at = existing_same_state.decided_at
            from app.modules.tasks.service import sync_requirement_tasks

            sync_requirement_tasks(db, claim=claim, user=user)
            db.commit()
            db.refresh(locked)
            return locked, existing_same_state
        raise ValueError(
            "This requirement state already has a human equivalent-evidence decision. Use deliberate re-review to record a new disposition."
        )

    latest = latest_requirement_decision(db, requirement=locked)
    decision_number = int(
        db.scalar(
            select(func.max(ClaimDocumentRequirementDecision.decision_number)).where(
                ClaimDocumentRequirementDecision.requirement_id == locked.id
            )
        )
        or 0
    ) + 1
    document = db.get(Document, current_fact.source_document_id)
    source_document_version = document.version_number if document is not None else None
    now = datetime.now(UTC)
    decision = ClaimDocumentRequirementDecision(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        requirement_id=locked.id,
        decided_by_id=user.id,
        claim_fact_id=current_fact.id,
        state_fingerprint=state.state_fingerprint,
        state_version=state.state_version,
        decision_number=decision_number,
        action="accept_equivalent",
        note=normalized_note,
        claim_fact_version=current_fact.version,
        source_document_id=current_fact.source_document_id,
        source_document_version=source_document_version,
        previous_decision_hash=latest.decision_hash if latest else None,
        decision_hash="",
        decided_at=now,
    )
    decision.decision_hash = _decision_hash(
        requirement_id=locked.id,
        state_fingerprint=decision.state_fingerprint,
        state_version=decision.state_version,
        decision_number=decision.decision_number,
        action=decision.action,
        note=decision.note,
        claim_fact_id=decision.claim_fact_id,
        claim_fact_version=decision.claim_fact_version,
        source_document_id=decision.source_document_id,
        source_document_version=decision.source_document_version,
        decided_by_id=decision.decided_by_id,
        previous_decision_hash=decision.previous_decision_hash,
    )
    db.add(decision)

    old = {
        "status": locked.status.value,
        "satisfaction_basis": locked.satisfaction_basis,
        "equivalent_claim_fact_id": str(locked.equivalent_claim_fact_id) if locked.equivalent_claim_fact_id else None,
    }
    locked.status = RequirementStatus.ACCEPTED
    locked.satisfaction_basis = "equivalent_evidence"
    locked.satisfaction_note = normalized_note
    locked.equivalent_claim_fact_id = current_fact.id
    locked.satisfied_by_id = user.id
    locked.satisfied_at = now

    from app.modules.tasks.service import sync_requirement_tasks

    sync_requirement_tasks(db, claim=claim, user=user)
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REREVIEW_EQUIVALENT_EVIDENCE" if re_review else "ACCEPT_EQUIVALENT_EVIDENCE",
        entity_type="claim_document_requirement",
        entity_id=locked.id,
        old_values=old,
        new_values={
            "status": locked.status.value,
            "satisfaction_basis": locked.satisfaction_basis,
            "claim_fact_id": str(current_fact.id),
            "claim_fact_version": current_fact.version,
            "field_path": current_fact.field_path,
            "state_fingerprint": state.state_fingerprint,
            "state_version": state.state_version,
            "decision_number": decision_number,
            "decision_hash": decision.decision_hash,
            "note": normalized_note,
        },
    )
    db.commit()
    db.refresh(locked)
    db.refresh(decision)
    return locked, decision
