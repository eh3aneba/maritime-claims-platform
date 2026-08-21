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
    """Use the newest applicable Production AI control plane and fail closed.

    Sprint 11I takes precedence over Sprint 11G. Once a tenant has any 11I
    attempt, a held, paused, revoked, completed or expired 11I attempt blocks
    execution rather than falling back to 11G/11E. If no 11I attempt exists,
    the existing 11G precedence rule remains unchanged.
    """
    if get_settings().app_env.lower().strip() == "production":
        from app.modules.ai_broader_production.service import (
            latest_broader_production_attempt,
            require_broader_production_runtime_authorization,
        )

        if latest_broader_production_attempt(db, organization_id) is not None:
            authorization, _ = require_broader_production_runtime_authorization(
                db, organization_id=organization_id, document=document,
                expected_document_type=expected_document_type,
                input_char_count=input_char_count, requested_by_id=requested_by_id,
            )
            return authorization

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
    """Reserve a content-free run in the newest Production control plane."""
    from app.modules.ai_broader_production.service import reserve_run_if_broader_production

    broader_run = reserve_run_if_broader_production(
        db, user=user, document=document,
        expected_document_type=expected_document_type,
        input_char_count=input_char_count, processing_job_id=processing_job_id,
    )
    if broader_run is not None:
        return broader_run

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
