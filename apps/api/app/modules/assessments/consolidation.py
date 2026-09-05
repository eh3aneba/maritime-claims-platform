from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claim_packs.recovery_snapshot import build_recovery_snapshot
from app.modules.claims.models import Claim
from app.modules.financial.models import CostItem, CostReviewStatus, FinancialFlag, FinancialFlagStatus, ReserveHistory
from app.modules.technical.service import build_technical_review


DOMAIN_STATUS_DISCLAIMER = (
    "This is a read-only cross-domain claim-review projection for the Initial Assessment workspace. "
    "It does not transfer decision authority into Initial Assessment and does not determine coverage, causation, "
    "liability, recoverability, governing law, time-bar legal effect, reserve adequacy, settlement, payment or claim closure. "
    "Technical, Financial/Reserve and Recovery/Time-Bar retain their canonical human-controlled authorities."
)


def _technical_status(db: Session, *, claim: Claim) -> dict[str, Any]:
    review = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
    topics = list(review.get("matrix") or [])
    stale = [row for row in topics if row.get("decision_state") == "stale"]
    unreviewed = [row for row in topics if row.get("decision_state") == "none"]
    current_decisions = [row for row in topics if row.get("decision_state") == "current"]
    if stale:
        state = "attention_required"
    elif unreviewed:
        state = "open_review"
    elif topics:
        state = "reviewed"
    else:
        state = "no_topics"
    return {
        "authority_module": "technical",
        "state": state,
        "topic_count": len(topics),
        "current_human_decision_count": len(current_decisions),
        "stale_human_decision_count": len(stale),
        "unreviewed_topic_count": len(unreviewed),
    }


def _financial_status(db: Session, *, claim: Claim) -> dict[str, Any]:
    items = list(
        db.scalars(
            select(CostItem).where(
                CostItem.organization_id == claim.organization_id,
                CostItem.claim_id == claim.id,
            )
        )
    )
    flags = list(
        db.scalars(
            select(FinancialFlag).where(
                FinancialFlag.organization_id == claim.organization_id,
                FinancialFlag.claim_id == claim.id,
            )
        )
    )
    open_flags = [row for row in flags if row.status == FinancialFlagStatus.OPEN]
    open_review_statuses = {
        CostReviewStatus.CLAIMED,
        CostReviewStatus.UNDER_REVIEW,
        CostReviewStatus.POTENTIALLY_RECOVERABLE,
        CostReviewStatus.POTENTIALLY_NON_RECOVERABLE,
    }
    open_items = [row for row in items if row.review_status in open_review_statuses]
    if open_flags:
        state = "attention_required"
    elif open_items:
        state = "open_review"
    elif items:
        state = "reviewed"
    else:
        state = "no_items"
    return {
        "authority_module": "financial",
        "state": state,
        "cost_item_count": len(items),
        "open_cost_review_count": len(open_items),
        "open_financial_flag_count": len(open_flags),
    }


def _reserve_status(db: Session, *, claim: Claim) -> dict[str, Any]:
    latest = db.scalar(
        select(ReserveHistory)
        .where(
            ReserveHistory.organization_id == claim.organization_id,
            ReserveHistory.claim_id == claim.id,
        )
        .order_by(ReserveHistory.created_at.desc(), ReserveHistory.id.desc())
        .limit(1)
    )
    if latest is None:
        return {
            "authority_module": "reserve",
            "state": "not_recorded",
            "reserve_id": None,
            "sequence": None,
            "currency": None,
            "amount": None,
            "source_kind": None,
            "reserve_hash": None,
        }
    amount = latest.amount
    return {
        "authority_module": "reserve",
        "state": "recorded",
        "reserve_id": str(latest.id),
        "sequence": latest.sequence,
        "currency": latest.currency,
        "amount": str(amount) if isinstance(amount, Decimal) else str(amount),
        "source_kind": latest.source_kind,
        "reserve_hash": latest.reserve_hash,
    }


def _recovery_status(db: Session, *, claim: Claim) -> dict[str, Any]:
    projection = build_recovery_snapshot(db, claim=claim)
    return {
        "authority_module": "recovery_timebar",
        "state": projection["human_closure_review_state"],
        "blockers": list(projection["closure_review_blockers"]),
        "summary": dict(projection["summary"]),
        "projection_authority": projection["authority"],
        "disclaimer": projection["disclaimer"],
    }


def build_current_domain_status(db: Session, *, claim: Claim) -> dict[str, Any]:
    """Return current read-only status references from canonical claim modules.

    This projection is intentionally not persisted into InitialAssessment and is not part of the approved-content
    digest. It tells an operator what the canonical workspaces currently report while historical assessment content
    remains immutable.
    """

    return {
        "authority": "read_only_cross_domain_projection",
        "disclaimer": DOMAIN_STATUS_DISCLAIMER,
        "technical": _technical_status(db, claim=claim),
        "financial": _financial_status(db, claim=claim),
        "reserve": _reserve_status(db, claim=claim),
        "recovery": _recovery_status(db, claim=claim),
    }
