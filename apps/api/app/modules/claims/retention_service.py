import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_models import ClaimLegalHold, LegalHoldProposal, TenantRetentionPolicy
from app.modules.documents.models import Document

FINAL_RETENTION_STATUSES = {
    ClaimStatus.CLOSED,
    ClaimStatus.REJECTED,
    ClaimStatus.WITHDRAWN,
}
LEGAL_HOLD_SOURCES = {"manual", "litigation", "regulatory", "investigation"}


class RetentionNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class DisposalEligibility:
    claim_id: UUID
    policy_id: UUID | None
    policy_number: int | None
    eligible: bool
    blocking_reasons: list[str]
    active_hold_ids: list[UUID]
    pending_proposal_ids: list[UUID]
    retention_anchor_at: datetime
    claim_retention_expires_at: datetime | None
    evidence_retention_expires_at: datetime | None
    earliest_eligible_at: datetime | None
    evaluated_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_claim_for_retention(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> Claim:
    claim = db.scalar(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.organization_id == organization_id,
            Claim.deleted_at.is_(None),
        )
    )
    if claim is None:
        raise RetentionNotFoundError("Claim not found")
    return claim


def list_retention_policies(
    db: Session,
    *,
    organization_id: UUID,
) -> list[TenantRetentionPolicy]:
    return list(
        db.scalars(
            select(TenantRetentionPolicy)
            .where(TenantRetentionPolicy.organization_id == organization_id)
            .order_by(TenantRetentionPolicy.policy_number.desc())
        ).all()
    )


