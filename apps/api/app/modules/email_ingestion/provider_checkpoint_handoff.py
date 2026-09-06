from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.email_ingestion import provider_gmail_history
from app.modules.email_ingestion.models import (
    EmailAdapterRun,
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.email_ingestion.provider_checkpoint_controls import (
    list_provider_reconciliation_with_checkpoint_controls,
    reset_gmail_checkpoint,
)
from app.modules.email_ingestion.provider_execution import (
    ProviderExecutionFailure,
    _fetch_graph_page,
    _hash_checkpoint,
    _resolve_credential,
)
from app.modules.email_ingestion.provider_operations import _consecutive_failures
from app.modules.email_ingestion.provider_source import _stage_email
from app.modules.email_ingestion.schemas import (
    CheckpointHandoffAbandonRequest,
    CheckpointHandoffAckRequest,
    EmailProviderExecutionRequest,
    GmailCheckpointResetRequest,
)
from app.modules.users.models import User

_NORMAL_INTERVAL_MINUTES = 15
_MAX_BACKOFF_MINUTES = 120
_PULL_KINDS = {"microsoft_graph", "gmail_api"}


def _connection_for_adapter(
    db: Session,
    adapter: EmailProviderAdapter,
) -> EmailIngestionConnection | None:
    return db.scalar(
        select(EmailIngestionConnection).where(
            EmailIngestionConnection.id == adapter.connection_id,
            EmailIngestionConnection.organization_id == adapter.organization_id,
        )
    )


def _pending_checkpoint_run(
    db: Session,
    adapter_id: UUID,
) -> EmailAdapterRun | None:
    return db.scalar(
        select(EmailAdapterRun)
        .where(
            EmailAdapterRun.adapter_id == adapter_id,
            EmailAdapterRun.checkpoint_handoff_status == "pending",
        )
        .order_by(EmailAdapterRun.started_at.desc())
        .limit(1)
    )


def _existing_run(
    db: Session,
    adapter_id: UUID,
    idempotency_key: str,
) -> EmailAdapterRun | None:
    return db.scalar(
        select(EmailAdapterRun).where(
            EmailAdapterRun.adapter_id == adapter_id,
            EmailAdapterRun.idempotency_key == idempotency_key,
        )
    )


def _record_run(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    user: User,
    payload: EmailProviderExecutionRequest,
    status: str,
    messages_seen: int,
    messages_ingested: int,
    next_checkpoint: str | None,
    failure_summary: str | None,
) -> EmailAdapterRun:
    now = datetime.now(UTC)
    checkpoint_hash = _hash_checkpoint(next_checkpoint)
    handoff_status = (
        "pending" if status == "succeeded" and checkpoint_hash is not None else "not_required"
    )
    run = EmailAdapterRun(
        organization_id=adapter.organization_id,
        adapter_id=adapter.id,
        initiated_by_id=user.id,
        idempotency_key=payload.idempotency_key,
        trigger=payload.trigger,
        status=status,
        messages_seen=messages_seen,
        messages_ingested=messages_ingested,
        checkpoint_hash=checkpoint_hash if status == "succeeded" else None,
        checkpoint_handoff_status=handoff_status,
        failure_summary=failure_summary,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    adapter.last_sync_at = now
    # A proposed cursor is deliberately not made active here. Until ACK, the
    # previous adapter.checkpoint_hash remains authoritative and no new pull is
    # scheduled. This is the crash boundary for raw checkpoint custody.
    adapter.next_sync_at = None if handoff_status == "pending" else adapter.next_sync_at
    write_audit_log(
        db,
        organization_id=adapter.organization_id,
        user_id=user.id,
        action="EXECUTE_EMAIL_PROVIDER_PULL",
        entity_type="email_adapter_run",
        entity_id=run.id,
        new_values={
            "provider_kind": adapter.provider_kind,
            "status": status,
            "messages_seen": messages_seen,
            "messages_ingested": messages_ingested,
            "checkpoint_present": checkpoint_hash is not None if status == "succeeded" else False,
            "checkpoint_handoff_status": handoff_status,
            "failure_summary": failure_summary,
        },
        details=(
            "Pull-only provider execution. A successful proposed checkpoint remains pending until explicit acknowledgement. "
            "Credential values, provider content and opaque checkpoint values are not persisted in audit metadata."
        ),
    )
    db.commit()
    db.refresh(run)
    return run


def _schedule_failure(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    user: User,
    run: EmailAdapterRun,
) -> None:
    finished_at = run.finished_at or datetime.now(UTC)
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
        },
        details="Bounded content-free retry schedule; no automatic provider execution is performed.",
    )
    db.commit()


