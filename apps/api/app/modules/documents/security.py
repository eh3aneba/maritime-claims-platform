from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document


def get_document_for_tenant(
    db: Session,
    *,
    document_id: UUID,
    claim_id: UUID,
    organization_id: UUID,
) -> Document | None:
    return db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.claim_id == claim_id,
            Document.organization_id == organization_id,
            Document.deleted_at.is_(None),
        )
    )
