from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.models import Claim


def get_claim_for_tenant(db: Session, *, claim_id: UUID, organization_id: UUID) -> Claim | None:
    """Return a claim only when it belongs to the authenticated organization."""
    return db.scalar(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.organization_id == organization_id,
            Claim.deleted_at.is_(None),
        )
    )
