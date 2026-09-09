import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.claims.retention_disposal_models import DisposalAuthorization
from app.modules.claims.retention_models import TenantRetentionPolicy
from app.modules.claims.retention_service import (
    RetentionNotFoundError,
    get_claim_for_retention,
    get_current_retention_policy,
    preview_disposal_eligibility,
)
from app.modules.documents.models import Document

AUTHORIZATION_REVIEW_WINDOW = timedelta(hours=24)
ACTIVE_AUTHORIZATION_STATUSES = {"pending_second_approval", "approved"}


class DisposalAuthorizationBlockedError(ValueError):
    def __init__(self, blocking_reasons: list[str]):
        self.blocking_reasons = list(blocking_reasons)
        super().__init__("Disposal authorization is blocked by current retention controls")


@dataclass(frozen=True)
class _Snapshot:
    claim: Claim
    policy: TenantRetentionPolicy
    claim_anchor_at: datetime
    claim_expires_at: datetime
    evidence_anchor_at: datetime
    evidence_expires_at: datetime
    evaluated_at: datetime
    state_fingerprint: str
    snapshot_hash: str
    active_hold_ids: list[str]
    pending_proposal_ids: list[str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _as_utc(value).isoformat()


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _document_state(db: Session, *, organization_id: UUID, claim_id: UUID) -> tuple[list[dict], datetime | None]:
    rows = list(
        db.scalars(
            select(Document)
            .where(
                Document.organization_id == organization_id,
                Document.claim_id == claim_id,
            )
            .order_by(Document.id.asc())
        ).all()
    )
    state: list[dict] = []
    newest: datetime | None = None
    for document in rows:
        updated_at = _as_utc(document.updated_at)
        if newest is None or updated_at > newest:
            newest = updated_at
        state.append(
            {
                "id": str(document.id),
                "file_hash": document.file_hash,
                "version_number": document.version_number,
                "is_current": document.is_current,
                "processing_status": _enum_value(document.processing_status),
                "malware_scan_status": _enum_value(document.malware_scan_status),
                "updated_at": _iso(document.updated_at),
                "deleted_at": _iso(document.deleted_at),
            }
        )
    return state, newest


def _state_fingerprint(
    *,
    claim: Claim,
    document_state: list[dict],
) -> str:
    canonical = json.dumps(
        {
            "claim": {
                "id": str(claim.id),
                "status": _enum_value(claim.status),
                "updated_at": _iso(claim.updated_at),
                "deleted_at": _iso(claim.deleted_at),
            },
            "documents": document_state,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot_hash(
    *,
    claim_id: UUID,
    policy: TenantRetentionPolicy,
    claim_anchor_at: datetime,
    claim_expires_at: datetime,
    evidence_anchor_at: datetime,
    evidence_expires_at: datetime,
    evaluated_at: datetime,
    state_fingerprint: str,
    active_hold_ids: list[str],
    pending_proposal_ids: list[str],
) -> str:
    canonical = json.dumps(
        {
            "claim_id": str(claim_id),
            "retention_policy_id": str(policy.id),
            "retention_policy_number": policy.policy_number,
            "retention_policy_hash": policy.policy_hash,
            "claim_retention_anchor_at": _iso(claim_anchor_at),
            "claim_retention_expires_at": _iso(claim_expires_at),
            "evidence_retention_anchor_at": _iso(evidence_anchor_at),
            "evidence_retention_expires_at": _iso(evidence_expires_at),
            "eligibility_evaluated_at": _iso(evaluated_at),
            "state_fingerprint": state_fingerprint,
            "active_hold_ids": active_hold_ids,
            "pending_proposal_ids": pending_proposal_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_eligible_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    now: datetime | None = None,
) -> _Snapshot:
    evaluated_at = _as_utc(now or _utc_now())
    eligibility = preview_disposal_eligibility(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        now=evaluated_at,
    )
    if not eligibility.eligible:
        raise DisposalAuthorizationBlockedError(eligibility.blocking_reasons)
    if eligibility.active_hold_ids or eligibility.pending_proposal_ids:
        raise DisposalAuthorizationBlockedError(["preservation_blocker_present"])
    if (
        eligibility.policy_id is None
        or eligibility.policy_number is None
        or eligibility.claim_retention_expires_at is None
        or eligibility.evidence_retention_expires_at is None
    ):
        raise DisposalAuthorizationBlockedError(["incomplete_retention_snapshot"])

    claim = get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    policy = get_current_retention_policy(db, organization_id=organization_id)
    if policy is None or policy.id != eligibility.policy_id or policy.policy_number != eligibility.policy_number:
        raise DisposalAuthorizationBlockedError(["retention_policy_drift"])

    document_state, newest_document_at = _document_state(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
    )
    claim_anchor_at = _as_utc(eligibility.retention_anchor_at)
    evidence_anchor_at = claim_anchor_at
    if newest_document_at is not None and newest_document_at > evidence_anchor_at:
        evidence_anchor_at = newest_document_at

    state_fingerprint = _state_fingerprint(claim=claim, document_state=document_state)
    active_hold_ids = [str(item) for item in eligibility.active_hold_ids]
    pending_proposal_ids = [str(item) for item in eligibility.pending_proposal_ids]
    snapshot_hash = _snapshot_hash(
        claim_id=claim.id,
        policy=policy,
        claim_anchor_at=claim_anchor_at,
        claim_expires_at=_as_utc(eligibility.claim_retention_expires_at),
        evidence_anchor_at=evidence_anchor_at,
        evidence_expires_at=_as_utc(eligibility.evidence_retention_expires_at),
        evaluated_at=evaluated_at,
        state_fingerprint=state_fingerprint,
        active_hold_ids=active_hold_ids,
        pending_proposal_ids=pending_proposal_ids,
    )
    return _Snapshot(
        claim=claim,
        policy=policy,
        claim_anchor_at=claim_anchor_at,
        claim_expires_at=_as_utc(eligibility.claim_retention_expires_at),
        evidence_anchor_at=evidence_anchor_at,
        evidence_expires_at=_as_utc(eligibility.evidence_retention_expires_at),
        evaluated_at=evaluated_at,
        state_fingerprint=state_fingerprint,
        snapshot_hash=snapshot_hash,
        active_hold_ids=active_hold_ids,
        pending_proposal_ids=pending_proposal_ids,
    )


def _get_authorization(
    db: Session,
    *,
    organization_id: UUID,
    authorization_id: UUID,
    claim_id: UUID | None = None,
    for_update: bool = False,
) -> DisposalAuthorization:
    stmt = select(DisposalAuthorization).where(
        DisposalAuthorization.id == authorization_id,
        DisposalAuthorization.organization_id == organization_id,
    )
    if claim_id is not None:
        stmt = stmt.where(DisposalAuthorization.claim_id == claim_id)
    if for_update:
        stmt = stmt.with_for_update()
    authorization = db.scalar(stmt)
    if authorization is None:
        raise RetentionNotFoundError("Disposal authorization not found")
    return authorization


def list_disposal_authorizations(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID | None = None,
) -> list[DisposalAuthorization]:
    if claim_id is not None:
        get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    stmt = select(DisposalAuthorization).where(
        DisposalAuthorization.organization_id == organization_id
    )
    if claim_id is not None:
        stmt = stmt.where(DisposalAuthorization.claim_id == claim_id)
    return list(
        db.scalars(
            stmt.order_by(DisposalAuthorization.created_at.desc(), DisposalAuthorization.id.desc())
        ).all()
    )


def get_disposal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    authorization_id: UUID,
    claim_id: UUID | None = None,
) -> DisposalAuthorization:
    if claim_id is not None:
        get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return _get_authorization(
        db,
        organization_id=organization_id,
        authorization_id=authorization_id,
        claim_id=claim_id,
    )


def request_disposal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    requested_by_id: UUID,
    request_reason: str,
    now: datetime | None = None,
) -> DisposalAuthorization:
    normalized_reason = request_reason.strip()
    if len(normalized_reason) < 8:
        raise ValueError("Disposal authorization request reason is required")
    current_time = _as_utc(now or _utc_now())

    # Lock the tenant claim while the authorization snapshot is assembled. The
    # second approval always performs a fresh revalidation as the decisive gate.
    claim = db.scalar(
        select(Claim)
        .where(
            Claim.id == claim_id,
            Claim.organization_id == organization_id,
            Claim.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if claim is None:
        raise RetentionNotFoundError("Claim not found")

    existing = list(
        db.scalars(
            select(DisposalAuthorization).where(
                DisposalAuthorization.organization_id == organization_id,
                DisposalAuthorization.claim_id == claim_id,
                DisposalAuthorization.status.in_(ACTIVE_AUTHORIZATION_STATUSES),
            )
        ).all()
    )
    for authorization in existing:
        if _as_utc(authorization.authorization_expires_at) > current_time:
            raise ValueError("An active disposal authorization already exists for this claim")

    snapshot = _build_eligible_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        now=current_time,
    )
    authorization = DisposalAuthorization(
        organization_id=organization_id,
        claim_id=claim_id,
        retention_policy_id=snapshot.policy.id,
        retention_policy_number=snapshot.policy.policy_number,
        retention_policy_hash=snapshot.policy.policy_hash,
        claim_retention_anchor_at=snapshot.claim_anchor_at,
        claim_retention_expires_at=snapshot.claim_expires_at,
        evidence_retention_anchor_at=snapshot.evidence_anchor_at,
        evidence_retention_expires_at=snapshot.evidence_expires_at,
        eligibility_evaluated_at=snapshot.evaluated_at,
        eligibility_snapshot_hash=snapshot.snapshot_hash,
        state_fingerprint=snapshot.state_fingerprint,
        active_hold_ids=snapshot.active_hold_ids,
        pending_proposal_ids=snapshot.pending_proposal_ids,
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        authorization_expires_at=current_time + AUTHORIZATION_REVIEW_WINDOW,
        status="pending_second_approval",
    )
    db.add(authorization)
    db.flush()
    return authorization


def _invalidate(
    authorization: DisposalAuthorization,
    *,
    actor_id: UUID,
    status: str,
    reason: str,
    now: datetime,
) -> None:
    authorization.status = status
    authorization.invalidated_by_id = actor_id
    authorization.invalidated_at = now
    authorization.decision_reason = reason


def approve_disposal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    approved_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalAuthorization, str]:
    normalized_reason = decision_reason.strip()
    if len(normalized_reason) < 8:
        raise ValueError("Disposal authorization approval reason is required")
    current_time = _as_utc(now or _utc_now())
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        authorization_id=authorization_id,
        claim_id=claim_id,
        for_update=True,
    )

    if authorization.status == "approved":
        return authorization, "unchanged"
    if authorization.status != "pending_second_approval":
        raise ValueError(f"Disposal authorization is already {authorization.status}")
    if authorization.requested_by_id == approved_by_id:
        raise ValueError("Four-eyes approval requires a different Admin")

    if current_time >= _as_utc(authorization.authorization_expires_at):
        _invalidate(
            authorization,
            actor_id=approved_by_id,
            status="expired",
            reason="Authorization review window expired before second approval.",
            now=current_time,
        )
        db.flush()
        return authorization, "expired"

    try:
        snapshot = _build_eligible_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            now=current_time,
        )
    except (DisposalAuthorizationBlockedError, RetentionNotFoundError) as exc:
        if isinstance(exc, DisposalAuthorizationBlockedError):
            reason = "Eligibility changed before approval: " + ", ".join(exc.blocking_reasons)
        else:
            reason = "Claim is no longer available in the authorization tenant."
        _invalidate(
            authorization,
            actor_id=approved_by_id,
            status="invalidated",
            reason=reason,
            now=current_time,
        )
        db.flush()
        return authorization, "invalidated"

    semantic_drift = any(
        (
            snapshot.policy.id != authorization.retention_policy_id,
            snapshot.policy.policy_number != authorization.retention_policy_number,
            snapshot.policy.policy_hash != authorization.retention_policy_hash,
            snapshot.claim_anchor_at != _as_utc(authorization.claim_retention_anchor_at),
            snapshot.claim_expires_at != _as_utc(authorization.claim_retention_expires_at),
            snapshot.evidence_anchor_at != _as_utc(authorization.evidence_retention_anchor_at),
            snapshot.evidence_expires_at != _as_utc(authorization.evidence_retention_expires_at),
            snapshot.state_fingerprint != authorization.state_fingerprint,
            snapshot.active_hold_ids != list(authorization.active_hold_ids or []),
            snapshot.pending_proposal_ids != list(authorization.pending_proposal_ids or []),
        )
    )
    if semantic_drift:
        _invalidate(
            authorization,
            actor_id=approved_by_id,
            status="invalidated",
            reason="Retention policy, claim, or evidence state changed after the request snapshot.",
            now=current_time,
        )
        db.flush()
        return authorization, "invalidated"

    authorization.status = "approved"
    authorization.approved_by_id = approved_by_id
    authorization.approved_at = current_time
    authorization.decision_reason = normalized_reason
    db.flush()
    return authorization, "approved"


def reject_disposal_authorization(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    authorization_id: UUID,
    rejected_by_id: UUID,
    decision_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalAuthorization, str]:
    normalized_reason = decision_reason.strip()
    if len(normalized_reason) < 8:
        raise ValueError("Disposal authorization rejection reason is required")
    current_time = _as_utc(now or _utc_now())
    authorization = _get_authorization(
        db,
        organization_id=organization_id,
        authorization_id=authorization_id,
        claim_id=claim_id,
        for_update=True,
    )
    if authorization.status == "rejected":
        return authorization, "unchanged"
    if authorization.status != "pending_second_approval":
        raise ValueError(f"Disposal authorization is already {authorization.status}")
    if current_time >= _as_utc(authorization.authorization_expires_at):
        _invalidate(
            authorization,
            actor_id=rejected_by_id,
            status="expired",
            reason="Authorization review window expired before a decision.",
            now=current_time,
        )
        db.flush()
        return authorization, "expired"

    authorization.status = "rejected"
    authorization.rejected_by_id = rejected_by_id
    authorization.rejected_at = current_time
    authorization.decision_reason = normalized_reason
    db.flush()
    return authorization, "rejected"
