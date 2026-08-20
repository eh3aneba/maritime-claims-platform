from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai_governance.service import (
    require_external_ai_runtime_authorization as require_legacy_ai_runtime_authorization,
)
from app.modules.documents.models import Document
from app.modules.users.models import User


def require_external_ai_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document,
    expected_document_type: str, input_char_count: int,
    requested_by_id: UUID | None = None,
) -> object:
    """Use the newest applicable AI control plane and never fall back around 11G.

    Once a tenant has any Sprint 11G attempt, that attempt becomes the production
    control plane. A held, paused, revoked, completed or expired attempt therefore
    blocks execution rather than silently falling back to the older Sprint 11E
    authorization. Tenants with no 11G attempt retain the existing 11A-11E path.
    """
    if get_settings().app_env.lower().strip() == "production":
        from app.modules.ai_scale_up.service import (
            latest_scale_up_attempt,
            require_scale_up_runtime_authorization,
        )

        if latest_scale_up_attempt(db, organization_id) is not None:
            authorization, _ = require_scale_up_runtime_authorization(
                db, organization_id=organization_id, document=document,
                expected_document_type=expected_document_type,
                input_char_count=input_char_count, requested_by_id=requested_by_id,
            )
            return authorization
    return require_legacy_ai_runtime_authorization(
        db, organization_id=organization_id, document=document,
        expected_document_type=expected_document_type,
        input_char_count=input_char_count, requested_by_id=requested_by_id,
    )


def reserve_production_ai_run(
    db: Session, *, user: User, document: Document, expected_document_type: str,
    input_char_count: int, processing_job_id: UUID,
) -> object:
    """Reserve a content-free run in the active production control plane."""
    from app.modules.ai_scale_up.service import reserve_run_if_scale_up

    scale_up_run = reserve_run_if_scale_up(
        db, user=user, document=document,
        expected_document_type=expected_document_type,
        input_char_count=input_char_count, processing_job_id=processing_job_id,
    )
    if scale_up_run is not None:
        return scale_up_run

    from app.modules.ai_limited_production.service import reserve_run_if_limited_production

    return reserve_run_if_limited_production(
        db, user=user, document=document,
        expected_document_type=expected_document_type,
        input_char_count=input_char_count, processing_job_id=processing_job_id,
    )