def execute_provider_adapter_with_checkpoint_handoff(
    db: Session,
    adapter: EmailProviderAdapter,
    user: User,
    payload: EmailProviderExecutionRequest,
) -> dict:
    existing = _existing_run(db, adapter.id, payload.idempotency_key)
    if existing is not None:
        return {
            "run": existing,
            "next_checkpoint": None,
            "replayed": True,
            "checkpoint_handoff_required": existing.checkpoint_handoff_status == "pending",
        }

    if adapter.organization_id != user.organization_id:
        raise HTTPException(404, "Email provider adapter not found")
    if adapter.provider_kind not in _PULL_KINDS:
        raise HTTPException(409, "This adapter kind has no pull execution authority")

    pending = _pending_checkpoint_run(db, adapter.id)
    if pending is not None:
        raise HTTPException(
            409,
            "A provider checkpoint handoff is pending acknowledgement or abandonment",
        )

    connection = _connection_for_adapter(db, adapter)
    if connection is None:
        raise HTTPException(404, "Email ingestion connection not found")
    if adapter.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both be active")
    if "messages.read.allowed_folder" not in set(adapter.permission_manifest):
        raise HTTPException(409, "Provider execution requires selected-folder message read permission")

    supplied_checkpoint_hash = _hash_checkpoint(payload.provider_checkpoint)
    if adapter.checkpoint_hash:
        if supplied_checkpoint_hash != adapter.checkpoint_hash:
            raise HTTPException(409, "Provider checkpoint does not match the active acknowledged cursor")
    elif payload.provider_checkpoint:
        raise HTTPException(409, "No active provider checkpoint is expected for this adapter")

    try:
        token = _resolve_credential(adapter.credential_reference)
        if adapter.provider_kind == "microsoft_graph":
            messages, next_checkpoint = _fetch_graph_page(
                connection,
                adapter,
                token,
                payload.provider_checkpoint,
            )
        else:
            messages, next_checkpoint = provider_gmail_history.fetch_gmail_provider_page(
                connection,
                adapter,
                token,
                payload.provider_checkpoint,
            )
        if not next_checkpoint:
            raise ProviderExecutionFailure("provider_checkpoint_missing")
    except ProviderExecutionFailure as exc:
        run = _record_run(
            db,
            adapter=adapter,
            user=user,
            payload=payload,
            status="failed",
            messages_seen=0,
            messages_ingested=0,
            next_checkpoint=None,
            failure_summary=exc.code,
        )
        _schedule_failure(db, adapter=adapter, user=user, run=run)
        return {
            "run": run,
            "next_checkpoint": None,
            "replayed": False,
            "checkpoint_handoff_required": False,
        }

    messages_seen = len(messages)
    messages_ingested = 0
    try:
        for message in messages:
            already_exists = db.scalar(
                select(IngestedEmailMessage.id).where(
                    IngestedEmailMessage.connection_id == connection.id,
                    IngestedEmailMessage.provider_message_id == message.provider_message_id,
                )
            )
            _stage_email(db, connection=connection, adapter=adapter, payload=message)
            if already_exists is None:
                messages_ingested += 1
    except HTTPException:
        run = _record_run(
            db,
            adapter=adapter,
            user=user,
            payload=payload,
            status="failed",
            messages_seen=messages_seen,
            messages_ingested=messages_ingested,
            next_checkpoint=None,
            failure_summary="provider_staging_rejected",
        )
        _schedule_failure(db, adapter=adapter, user=user, run=run)
        return {
            "run": run,
            "next_checkpoint": None,
            "replayed": False,
            "checkpoint_handoff_required": False,
        }

    run = _record_run(
        db,
        adapter=adapter,
        user=user,
        payload=payload,
        status="succeeded",
        messages_seen=messages_seen,
        messages_ingested=messages_ingested,
        next_checkpoint=next_checkpoint,
        failure_summary=None,
    )
    return {
        "run": run,
        "next_checkpoint": next_checkpoint,
        "replayed": False,
        "checkpoint_handoff_required": True,
    }


