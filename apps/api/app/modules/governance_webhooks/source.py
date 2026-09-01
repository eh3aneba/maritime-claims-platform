from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.ai_operations.schemas import AIOperationsFilters
from app.modules.ai_operations.service import _filtered_events


def content_free_events_for_delivery(db: Session, organization_id: UUID) -> list[dict]:
    """Return the recomputable Phase 12H content-free read model for outbound delivery.

    This adapter deliberately consumes the existing Phase 12H projection instead of
    reading raw AI/claim source tables again. Phase 12I therefore cannot widen the
    governance payload beyond fields already approved for the operator plane.
    """
    return _filtered_events(db, organization_id, AIOperationsFilters())
