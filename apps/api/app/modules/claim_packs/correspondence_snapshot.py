from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim
from app.modules.correspondence.models import (
    ClaimCorrespondence,
    CorrespondenceReviewDecision,
    CorrespondenceSensitivity,
    CorrespondenceStatus,
)


MAX_CORRESPONDENCE_RECORDS = 50
MAX_BODY_EXCERPT_CHARS = 4000
_INCLUDED_STATUSES = {
    CorrespondenceStatus.SENT_EXTERNALLY,
    CorrespondenceStatus.RECEIVED_EXTERNAL,
    CorrespondenceStatus.FILED_INTERNAL,
}
_EXCLUDED_SENSITIVITIES = {
    CorrespondenceSensitivity.PRIVILEGED_CONFIDENTIAL,
    CorrespondenceSensitivity.WITHOUT_PREJUDICE,
}


def _enum(value):
    return value.value if hasattr(value, "value") else value


def _sort_time(item: ClaimCorrespondence) -> datetime:
    return item.occurred_at or item.sent_at or item.created_at


def _latest_reviews(
    db: Session,
    *,
    claim: Claim,
    correspondence_ids: list,
) -> dict:
    if not correspondence_ids:
        return {}
    decisions = list(
        db.scalars(
            select(CorrespondenceReviewDecision)
            .where(
                CorrespondenceReviewDecision.organization_id == claim.organization_id,
                CorrespondenceReviewDecision.claim_id == claim.id,
                CorrespondenceReviewDecision.correspondence_id.in_(correspondence_ids),
            )
            .order_by(
                CorrespondenceReviewDecision.correspondence_id.asc(),
                CorrespondenceReviewDecision.review_number.asc(),
            )
        )
    )
    latest: dict = {}
    for decision in decisions:
        latest[decision.correspondence_id] = decision
    return latest


def build_correspondence_snapshot(db: Session, *, claim: Claim) -> dict[str, Any]:
    """Build bounded downstream reporting context from governed historical correspondence.

    Privileged/without-prejudice markings are exclusion signals only. This projection does not
    decide whether legal privilege exists and never treats inclusion/exclusion as a waiver decision.
    """

    historical = list(
        db.scalars(
            select(ClaimCorrespondence).where(
                ClaimCorrespondence.organization_id == claim.organization_id,
                ClaimCorrespondence.claim_id == claim.id,
                ClaimCorrespondence.status.in_(_INCLUDED_STATUSES),
            )
        )
    )
    excluded_sensitive = [item for item in historical if item.sensitivity in _EXCLUDED_SENSITIVITIES]
    eligible = [item for item in historical if item.sensitivity not in _EXCLUDED_SENSITIVITIES]
    eligible.sort(key=lambda item: (_sort_time(item), str(item.id)), reverse=True)
    omitted_for_bound_count = max(0, len(eligible) - MAX_CORRESPONDENCE_RECORDS)
    selected = eligible[:MAX_CORRESPONDENCE_RECORDS]
    selected.sort(key=lambda item: (_sort_time(item), str(item.id)))
    latest_reviews = _latest_reviews(db, claim=claim, correspondence_ids=[item.id for item in selected])

    items: list[dict[str, Any]] = []
    for item in selected:
        review = latest_reviews.get(item.id)
        body_excerpt = item.body[:MAX_BODY_EXCERPT_CHARS]
        items.append(
            {
                "id": str(item.id),
                "direction": _enum(item.direction),
                "kind": _enum(item.kind),
                "status": _enum(item.status),
                "sensitivity": _enum(item.sensitivity),
                "channel": _enum(item.channel) if item.channel else None,
                "sender_label": item.sender_label,
                "recipient_label": item.recipient_label,
                "subject": item.subject,
                "body_excerpt": body_excerpt,
                "body_truncated": len(item.body) > MAX_BODY_EXCERPT_CHARS,
                "external_reference": item.external_reference,
                "occurred_at": item.occurred_at,
                "sent_at": item.sent_at,
                "created_at": item.created_at,
                "request_batch_id": str(item.request_batch_id) if item.request_batch_id else None,
                "requirement_ids": sorted(str(value) for value in (item.requirement_ids or [])),
                "state_fingerprint": item.state_fingerprint,
                "state_version": item.state_version,
                "content_hash": item.content_hash,
                "sent_review_hash": item.sent_review_hash,
                "latest_review": (
                    {
                        "review_number": review.review_number,
                        "action": review.action,
                        "review_hash": review.review_hash,
                        "content_hash": review.content_hash,
                        "correspondence_state_fingerprint": review.correspondence_state_fingerprint,
                        "request_context_fingerprint": review.request_context_fingerprint,
                        "reviewed_at": review.reviewed_at,
                    }
                    if review
                    else None
                ),
            }
        )

    return {
        "authority": "downstream_reporting_context_only",
        "disclaimer": (
            "This is a bounded projection of human-recorded correspondence history for Claim Pack reporting only. "
            "The platform does not send communications or determine coverage, causation, liability, recoverability, "
            "time-bar legal effect, settlement, payment or claim closure."
        ),
        "confidentiality_notice": (
            "Privileged & Confidential and Without Prejudice records are excluded by default. These markings are "
            "handling signals only; this export does not determine legal privilege and does not waive it."
        ),
        "policy": {
            "max_records": MAX_CORRESPONDENCE_RECORDS,
            "max_body_excerpt_chars": MAX_BODY_EXCERPT_CHARS,
            "included_statuses": sorted(status.value for status in _INCLUDED_STATUSES),
            "excluded_sensitive_markings": sorted(value.value for value in _EXCLUDED_SENSITIVITIES),
            "excluded_sensitive_count": len(excluded_sensitive),
            "omitted_for_bound_count": omitted_for_bound_count,
        },
        "summary": {
            "included_count": len(items),
            "excluded_sensitive_count": len(excluded_sensitive),
            "omitted_for_bound_count": omitted_for_bound_count,
        },
        "items": items,
    }
