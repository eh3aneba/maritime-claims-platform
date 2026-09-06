from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.email_ingestion.models import EmailAdapterRun, EmailProviderAdapter
from app.modules.email_ingestion.provider_checkpoint_handoff import (
    execute_provider_adapter_with_checkpoint_handoff,
)
from app.modules.email_ingestion.provider_live_activation import require_live_provider_activation
from app.modules.email_ingestion.schemas import EmailProviderExecutionRequest
from app.modules.users.models import User


def execute_activated_provider_adapter(
    db: Session,
    adapter: EmailProviderAdapter,
    user: User,
    payload: EmailProviderExecutionRequest,
) -> dict:
    # Exact replay is a DB-only recovery path and must remain available even if
    # live authority was later invalidated by credential/lifecycle changes.
    existing = db.scalar(
        select(EmailAdapterRun.id).where(
            EmailAdapterRun.adapter_id == adapter.id,
            EmailAdapterRun.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is None:
        require_live_provider_activation(adapter)
    return execute_provider_adapter_with_checkpoint_handoff(db, adapter, user, payload)
