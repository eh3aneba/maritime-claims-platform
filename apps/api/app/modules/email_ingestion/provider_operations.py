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
from app.modules.email_ingestion.provider_execution import execute_provider_adapter
from app.modules.email_ingestion.schemas import (
    EmailAdapterCreate,
    EmailAdapterRunCreate,
    EmailProviderExecutionRequest,
)
from app.modules.email_ingestion.service import (
    create_adapter,
    get_connection,
    transition_adapter,
)
from app.modules.users.models import User

_PULL_KINDS = {"microsoft_graph", "gmail_api"}
_NORMAL_INTERVAL_MINUTES = 15
_MAX_BACKOFF_MINUTES = 120
_RECONCILIATION_FAILURE_THRESHOLD = 4


def _is_pull_adapter(item: EmailProviderAdapter) -> bool:
    return item.provider_kind in _PULL_KINDS


def create_governed_adapter(db: Session, user: User, payload: EmailAdapterCreate) -> EmailProviderAdapter:
    item = create_adapter(db, user, payload)
    if not _is_pull_adapter(item):
        item.next_sync_at = None
        db.commit()
        db.refresh(item)
    return item


def transition_governed_adapter(
    db: Session,
    item: EmailProviderAdapter,
    user: User,
    action: str,
    note: str,
) -> EmailProviderAdapter:
    item = transition_adapter(db, item, user, action, note)
    if item.status in {"suspended", "revoked"}:
        item.next_sync_at = None
    elif item.status == "active":
        item.next_sync_at = datetime.now(UTC) if _is_pull_adapter(item) else None
    db.commit()
    db.refresh(item)
    return item


def record_governed_adapter_run(
    db: Session,
    item: EmailProviderAdapter,
    user: User,
    payload: EmailAdapterRunCreate,
) -> EmailAdapterRun:
    if _is_pull_adapter(item):
        raise HTTPException(
            409,
            "Graph/Gmail execution state may only be recorded by the governed provider execution endpoint",
        )
    if item.provider_kind != "provider_webhook":
        raise HTTPException(409, "This adapter kind has no external run-recording authority")
    connection = get_connection(db, user.organization_id, item.connection_id)
    if item.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both be active")
    if payload.provider_checkpoint:
        raise HTTPException(422, "Provider webhook runs cannot supply pull checkpoints")
    if payload.messages_seen > item.batch_limit or payload.messages_ingested > payload.messages_seen:
        raise HTTPException(422, "Run counts exceed the bounded adapter batch")

    existing = db.scalar(
        select(EmailAdapterRun).where(
            EmailAdapterRun.adapter_id == item.id,
            EmailAdapterRun.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing

    now = datetime.now(UTC)
    failure_summary = "provider_webhook_reported_failure" if payload.failure_summary else None
    run = EmailAdapterRun(
        organization_id=item.organization_id,
        adapter_id=item.id,
        initiated_by_id=user.id,
        idempotency_key=payload.idempotency_key,
        trigger=payload.trigger,
        status="failed" if failure_summary else "succeeded",
        messages_seen=payload.messages_seen,
        messages_ingested=payload.messages_ingested,
        checkpoint_hash=None,
        failure_summary=failure_summary,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    item.last_sync_at = now
    item.next_sync_at = None
    write_audit_log(
        db,
        organization_id=item.organization_id,
        user_id=user.id,
        action="RECORD_PROVIDER_WEBHOOK_RUN",
        entity_type="email_adapter_run",
        entity_id=run.id,
        new_values={
            "status": run.status,
            "messages_seen": run.messages_seen,
            "messages_ingested": run.messages_ingested,
            "trigger": run.trigger,
        },
        details=(
            "Content-free webhook operations metadata only. This path has no pull checkpoint or scheduling authority."
        ),
    )
    db.commit()
    db.refresh(run)
    return run


def _consecutive_failures(db: Session, adapter_id: UUID, *, limit: int = 8) -> int:
    runs = list(
        db.scalars(
            select(EmailAdapterRun)
            .where(EmailAdapterRun.adapter_id == adapter_id)
            .order_by(EmailAdapterRun.started_at.desc())
            .limit(limit)
        )
    )
    count = 0
    for run in runs:
        if run.status != "failed":
            break
        count += 1
    return count


def execute_governed_provider_adapter(
    db: Session,
    adapter: EmailProviderAdapter,
    user: User,
    payload: EmailProviderExecutionRequest,
) -> dict:
    result = execute_provider_adapter(db, adapter, user, payload)
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
            },
            details="Bounded content-free retry schedule; no automatic provider execution is performed.",
        )
    else:
        adapter.next_sync_at = finished_at + timedelta(minutes=_NORMAL_INTERVAL_MINUTES)
    db.commit()
    return result


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


def list_provider_reconciliation(db: Session, user: User) -> dict:
    now = datetime.now(UTC)
    adapters = list(
        db.scalars(
            select(EmailProviderAdapter)
            .where(
                EmailProviderAdapter.organization_id == user.organization_id,
                EmailProviderAdapter.provider_kind.in_(_PULL_KINDS),
            )
            .order_by(EmailProviderAdapter.created_at.asc())
        )
    )
    items: list[dict] = []
    for adapter in adapters:
        connection = _connection_for_adapter(db, adapter)
        last_run = db.scalar(
            select(EmailAdapterRun)
            .where(EmailAdapterRun.adapter_id == adapter.id)
            .order_by(EmailAdapterRun.started_at.desc())
            .limit(1)
        )
        failure_streak = _consecutive_failures(db, adapter.id)
        connection_status = connection.status.value if connection is not None else "missing"

        if adapter.status == "revoked":
            operational_state = "revoked"
        elif adapter.status == "suspended":
            operational_state = "suspended"
        elif connection is None or connection.status != EmailConnectionStatus.ACTIVE:
            operational_state = "blocked_connection"
        elif failure_streak >= _RECONCILIATION_FAILURE_THRESHOLD or adapter.next_sync_at is None:
            operational_state = "reconciliation_required"
        elif adapter.next_sync_at <= now:
            operational_state = "due"
        else:
            operational_state = "waiting"

        items.append(
            {
                "adapter_id": str(adapter.id),
                "provider_kind": adapter.provider_kind,
                "adapter_status": adapter.status,
                "connection_status": connection_status,
                "operational_state": operational_state,
                "last_sync_at": adapter.last_sync_at,
                "next_sync_at": adapter.next_sync_at,
                "last_run_status": last_run.status if last_run else None,
                "consecutive_failures": failure_streak,
                "checkpoint_handoff_required": bool(adapter.checkpoint_hash),
                "operator_driven_execution": True,
            }
        )

    return {
        "generated_at": now,
        "execution_mode": "operator_or_external_orchestrator",
        "items": items,
    }
