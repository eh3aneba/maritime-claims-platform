import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.retention_disposal_dry_run_service import _as_utc
from app.modules.claims.retention_disposal_quarantine_models import DisposalQuarantineStage
from app.modules.claims.retention_disposal_quarantine_service import (
    revalidate_disposal_quarantine_stage,
)
from app.modules.claims.retention_disposal_release_models import DisposalReleaseReview
from app.modules.claims.retention_service import RetentionNotFoundError, get_claim_for_retention

RELEASE_MINIMUM_QUARANTINE_DWELL = timedelta(minutes=5)
RELEASE_REVIEW_WINDOW = timedelta(minutes=5)


class DisposalReleasePreflightError(ValueError):
    def __init__(
        self,
        *,
        outcome: str,
        blocking_reasons: list[str],
        stage_id: UUID | None = None,
        stage_state_changed: bool = False,
    ):
        self.outcome = outcome
        self.blocking_reasons = list(blocking_reasons)
        self.stage_id = stage_id
        self.stage_state_changed = stage_state_changed
        super().__init__(
            "Disposal release review preflight failed: "
            + ", ".join(self.blocking_reasons)
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _as_utc(value).isoformat()


def _canonical_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_reason(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < 5:
        raise ValueError("Release review reason must contain at least 5 characters")
    if len(normalized) > 2000:
        raise ValueError("Release review reason must not exceed 2000 characters")
    return normalized


def _get_review(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
    for_update: bool = False,
) -> DisposalReleaseReview:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    stmt = select(DisposalReleaseReview).where(
        DisposalReleaseReview.id == review_id,
        DisposalReleaseReview.organization_id == organization_id,
        DisposalReleaseReview.claim_id == claim_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    review = db.scalar(stmt)
    if review is None:
        raise RetentionNotFoundError("Disposal release review not found")
    return review


def _release_snapshot(
    stage: DisposalQuarantineStage,
    *,
    minimum_release_eligible_at: datetime,
) -> dict:
    return {
        "organization_id": str(stage.organization_id),
        "claim_id": str(stage.claim_id),
        "disposal_quarantine_stage_id": str(stage.id),
        "disposal_dry_run_ceremony_id": str(stage.disposal_dry_run_ceremony_id),
        "disposal_execution_manifest_id": str(stage.disposal_execution_manifest_id),
        "disposal_authorization_id": str(stage.disposal_authorization_id),
        "retention_policy_id": str(stage.retention_policy_id),
        "manifest_hash": stage.manifest_hash,
        "inventory_hash": stage.inventory_hash,
        "authorization_lineage_hash": stage.authorization_lineage_hash,
        "ceremony_hash": stage.ceremony_hash,
        "plan_hash": stage.plan_hash,
        "attestation_hash": stage.attestation_hash,
        "overlay_hash": stage.overlay_hash,
        "stage_hash": stage.stage_hash,
        "retention_policy_number": stage.retention_policy_number,
        "retention_policy_hash": stage.retention_policy_hash,
        "document_count": stage.document_count,
        "total_file_size_bytes": stage.total_file_size_bytes,
        "quarantine_staged_by_id": str(stage.staged_by_id),
        "quarantine_staged_at": _iso(stage.staged_at),
        "quarantine_stage_expires_at": _iso(stage.stage_expires_at),
        "minimum_release_eligible_at": _iso(minimum_release_eligible_at),
        "logical_overlay_only": True,
        "physical_quarantine_performed": False,
        "execution_authority_created": False,
        "destructive_action_performed": False,
    }


def _review_hash(
    *,
    snapshot_hash: str,
    requested_by_id: UUID,
    request_reason: str,
    requested_at: datetime,
    review_expires_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "release_snapshot_hash": snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "request_reason": request_reason,
            "requested_at": _iso(requested_at),
            "review_expires_at": _iso(review_expires_at),
            "execution_authority_created": False,
            "physical_quarantine_performed": False,
            "destructive_action_performed": False,
        }
    )


def _approval_hash(
    review: DisposalReleaseReview,
    *,
    approved_by_id: UUID,
    approved_at: datetime,
    approval_reason: str,
    stage_last_revalidated_at: datetime | None,
) -> str:
    return _canonical_hash(
        {
            "review_id": str(review.id),
            "review_hash": review.review_hash,
            "release_snapshot_hash": review.release_snapshot_hash,
            "stage_hash": review.stage_hash,
            "approved_by_id": str(approved_by_id),
            "approved_at": _iso(approved_at),
            "approval_reason": approval_reason,
            "stage_last_revalidated_at": _iso(stage_last_revalidated_at),
            "execution_authority_created": False,
            "physical_quarantine_performed": False,
            "destructive_action_performed": False,
        }
    )


def _stored_review_integrity_ok(review: DisposalReleaseReview) -> bool:
    snapshot = dict(review.release_snapshot or {})
    if _canonical_hash(snapshot) != review.release_snapshot_hash:
        return False
    expected_review_hash = _review_hash(
        snapshot_hash=review.release_snapshot_hash,
        requested_by_id=review.requested_by_id,
        request_reason=review.request_reason,
        requested_at=_as_utc(review.requested_at),
        review_expires_at=_as_utc(review.review_expires_at),
    )
    return expected_review_hash == review.review_hash


def _stage_failure(
    stage: DisposalQuarantineStage,
    *,
    outcome: str,
) -> DisposalReleasePreflightError:
    mapped = "expired" if stage.status == "expired" else "invalidated"
    reason = stage.terminal_reason or f"quarantine_stage_status_{stage.status}"
    return DisposalReleasePreflightError(
        outcome=mapped,
        blocking_reasons=[reason],
        stage_id=stage.id,
        stage_state_changed=outcome not in {"unchanged", "revalidated"},
    )


def _revalidate_live_stage(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    stage_id: UUID,
    actor_id: UUID,
    now: datetime,
) -> DisposalQuarantineStage:
    stage, outcome = revalidate_disposal_quarantine_stage(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        stage_id=stage_id,
        actor_id=actor_id,
        now=now,
    )
    if stage.status != "staged":
        raise _stage_failure(stage, outcome=outcome)
    return stage


def request_disposal_release_review(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    stage_id: UUID,
    requested_by_id: UUID,
    request_reason: str,
    now: datetime | None = None,
) -> DisposalReleaseReview:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(request_reason)
    existing = db.scalar(
        select(DisposalReleaseReview).where(
            DisposalReleaseReview.organization_id == organization_id,
            DisposalReleaseReview.disposal_quarantine_stage_id == stage_id,
        )
    )
    if existing is not None:
        raise ValueError(
            "A release review already exists for this quarantine stage; "
            "fresh authorization, manifest, ceremony, and stage are required for another review"
        )

    stage = _revalidate_live_stage(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        stage_id=stage_id,
        actor_id=requested_by_id,
        now=current_time,
    )
    minimum_release_eligible_at = _as_utc(stage.staged_at) + RELEASE_MINIMUM_QUARANTINE_DWELL
    if current_time < minimum_release_eligible_at:
        raise DisposalReleasePreflightError(
            outcome="blocked",
            blocking_reasons=["minimum_quarantine_dwell_not_met"],
            stage_id=stage.id,
        )
    if current_time >= _as_utc(stage.stage_expires_at):
        raise DisposalReleasePreflightError(
            outcome="expired",
            blocking_reasons=["quarantine_stage_expired_before_release_review"],
            stage_id=stage.id,
        )

    snapshot = _release_snapshot(
        stage,
        minimum_release_eligible_at=minimum_release_eligible_at,
    )
    snapshot_hash = _canonical_hash(snapshot)
    review_expires_at = min(
        current_time + RELEASE_REVIEW_WINDOW,
        _as_utc(stage.stage_expires_at),
    )
    if review_expires_at <= current_time:
        raise DisposalReleasePreflightError(
            outcome="expired",
            blocking_reasons=["insufficient_live_quarantine_window_for_release_review"],
            stage_id=stage.id,
        )
    review_hash = _review_hash(
        snapshot_hash=snapshot_hash,
        requested_by_id=requested_by_id,
        request_reason=reason,
        requested_at=current_time,
        review_expires_at=review_expires_at,
    )
    review = DisposalReleaseReview(
        organization_id=organization_id,
        claim_id=claim_id,
        disposal_quarantine_stage_id=stage.id,
        disposal_dry_run_ceremony_id=stage.disposal_dry_run_ceremony_id,
        disposal_execution_manifest_id=stage.disposal_execution_manifest_id,
        disposal_authorization_id=stage.disposal_authorization_id,
        retention_policy_id=stage.retention_policy_id,
        manifest_hash=stage.manifest_hash,
        inventory_hash=stage.inventory_hash,
        authorization_lineage_hash=stage.authorization_lineage_hash,
        ceremony_hash=stage.ceremony_hash,
        plan_hash=stage.plan_hash,
        attestation_hash=stage.attestation_hash,
        overlay_hash=stage.overlay_hash,
        stage_hash=stage.stage_hash,
        retention_policy_number=stage.retention_policy_number,
        retention_policy_hash=stage.retention_policy_hash,
        release_snapshot=snapshot,
        release_snapshot_hash=snapshot_hash,
        review_hash=review_hash,
        document_count=stage.document_count,
        total_file_size_bytes=stage.total_file_size_bytes,
        quarantine_staged_by_id=stage.staged_by_id,
        quarantine_staged_at=stage.staged_at,
        quarantine_stage_expires_at=stage.stage_expires_at,
        minimum_release_eligible_at=minimum_release_eligible_at,
        requested_by_id=requested_by_id,
        request_reason=reason,
        requested_at=current_time,
        review_expires_at=review_expires_at,
        last_revalidated_at=current_time,
        status="pending_final_approval",
    )
    db.add(review)
    db.flush()
    return review


def list_disposal_release_reviews(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
) -> list[DisposalReleaseReview]:
    get_claim_for_retention(db, organization_id=organization_id, claim_id=claim_id)
    return list(
        db.scalars(
            select(DisposalReleaseReview)
            .where(
                DisposalReleaseReview.organization_id == organization_id,
                DisposalReleaseReview.claim_id == claim_id,
            )
            .order_by(
                DisposalReleaseReview.created_at.desc(),
                DisposalReleaseReview.id.desc(),
            )
        ).all()
    )


def get_disposal_release_review(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
) -> DisposalReleaseReview:
    return _get_review(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        review_id=review_id,
    )


def _terminalize(
    review: DisposalReleaseReview,
    *,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> None:
    review.status = status
    review.terminal_by_id = actor_id
    review.terminal_at = now
    review.terminal_reason = reason
    review.last_revalidated_at = now


def _live_snapshot_matches(
    review: DisposalReleaseReview,
    stage: DisposalQuarantineStage,
) -> bool:
    minimum_release_eligible_at = _as_utc(stage.staged_at) + RELEASE_MINIMUM_QUARANTINE_DWELL
    snapshot = _release_snapshot(
        stage,
        minimum_release_eligible_at=minimum_release_eligible_at,
    )
    return all(
        (
            stage.id == review.disposal_quarantine_stage_id,
            stage.disposal_dry_run_ceremony_id == review.disposal_dry_run_ceremony_id,
            stage.disposal_execution_manifest_id == review.disposal_execution_manifest_id,
            stage.disposal_authorization_id == review.disposal_authorization_id,
            stage.retention_policy_id == review.retention_policy_id,
            stage.manifest_hash == review.manifest_hash,
            stage.inventory_hash == review.inventory_hash,
            stage.authorization_lineage_hash == review.authorization_lineage_hash,
            stage.ceremony_hash == review.ceremony_hash,
            stage.plan_hash == review.plan_hash,
            stage.attestation_hash == review.attestation_hash,
            stage.overlay_hash == review.overlay_hash,
            stage.stage_hash == review.stage_hash,
            stage.retention_policy_number == review.retention_policy_number,
            stage.retention_policy_hash == review.retention_policy_hash,
            stage.document_count == review.document_count,
            stage.total_file_size_bytes == review.total_file_size_bytes,
            stage.staged_by_id == review.quarantine_staged_by_id,
            _as_utc(stage.staged_at) == _as_utc(review.quarantine_staged_at),
            _as_utc(stage.stage_expires_at) == _as_utc(review.quarantine_stage_expires_at),
            minimum_release_eligible_at == _as_utc(review.minimum_release_eligible_at),
            snapshot == dict(review.release_snapshot or {}),
            _canonical_hash(snapshot) == review.release_snapshot_hash,
        )
    )


def approve_disposal_release_review(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
    approved_by_id: UUID,
    approval_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalReleaseReview, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(approval_reason)
    review = _get_review(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        review_id=review_id,
        for_update=True,
    )
    if review.status != "pending_final_approval":
        return review, "unchanged"
    if review.requested_by_id == approved_by_id:
        raise ValueError("Release requester cannot approve their own final release review")
    if review.quarantine_staged_by_id == approved_by_id:
        raise ValueError("Quarantine stage creator cannot approve the final release review")
    if current_time >= _as_utc(review.review_expires_at):
        _terminalize(
            review,
            status="expired",
            actor_id=approved_by_id,
            reason="Final release review validity window expired.",
            now=current_time,
        )
        db.flush()
        return review, "expired"
    if not _stored_review_integrity_ok(review):
        _terminalize(
            review,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Stored final release review integrity check failed.",
            now=current_time,
        )
        db.flush()
        return review, "invalidated"

    try:
        stage = _revalidate_live_stage(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            stage_id=review.disposal_quarantine_stage_id,
            actor_id=approved_by_id,
            now=current_time,
        )
    except DisposalReleasePreflightError as exc:
        mapped = "expired" if exc.outcome == "expired" else "invalidated"
        _terminalize(
            review,
            status=mapped,
            actor_id=approved_by_id,
            reason="; ".join(exc.blocking_reasons),
            now=current_time,
        )
        db.flush()
        return review, mapped

    if current_time < _as_utc(review.minimum_release_eligible_at):
        _terminalize(
            review,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Minimum quarantine dwell is no longer consistent with the release review.",
            now=current_time,
        )
        db.flush()
        return review, "invalidated"
    if not _live_snapshot_matches(review, stage):
        _terminalize(
            review,
            status="invalidated",
            actor_id=approved_by_id,
            reason="Quarantine stage or release snapshot lineage drift detected.",
            now=current_time,
        )
        db.flush()
        return review, "invalidated"

    review.status = "approved"
    review.approved_by_id = approved_by_id
    review.approved_at = current_time
    review.approval_reason = reason
    review.approval_hash = _approval_hash(
        review,
        approved_by_id=approved_by_id,
        approved_at=current_time,
        approval_reason=reason,
        stage_last_revalidated_at=stage.last_revalidated_at,
    )
    review.last_revalidated_at = current_time
    db.flush()
    return review, "approved"


def reject_disposal_release_review(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
    rejected_by_id: UUID,
    rejection_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalReleaseReview, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(rejection_reason)
    review = _get_review(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        review_id=review_id,
        for_update=True,
    )
    if review.status != "pending_final_approval":
        return review, "unchanged"
    if current_time >= _as_utc(review.review_expires_at):
        _terminalize(
            review,
            status="expired",
            actor_id=rejected_by_id,
            reason="Final release review validity window expired before rejection.",
            now=current_time,
        )
        db.flush()
        return review, "expired"
    _terminalize(
        review,
        status="rejected",
        actor_id=rejected_by_id,
        reason=reason,
        now=current_time,
    )
    db.flush()
    return review, "rejected"


def cancel_disposal_release_review(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    review_id: UUID,
    cancelled_by_id: UUID,
    cancellation_reason: str,
    now: datetime | None = None,
) -> tuple[DisposalReleaseReview, str]:
    current_time = _as_utc(now or _utc_now())
    reason = _normalize_reason(cancellation_reason)
    review = _get_review(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        review_id=review_id,
        for_update=True,
    )
    if review.status != "pending_final_approval":
        return review, "unchanged"
    if current_time >= _as_utc(review.review_expires_at):
        _terminalize(
            review,
            status="expired",
            actor_id=cancelled_by_id,
            reason="Final release review validity window expired before cancellation.",
            now=current_time,
        )
        db.flush()
        return review, "expired"
    _terminalize(
        review,
        status="cancelled",
        actor_id=cancelled_by_id,
        reason=reason,
        now=current_time,
    )
    db.flush()
    return review, "cancelled"