def _get_run_for_adapter(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    run_id: UUID,
    organization_id: UUID,
) -> EmailAdapterRun:
    run = db.scalar(
        select(EmailAdapterRun).where(
            EmailAdapterRun.id == run_id,
            EmailAdapterRun.adapter_id == adapter.id,
            EmailAdapterRun.organization_id == organization_id,
        )
    )
    if run is None:
        raise HTTPException(404, "Provider execution run not found")
    return run


def acknowledge_checkpoint_handoff(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    run_id: UUID,
    user: User,
    payload: CheckpointHandoffAckRequest,
) -> dict:
    if not payload.confirm_ack:
        raise HTTPException(422, "Explicit checkpoint acknowledgement confirmation is required")
    if adapter.organization_id != user.organization_id:
        raise HTTPException(404, "Email provider adapter not found")
    if adapter.provider_kind not in _PULL_KINDS:
        raise HTTPException(409, "This adapter kind has no checkpoint handoff authority")
    connection = _connection_for_adapter(db, adapter)
    if connection is None:
        raise HTTPException(404, "Email ingestion connection not found")
    if adapter.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both be active")

    run = _get_run_for_adapter(
        db,
        adapter=adapter,
        run_id=run_id,
        organization_id=user.organization_id,
    )
    pending = _pending_checkpoint_run(db, adapter.id)
    if pending is None or pending.id != run.id:
        raise HTTPException(409, "This run is not the current pending checkpoint handoff")
    if run.status != "succeeded" or run.checkpoint_handoff_status != "pending" or not run.checkpoint_hash:
        raise HTTPException(409, "This run does not have an acknowledgeable checkpoint handoff")
    if _hash_checkpoint(payload.provider_checkpoint) != run.checkpoint_hash:
        raise HTTPException(409, "Supplied checkpoint does not match the pending provider handoff")

    now = datetime.now(UTC)
    adapter.checkpoint_hash = run.checkpoint_hash
    adapter.next_sync_at = now + timedelta(minutes=_NORMAL_INTERVAL_MINUTES)
    run.checkpoint_handoff_status = "acknowledged"
    run.checkpoint_acknowledged_at = now
    write_audit_log(
        db,
        organization_id=adapter.organization_id,
        user_id=user.id,
        action="ACKNOWLEDGE_EMAIL_PROVIDER_CHECKPOINT",
        entity_type="email_adapter_run",
        entity_id=run.id,
        new_values={
            "provider_kind": adapter.provider_kind,
            "checkpoint_handoff_status": "acknowledged",
            "checkpoint_committed": True,
        },
        details=(
            "Operator acknowledged external custody of the exact proposed provider checkpoint. "
            "Raw checkpoint values, hashes, credentials and provider content are excluded from audit metadata."
        ),
    )
    db.commit()
    db.refresh(run)
    return {
        "adapter_id": adapter.id,
        "run_id": run.id,
        "checkpoint_handoff_status": run.checkpoint_handoff_status,
        "checkpoint_committed": True,
        "next_sync_at": adapter.next_sync_at,
    }


