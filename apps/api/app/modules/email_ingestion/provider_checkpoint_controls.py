from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.email_ingestion.models import (
    EmailAdapterRun,
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailProviderAdapter,
)
from app.modules.email_ingestion.provider_gmail_history import execute_gmail_history_adapter
from app.modules.email_ingestion.provider_operations import (
    _consecutive_failures,
    execute_governed_provider_adapter,
    list_provider_reconciliation,
)
from app.modules.email_ingestion.schemas import (
    EmailProviderExecutionRequest,
    GmailCheckpointResetRequest,
)
from app.modules.users.models import User

_NORMAL_INTERVAL_MINUTES = 15
_MAX_BACKOFF_MINUTES = 120
_RESYNC_FAILURE_CODES = {
    "gmail_history_resync_required",
    "gmail_checkpoint_resync_required",
}


def _connection_for_adapter(db: Session, adapter: EmailProviderAdapter) -> EmailIngestionConnection | None:
    return db.scalar(
        select(EmailIngestionConnection).where(
            EmailIngestionConnection.id == adapter.connection_id,
            EmailIngestionConnection.organization_id == adapter.organization_id,
        )
    )


def execute_governed_provider_adapter_with_history(
    db: Session,
    adapter: EmailProviderAdapter,
    user: User,
    payload: EmailProviderExecutionRequest,
) -> dict:
    if adapter.provider_kind != "gmail_api":
        return execute_governed_provider_adapter(db, adapter, user, payload)

    result = execute_gmail_history_adapter(db, adapter, user, payload)
    if result["replayed"]:
        return result

    run: EmailAdapterRun = result["run"]
    finished_at = run.finished_at or datetime.now(UTC)
    if run.status == "failed":
        failure_streak = _consecutive_failures(db, adapter.id)
        backoff_minutes = min(
            _NORMAL_INTERVAL_MINUTES * (2 ** max(failure_streak - 1, 0)),
            _MAX_BACKOFF_MINUTES,
        )
        adapter.next_sync_at = finished_at + timedelta(minutes=backoff_minutes)
        write_audit_log(
            db,
            organization_id=adapter.organization_id,
            user_id=user.id,
            action="SCHEDULE_EMAIL_PROVIDER_RETRY",
            entity_type="email_provider_adapter",
            entity_id=adapter.id,
            new_values={
                "failure_streak": failure_streak,
                "backoff_minutes": backoff_minutes,
                "checkpoint_resync_required": run.failure_summary in _RESYNC_FAILURE_CODES,
            },
            details=(
                "Bounded content-free retry/reconciliation schedule. No automatic Gmail resync or checkpoint reset is performed."
            ),
        )
    else:
        adapter.next_sync_at = finished_at + timedelta(minutes=_NORMAL_INTERVAL_MINUTES)
    db.commit()
    return result


def list_provider_reconciliation_with_checkpoint_controls(db: Session, user: User) -> dict:
    result = list_provider_reconciliation(db, user)
    for item in result["items"]:
        adapter_id = UUID(item["adapter_id"])
        adapter = db.get(EmailProviderAdapter, adapter_id)
        if adapter is None or adapter.organization_id != user.organization_id:
            continue
        last_run = db.scalar(
            select(EmailAdapterRun)
            .where(EmailAdapterRun.adapter_id == adapter.id)
            .order_by(EmailAdapterRun.started_at.desc())
            .limit(1)
        )
        last_failure_code = (
            last_run.failure_summary if last_run is not None and last_run.status == "failed" else None
        )
        connection = _connection_for_adapter(db, adapter)
        active_source = (
            adapter.status == "active"
            and connection is not None
            and connection.status == EmailConnectionStatus.ACTIVE
        )
        reset_eligible_failure = last_failure_code in _RESYNC_FAILURE_CODES
        reset_available = bool(
            adapter.provider_kind == "gmail_api"
            and reset_eligible_failure
            and adapter.checkpoint_hash
            and active_source
        )

        item["last_run_failure_code"] = last_failure_code
        item["checkpoint_reset_available"] = reset_available
        if adapter.provider_kind == "microsoft_graph" and adapter.checkpoint_hash:
            item["checkpoint_semantics"] = "graph_delta"
        elif adapter.provider_kind == "gmail_api" and adapter.checkpoint_hash and not reset_eligible_failure:
            # The raw checkpoint remains external. The application deliberately
            # cannot infer legacy-vs-v1 semantics from a hash alone until execution
            # proves it; expose no stronger claim here.
            item["checkpoint_semantics"] = None
        else:
            item["checkpoint_semantics"] = None

        if adapter.provider_kind == "gmail_api" and reset_eligible_failure:
            if adapter.checkpoint_hash:
                item["operational_state"] = "reconciliation_required"
            elif active_source:
                # An explicit reset has cleared only the stale cursor. The next
                # operator execution performs a fresh bootstrap.
                item["operational_state"] = "due"

    return result


def reset_gmail_checkpoint(
    db: Session,
    adapter: EmailProviderAdapter,
    user: User,
    payload: GmailCheckpointResetRequest,
) -> dict:
    if not payload.confirm_reset:
        raise HTTPException(422, "Explicit Gmail checkpoint reset confirmation is required")
    if adapter.organization_id != user.organization_id:
        raise HTTPException(404, "Email provider adapter not found")
    if adapter.provider_kind != "gmail_api":
        raise HTTPException(409, "Checkpoint reset is only available for Gmail history adapters")
    connection = _connection_for_adapter(db, adapter)
    if connection is None:
        raise HTTPException(404, "Email ingestion connection not found")
    if adapter.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both be active")

    last_run = db.scalar(
        select(EmailAdapterRun)
        .where(EmailAdapterRun.adapter_id == adapter.id)
        .order_by(EmailAdapterRun.started_at.desc())
        .limit(1)
    )
    if (
        last_run is None
        or last_run.status != "failed"
        or last_run.failure_summary not in _RESYNC_FAILURE_CODES
    ):
        raise HTTPException(409, "Latest Gmail execution does not authorize a checkpoint reset")
    if adapter.checkpoint_hash is None:
        raise HTTPException(409, "Gmail checkpoint has already been reset")

    failure_code = last_run.failure_summary
    adapter.checkpoint_hash = None
    adapter.next_sync_at = datetime.now(UTC)
    write_audit_log(
        db,
        organization_id=adapter.organization_id,
        user_id=user.id,
        action="RESET_GMAIL_PROVIDER_CHECKPOINT",
        entity_type="email_provider_adapter",
        entity_id=adapter.id,
        new_values={
            "failure_code": failure_code,
            "checkpoint_cleared": True,
            "bootstrap_required": True,
        },
        details=(
            "Human-authorized Gmail cursor reset after a fixed resync-required failure. Raw checkpoint values, credentials and mailbox content are excluded."
        ),
    )
    db.commit()
    db.refresh(adapter)
    return {
        "adapter_id": adapter.id,
        "reset_performed": True,
        "last_failure_code": failure_code,
        "next_sync_at": adapter.next_sync_at,
    }
