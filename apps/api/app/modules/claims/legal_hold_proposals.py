import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_models import ClaimLegalHold, LegalHoldProposal
from app.modules.claims.retention_service import (
    LEGAL_HOLD_SOURCES,
    RetentionNotFoundError,
    get_claim_for_retention,
    place_legal_hold,
)

PROPOSAL_SOURCE_KINDS = {
    "rule",
    "webhook",
    "ai",
    "external_notice",
    "investigation",
}
PROPOSAL_STATUSES = {"pending", "activated", "rejected"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_payload_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return _sha256_text(canonical)


def _normalize_source_reference(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Legal-hold proposal source reference is required")
    if len(normalized) > 2000:
        raise ValueError("Legal-hold proposal source reference is too long")
    return normalized


def ingest_legal_hold_proposal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    source_kind: str,
    source_reference: str,
    source_payload: Any,
    recommended_hold_source: str,
    reason: str,
) -> tuple[LegalHoldProposal, bool]:
    """Ingest one automated preservation signal as a pending proposal only.

    Returns ``(proposal, created)``. Replaying the same source identity and exact
    payload is idempotent. Reusing an identity with a different payload fails
    closed rather than silently rewriting provenance.
    """

    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    normalized_kind = source_kind.strip().lower()
    if normalized_kind not in PROPOSAL_SOURCE_KINDS:
        raise ValueError("Unsupported legal-hold proposal source kind")
    normalized_hold_source = recommended_hold_source.strip().lower()
    if normalized_hold_source not in LEGAL_HOLD_SOURCES - {"manual"}:
        raise ValueError("Automated proposal must recommend litigation, regulatory, or investigation")
    normalized_reason = reason.strip()
    if len(normalized_reason) < 3 or len(normalized_reason) > 4000:
        raise ValueError("Legal-hold proposal reason must be between 3 and 4000 characters")

    source_reference = _normalize_source_reference(source_reference)
    source_ref_fingerprint = _sha256_text(source_reference)
    source_payload_hash = _canonical_payload_hash(source_payload)

    existing = db.scalar(
        select(LegalHoldProposal).where(
            LegalHoldProposal.organization_id == organization_id,
            LegalHoldProposal.claim_id == claim_id,
            LegalHoldProposal.source_kind == normalized_kind,
            LegalHoldProposal.source_ref_fingerprint == source_ref_fingerprint,
        )
    )
    if existing is not None:
        if existing.source_payload_hash != source_payload_hash:
            raise ValueError("Legal-hold signal identity was reused with a different payload")
        if existing.recommended_hold_source != normalized_hold_source or existing.reason != normalized_reason:
            raise ValueError("Legal-hold signal identity was reused with different proposal semantics")
        return existing, False

    proposal = LegalHoldProposal(
        organization_id=organization_id,
        claim_id=claim_id,
        source_kind=normalized_kind,
        recommended_hold_source=normalized_hold_source,
        source_ref_fingerprint=source_ref_fingerprint,
        source_payload_hash=source_payload_hash,
        reason=normalized_reason,
        status="pending",
    )
    db.add(proposal)
    db.flush()
    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=None,
        action="LEGAL_HOLD_PROPOSAL_CREATED",
        entity_type="legal_hold_proposal",
        entity_id=proposal.id,
        new_values={
            "claim_id": str(claim_id),
            "source_kind": proposal.source_kind,
            "recommended_hold_source": proposal.recommended_hold_source,
            "source_ref_fingerprint": proposal.source_ref_fingerprint,
            "source_payload_hash": proposal.source_payload_hash,
            "status": proposal.status,
        },
    )
    return proposal, True


def list_legal_hold_proposals(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[LegalHoldProposal]:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return list(
        db.scalars(
            select(LegalHoldProposal)
            .where(
                LegalHoldProposal.organization_id == organization_id,
                LegalHoldProposal.claim_id == claim_id,
            )
            .order_by(LegalHoldProposal.created_at.desc(), LegalHoldProposal.id.desc())
        ).all()
    )


def get_legal_hold_proposal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    proposal_id: UUID,
    for_update: bool = False,
) -> LegalHoldProposal:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    stmt = select(LegalHoldProposal).where(
        LegalHoldProposal.id == proposal_id,
        LegalHoldProposal.organization_id == organization_id,
        LegalHoldProposal.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    proposal = db.scalar(stmt)
    if proposal is None:
        raise RetentionNotFoundError("Legal-hold proposal not found")
    return proposal


def pending_legal_hold_proposals(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[LegalHoldProposal]:
    return list(
        db.scalars(
            select(LegalHoldProposal)
            .where(
                LegalHoldProposal.organization_id == organization_id,
                LegalHoldProposal.claim_id == claim_id,
                LegalHoldProposal.status == "pending",
            )
            .order_by(LegalHoldProposal.created_at.asc(), LegalHoldProposal.id.asc())
        ).all()
    )


def activate_legal_hold_proposal(
    db: Session,
    *,
    proposal: LegalHoldProposal,
    activated_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
) -> tuple[ClaimLegalHold, bool]:
    normalized_reason = decision_reason.strip()
    if len(normalized_reason) < 3 or len(normalized_reason) > 4000:
        raise ValueError("Proposal activation reason must be between 3 and 4000 characters")
    if proposal.status == "rejected":
        raise ValueError("Rejected legal-hold proposal cannot be activated")
    if proposal.status == "activated":
        if proposal.hold_id is None:
            raise ValueError("Activated legal-hold proposal is missing hold linkage")
        hold = db.get(ClaimLegalHold, proposal.hold_id)
        if hold is None or hold.organization_id != proposal.organization_id or hold.claim_id != proposal.claim_id:
            raise ValueError("Activated legal-hold proposal has invalid hold linkage")
        return hold, False
    if proposal.status != "pending":
        raise ValueError("Unsupported legal-hold proposal state")

    hold = place_legal_hold(
        db,
        organization_id=proposal.organization_id,
        claim_id=proposal.claim_id,
        source=proposal.recommended_hold_source,
        reason=proposal.reason,
        placed_by_id=activated_by_id,
    )
    proposal.status = "activated"
    proposal.hold_id = hold.id
    proposal.decided_at = now or _utc_now()
    proposal.decided_by_id = activated_by_id
    proposal.decision_reason = normalized_reason
    db.flush()
    return hold, True


def reject_legal_hold_proposal(
    proposal: LegalHoldProposal,
    *,
    rejected_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
) -> bool:
    normalized_reason = decision_reason.strip()
    if len(normalized_reason) < 3 or len(normalized_reason) > 4000:
        raise ValueError("Proposal rejection reason must be between 3 and 4000 characters")
    if proposal.status == "activated":
        raise ValueError("Activated legal-hold proposal cannot be rejected")
    if proposal.status == "rejected":
        return False
    if proposal.status != "pending":
        raise ValueError("Unsupported legal-hold proposal state")
    proposal.status = "rejected"
    proposal.decided_at = now or _utc_now()
    proposal.decided_by_id = rejected_by_id
    proposal.decision_reason = normalized_reason
    return True