def get_latest_retention_policy(
    db: Session,
    *,
    organization_id: UUID,
    for_update: bool = False,
) -> TenantRetentionPolicy | None:
    stmt = (
        select(TenantRetentionPolicy)
        .where(TenantRetentionPolicy.organization_id == organization_id)
        .order_by(TenantRetentionPolicy.policy_number.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def get_current_retention_policy(
    db: Session,
    *,
    organization_id: UUID,
) -> TenantRetentionPolicy | None:
    latest = get_latest_retention_policy(db, organization_id=organization_id)
    if latest is None or not latest.enabled:
        return None
    return latest


def _policy_hash(
    *,
    organization_id: UUID,
    policy_number: int,
    closed_claim_retention_days: int,
    evidence_retention_days: int,
    enabled: bool,
    disposal_enabled: bool,
    previous_policy_hash: str | None,
) -> str:
    canonical = json.dumps(
        {
            "organization_id": str(organization_id),
            "policy_number": policy_number,
            "closed_claim_retention_days": closed_claim_retention_days,
            "evidence_retention_days": evidence_retention_days,
            "enabled": enabled,
            "disposal_enabled": disposal_enabled,
            "previous_policy_hash": previous_policy_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_retention_policy(
    db: Session,
    *,
    organization_id: UUID,
    closed_claim_retention_days: int,
    evidence_retention_days: int,
    enabled: bool,
    disposal_enabled: bool,
    created_by_id: UUID,
) -> TenantRetentionPolicy:
    if not 30 <= closed_claim_retention_days <= 36500:
        raise ValueError("closed claim retention must be between 30 and 36500 days")
    if not 30 <= evidence_retention_days <= 36500:
        raise ValueError("evidence retention must be between 30 and 36500 days")

    latest = get_latest_retention_policy(
        db,
        organization_id=organization_id,
        for_update=True,
    )
    policy_number = 1 if latest is None else latest.policy_number + 1
    previous_policy_hash = None if latest is None else latest.policy_hash
    policy = TenantRetentionPolicy(
        organization_id=organization_id,
        policy_number=policy_number,
        closed_claim_retention_days=closed_claim_retention_days,
        evidence_retention_days=evidence_retention_days,
        enabled=enabled,
        disposal_enabled=disposal_enabled,
        previous_policy_hash=previous_policy_hash,
        policy_hash=_policy_hash(
            organization_id=organization_id,
            policy_number=policy_number,
            closed_claim_retention_days=closed_claim_retention_days,
            evidence_retention_days=evidence_retention_days,
            enabled=enabled,
            disposal_enabled=disposal_enabled,
            previous_policy_hash=previous_policy_hash,
        ),
        created_by_id=created_by_id,
    )
    db.add(policy)
    db.flush()
    return policy


def place_legal_hold(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    source: str,
    reason: str,
    placed_by_id: UUID,
) -> ClaimLegalHold:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    normalized_source = source.strip().lower()
    if normalized_source not in LEGAL_HOLD_SOURCES:
        raise ValueError("Unsupported legal-hold source")
    normalized_reason = reason.strip()
    if len(normalized_reason) < 3:
        raise ValueError("Legal-hold reason is required")

    hold = ClaimLegalHold(
        organization_id=organization_id,
        claim_id=claim_id,
        source=normalized_source,
        reason=normalized_reason,
        placed_by_id=placed_by_id,
    )
    db.add(hold)
    db.flush()
    return hold


def list_legal_holds(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[ClaimLegalHold]:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return list(
        db.scalars(
            select(ClaimLegalHold)
            .where(
                ClaimLegalHold.organization_id == organization_id,
                ClaimLegalHold.claim_id == claim_id,
            )
            .order_by(ClaimLegalHold.created_at.desc(), ClaimLegalHold.id.desc())
        ).all()
    )


def get_legal_hold(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    hold_id: UUID,
) -> ClaimLegalHold:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    hold = db.scalar(
        select(ClaimLegalHold).where(
            ClaimLegalHold.id == hold_id,
            ClaimLegalHold.organization_id == organization_id,
            ClaimLegalHold.claim_id == claim_id,
        )
    )
    if hold is None:
        raise RetentionNotFoundError("Legal hold not found")
    return hold


def release_legal_hold(
    hold: ClaimLegalHold,
    *,
    released_by_id: UUID,
    release_reason: str,
    now: datetime | None = None,
) -> bool:
    if hold.released_at is not None:
        return False
    normalized_reason = release_reason.strip()
    if len(normalized_reason) < 3:
        raise ValueError("Legal-hold release reason is required")
    hold.released_at = now or _utc_now()
    hold.released_by_id = released_by_id
    hold.release_reason = normalized_reason
    return True


def _active_holds(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[ClaimLegalHold]:
    return list(
        db.scalars(
            select(ClaimLegalHold)
            .where(
                ClaimLegalHold.organization_id == organization_id,
                ClaimLegalHold.claim_id == claim_id,
                ClaimLegalHold.released_at.is_(None),
            )
            .order_by(ClaimLegalHold.created_at.asc(), ClaimLegalHold.id.asc())
        ).all()
    )


def _pending_proposals(
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


def preview_disposal_eligibility(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    now: datetime | None = None,
) -> DisposalEligibility:
    claim = get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    evaluated_at = _as_utc(now or _utc_now())
    retention_anchor_at = _as_utc(claim.updated_at)
    blockers: list[str] = []

    latest_policy = get_latest_retention_policy(db, organization_id=organization_id)
    current_policy = latest_policy if latest_policy is not None and latest_policy.enabled else None
    if latest_policy is None:
        blockers.append("retention_policy_missing")
    elif not latest_policy.enabled:
        blockers.append("retention_policy_disabled")

    if claim.status not in FINAL_RETENTION_STATUSES:
        blockers.append("claim_not_final")

    active_holds = _active_holds(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
    )
    if active_holds:
        blockers.append("active_legal_hold")

    pending_proposals = _pending_proposals(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
    )
    if pending_proposals:
        blockers.append("pending_legal_hold_proposal")

    claim_expires_at: datetime | None = None
    evidence_expires_at: datetime | None = None
    earliest_eligible_at: datetime | None = None

    if current_policy is not None:
        if not current_policy.disposal_enabled:
            blockers.append("disposal_not_enabled")

        claim_expires_at = retention_anchor_at + timedelta(
            days=current_policy.closed_claim_retention_days
        )
        evidence_anchor = retention_anchor_at
        document_timestamps = db.scalars(
            select(Document.updated_at).where(
                Document.organization_id == organization_id,
                Document.claim_id == claim_id,
            )
        ).all()
        for document_timestamp in document_timestamps:
            document_updated_at = _as_utc(document_timestamp)
            if document_updated_at > evidence_anchor:
                evidence_anchor = document_updated_at
        evidence_expires_at = evidence_anchor + timedelta(
            days=current_policy.evidence_retention_days
        )
        earliest_eligible_at = max(claim_expires_at, evidence_expires_at)
        if evaluated_at < earliest_eligible_at:
            blockers.append("retention_window_active")

    return DisposalEligibility(
        claim_id=claim.id,
        policy_id=None if current_policy is None else current_policy.id,
        policy_number=None if current_policy is None else current_policy.policy_number,
        eligible=not blockers,
        blocking_reasons=blockers,
        active_hold_ids=[hold.id for hold in active_holds],
        pending_proposal_ids=[proposal.id for proposal in pending_proposals],
        retention_anchor_at=retention_anchor_at,
        claim_retention_expires_at=claim_expires_at,
        evidence_retention_expires_at=evidence_expires_at,
        earliest_eligible_at=earliest_eligible_at,
        evaluated_at=evaluated_at,
    )
