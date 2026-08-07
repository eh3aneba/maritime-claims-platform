from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


def write_audit_log(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    details: str | None = None,
) -> AuditLog:
    event = AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=old_values,
        new_values=new_values,
        details=details,
    )
    db.add(event)
    return event
