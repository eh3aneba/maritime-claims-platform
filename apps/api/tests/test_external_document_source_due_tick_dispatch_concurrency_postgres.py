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

from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
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
from tests.db_harness import reset_database
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_family_version_admission import _bound_v1

pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_DUE_TICK_DISPATCH_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase AD concurrency regressions run only in the dedicated PostgreSQL CI job",
)

_SCHEDULE_REASON = (
    "Authorize a bounded recurring schedule for PostgreSQL scheduler-dispatch "
    "concurrency validation without granting downstream provider authority."
)
_DISABLE_REASON = (
    "Disable this recurring schedule during scheduler-dispatch concurrency "
    "validation so future internal dispatches fail closed."
)


def setup_function() -> None:
    _phase_y_setup()
    reset_database()


def teardown_function() -> None:
    _phase_y_teardown()


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


def _seed_due_schedule(monkeypatch: pytest.MonkeyPatch, suffix: str):
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        suffix,
    )
    engine, SessionLocal = _session_factory()
    due_now = datetime.now(UTC)
    with SessionLocal() as db:
        family = db.get(
            ExternalDocumentSourceEvidenceFamilyBinding,
            UUID(binding["id"]),
        )
        assert family is not None
        schedule, _ = authorize_recurring_observation_schedule(
            db,
            organization_id=family.organization_id,
            profile_id=UUID(profile_id),
            binding_id=UUID(binding["id"]),
            authorized_by_id=actor_id,
            request_key=f"phase-ad-pg-schedule-{suffix}",
            reason=_SCHEDULE_REASON,
            cadence_class="hourly",
            effective_at=due_now,
        )
        return engine, SessionLocal, due_now, schedule.id


def test_two_scheduler_workers_dispatch_same_due_tick_at_most_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, SessionLocal, due_now, schedule_id = _seed_due_schedule(
        monkeypatch,
        "same-tick",
    )
    barrier = Barrier(2)
    try:
        def dispatch(label: str):
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    row = dispatch_next_due_tick(
                        db,
                        worker_id=f"phase-ad-worker-{label}",
                        now=due_now,
                    )
                    return row.id if row is not None else None
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(dispatch, ("a", "b")))

        assert sum(value is not None for value in results) == 1
        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(ExternalDocumentSourceDueTickDispatch).where(
                        ExternalDocumentSourceDueTickDispatch.schedule_id == schedule_id
                    )
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].due_at == due_now
    finally:
        engine.dispose()


def test_disable_vs_dispatch_serializes_on_active_schedule_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "disable-race",
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
                request_key="phase-ad-pg-disable-schedule",
                reason=_SCHEDULE_REASON,
                cadence_class="hourly",
                effective_at=due_now,
            )
            schedule_id = schedule.id

        barrier = Barrier(2)

        def dispatch():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    row = dispatch_next_due_tick(
                        db,
                        worker_id="phase-ad-worker-dispatch",
                        now=due_now,
                    )
                    return ("dispatch", "ok" if row is not None else "none")
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("dispatch", "conflict")

        def disable():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    disable_recurring_observation_schedule(
                        db,
                        organization_id=organization_id,
                        profile_id=UUID(profile_id),
                        schedule_id=schedule_id,
                        actor_id=actor_id,
                        request_key="phase-ad-pg-disable",
                        reason=_DISABLE_REASON,
                    )
                    return ("disable", "ok")
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("disable", "conflict")

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(dispatch)
            b = pool.submit(disable)
            results = [a.result(), b.result()]

        disable_result = next(row for row in results if row[0] == "disable")
        assert disable_result[1] == "ok"

        with SessionLocal() as db:
            schedule = db.get(
                ExternalDocumentSourceRecurringObservationSchedule,
                schedule_id,
            )
            assert schedule is not None
            assert schedule.status == "disabled"
            dispatches = list(
                db.scalars(
                    select(ExternalDocumentSourceDueTickDispatch).where(
                        ExternalDocumentSourceDueTickDispatch.schedule_id == schedule_id
                    )
                ).all()
            )
            assert len(dispatches) <= 1
            if dispatches:
                assert dispatches[0].due_at == due_now
    finally:
        engine.dispose()