def abandon_checkpoint_handoff(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    run_id: UUID,
    user: User,
    payload: CheckpointHandoffAbandonRequest,
) -> dict:
    if not payload.confirm_abandon:
        raise HTTPException(422, "Explicit checkpoint handoff abandonment confirmation is required")
    reason = payload.reason.strip()
    if len(reason) < 20:
        raise HTTPException(422, "Checkpoint abandonment reason must contain at least 20 characters")
    if adapter.organization_id != user.organization_id:
        raise HTTPException(404, "Email provider adapter not found")
    if adapter.provider_kind not in _PULL_KINDS:
        raise HTTPException(409, "This adapter kind has no checkpoint handoff authority")

    run = _get_run_for_adapter(
        db,
        adapter=adapter,
        run_id=run_id,
        organization_id=user.organization_id,
    )
    pending = _pending_checkpoint_run(db, adapter.id)
    if pending is None or pending.id != run.id:
        raise HTTPException(409, "This run is not the current pending checkpoint handoff")
    if run.status != "succeeded" or run.checkpoint_handoff_status != "pending":
        raise HTTPException(409, "This run does not have an abandonable checkpoint handoff")

    now = datetime.now(UTC)
    run.checkpoint_handoff_status = "abandoned"
    run.checkpoint_abandoned_at = now
    connection = _connection_for_adapter(db, adapter)
    active_source = (
        adapter.status == "active"
        and connection is not None
        and connection.status == EmailConnectionStatus.ACTIVE
    )
    adapter.next_sync_at = now if active_source else None
    # Deliberately leave adapter.checkpoint_hash unchanged. Re-execution resumes
    # from the previously acknowledged cursor, or from bootstrap when it is null.
    write_audit_log(
        db,
        organization_id=adapter.organization_id,
        user_id=user.id,
        action="ABANDON_EMAIL_PROVIDER_CHECKPOINT_HANDOFF",
        entity_type="email_adapter_run",
        entity_id=run.id,
        new_values={
            "provider_kind": adapter.provider_kind,
            "checkpoint_handoff_status": "abandoned",
            "previous_cursor_preserved": True,
            "operator_reason_supplied": True,
        },
        details=(
            "Operator abandoned a pending checkpoint handoff so execution can safely resume from the previous acknowledged cursor. "
            "The supplied reason text, raw checkpoints, hashes, credentials and provider content are not persisted in audit metadata."
        ),
    )
    db.commit()
    db.refresh(run)
    return {
        "adapter_id": adapter.id,
        "run_id": run.id,
        "checkpoint_handoff_status": run.checkpoint_handoff_status,
        "previous_cursor_preserved": True,
        "next_sync_at": adapter.next_sync_at,
    }


def list_provider_reconciliation_with_handoff(db: Session, user: User) -> dict:
    result = list_provider_reconciliation_with_checkpoint_controls(db, user)
    for item in result["items"]:
        adapter = db.get(EmailProviderAdapter, UUID(item["adapter_id"]))
        if adapter is None or adapter.organization_id != user.organization_id:
            continue
        pending = _pending_checkpoint_run(db, adapter.id)
        connection = _connection_for_adapter(db, adapter)
        active_source = (
            adapter.status == "active"
            and connection is not None
            and connection.status == EmailConnectionStatus.ACTIVE
        )
        item["checkpoint_handoff_required"] = pending is not None
        item["pending_checkpoint_run_id"] = str(pending.id) if pending else None
        item["checkpoint_ack_available"] = bool(pending and active_source)
        item["checkpoint_abandon_available"] = pending is not None
        if pending is not None:
            item["operational_state"] = "checkpoint_handoff_pending"
    return result


def reset_gmail_checkpoint_with_handoff_guard(
    db: Session,
    adapter: EmailProviderAdapter,
    user: User,
    payload: GmailCheckpointResetRequest,
) -> dict:
    if _pending_checkpoint_run(db, adapter.id) is not None:
        raise HTTPException(
            409,
            "Pending checkpoint handoff must be acknowledged or abandoned before Gmail cursor reset",
        )
    return reset_gmail_checkpoint(db, adapter, user, payload)
