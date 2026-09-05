from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assessments.models import InitialAssessment
from app.modules.assessments.source_integrity import build_assessment_source_snapshot
from app.modules.claims.models import Claim


def latest_assessment_version(db: Session, *, claim: Claim) -> int | None:
    return db.scalar(
        select(func.max(InitialAssessment.version)).where(
            InitialAssessment.organization_id == claim.organization_id,
            InitialAssessment.claim_id == claim.id,
        )
    )


def list_assessment_history(db: Session, *, claim: Claim) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(InitialAssessment)
            .where(
                InitialAssessment.organization_id == claim.organization_id,
                InitialAssessment.claim_id == claim.id,
            )
            .order_by(InitialAssessment.version.desc())
        )
    )
    if not rows:
        return {
            "claim_id": claim.id,
            "latest_version": None,
            "current_source_fingerprint": None,
            "items": [],
        }

    _, current_source_fingerprint = build_assessment_source_snapshot(db, claim=claim)
    latest_version = rows[0].version
    items: list[dict[str, Any]] = []
    for row in rows:
        if not row.source_fingerprint:
            source_state = "legacy_unbound"
        elif row.source_fingerprint == current_source_fingerprint:
            source_state = "current"
        else:
            source_state = "stale"
        items.append(
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "is_preliminary": row.is_preliminary,
                "is_latest": row.version == latest_version,
                "source_state": source_state,
                "source_fingerprint": row.source_fingerprint,
                "approved_content_hash": row.approved_content_hash,
                "generated_by_id": row.generated_by_id,
                "approved_by_id": row.approved_by_id,
                "approved_at": row.approved_at,
                "created_at": row.created_at,
            }
        )
    return {
        "claim_id": claim.id,
        "latest_version": latest_version,
        "current_source_fingerprint": current_source_fingerprint,
        "items": items,
    }
