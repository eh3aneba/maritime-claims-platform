from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    execute_due_tick_observation,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
)
from app.modules.external_document_sources.recurring_observation_schedule_service import (
    authorize_recurring_observation_schedule,
    disable_recurring_observation_schedule,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_family_version_admission import _bound_v1
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "PostgreSQL due-tick observation concurrency regressions run only in "
        "the dedicated PostgreSQL CI job"
    ),
)

_SCHEDULE_REASON = (
    "Authorize this bounded recurring metadata-only schedule for PostgreSQL "
    "due-tick observation concurrency validation."
)
_EXEC_REASON = (
    "Consume exactly one deterministic due tick during PostgreSQL concurrency "
    "validation without downstream content or Evidence side effects."
)
_DISABLE_REASON = (
    "Disable the recurring schedule during PostgreSQL due-tick concurrency "
    "validation and prevent future observations."
)


def _session_factory():
    engine = create_engine(
        os.environ["DATABASE_URL"],
        future=True,
        pool_pre_ping=True,
    )
    return engine, sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        class_=Session,
    )


def test_same_due_tick_concurrent_consumers_create_one_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ac-pg-same-tick",
    )
    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(
        found=True,
        item=_baseline_projection(),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        adapter,
    )

    engine, SessionLocal = _session_factory()
    due_now = datetime.now(UTC)
    try:
        with SessionLocal() as db:
            family = db.get(
                ExternalDocumentSourceEvidenceFamilyBinding,
                UUID(binding["id"]),
            )
            assert family is not None
            organization_id = family.organization_id
            schedule, _ = authorize_recurring_observation_schedule(
                db,
                organization_id=organization_id,
                profile_id=UUID(profile_id),
                binding_id=UUID(binding["id"]),
                authorized_by_id=actor_id,
                request_key="phase-ac-pg-schedule",
                reason=_SCHEDULE_REASON,
                cadence_class="hourly",
                effective_at=due_now,
            )
            schedule_id = schedule.id

        barrier = Barrier(2)

        def consume(label: str):
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    row, _ = execute_due_tick_observation(
                        db,
                        organization_id=organization_id,
                        profile_id=UUID(profile_id),
                        schedule_id=schedule_id,
                        executed_by_id=actor_id,
                        request_key=f"phase-ac-pg-consume-{label}",
                        reason=_EXEC_REASON,
                        now=due_now,
                    )
                    return ("ok", row.id)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("conflict", None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, ("a", "b")))

        assert sorted(result[0] for result in results) == ["conflict", "ok"]
        assert adapter.calls == 1

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(ExternalDocumentSourceDueTickObservationExecution).where(
                        ExternalDocumentSourceDueTickObservationExecution.schedule_id
                        == schedule_id
                    )
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].due_at == due_now
            assert rows[0].result_status == "unchanged"
    finally:
        engine.dispose()


def test_disable_vs_consume_is_serialized_and_never_observes_after_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ac-pg-disable-race",
    )
    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(
        found=True,
        item=_baseline_projection(),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        adapter,
    )

    engine, SessionLocal = _session_factory()
    due_now = datetime.now(UTC)
    try:
        with SessionLocal() as db:
            family = db.get(
                ExternalDocumentSourceEvidenceFamilyBinding,
                UUID(binding["id"]),
            )
            assert family is not None
            organization_id = family.organization_id
            schedule, _ = authorize_recurring_observation_schedule(
                db,
                organization_id=organization_id,
                profile_id=UUID(profile_id),
                binding_id=UUID(binding["id"]),
                authorized_by_id=actor_id,
                request_key="phase-ac-pg-disable-schedule",
                reason=_SCHEDULE_REASON,
                cadence_class="hourly",
                effective_at=due_now,
            )
            schedule_id = schedule.id

        barrier = Barrier(2)

        def consume():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    row, _ = execute_due_tick_observation(
                        db,
                        organization_id=organization_id,
                        profile_id=UUID(profile_id),
                        schedule_id=schedule_id,
                        executed_by_id=actor_id,
                        request_key="phase-ac-pg-disable-consume",
                        reason=_EXEC_REASON,
                        now=due_now,
                    )
                    return ("consume", "ok", row.id)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("consume", "conflict", None)

        def disable():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    row, _ = disable_recurring_observation_schedule(
                        db,
                        organization_id=organization_id,
                        profile_id=UUID(profile_id),
                        schedule_id=schedule_id,
                        actor_id=actor_id,
                        request_key="phase-ac-pg-disable",
                        reason=_DISABLE_REASON,
                    )
                    return ("disable", "ok", row.id)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("disable", "conflict", None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(consume)
            b = pool.submit(disable)
            results = [a.result(), b.result()]

        disable_result = next(row for row in results if row[0] == "disable")
        consume_result = next(row for row in results if row[0] == "consume")
        assert disable_result[1] == "ok"
        assert consume_result[1] in {"ok", "conflict"}

        with SessionLocal() as db:
            schedule = db.get(
                ExternalDocumentSourceRecurringObservationSchedule,
                schedule_id,
            )
            assert schedule is not None
            assert schedule.status == "disabled"
            executions = list(
                db.scalars(
                    select(ExternalDocumentSourceDueTickObservationExecution).where(
                        ExternalDocumentSourceDueTickObservationExecution.schedule_id
                        == schedule_id
                    )
                ).all()
            )
            assert len(executions) <= 1
            if executions:
                assert executions[0].due_at == due_now
                assert adapter.calls == 1
            else:
                assert adapter.calls == 0
    finally:
        engine.dispose()
