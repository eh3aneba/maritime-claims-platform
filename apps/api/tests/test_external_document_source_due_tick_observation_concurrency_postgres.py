from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from time import perf_counter
import os
from threading import Barrier, local
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources import due_tick_observation_service
from app.modules.external_document_sources import recurring_observation_provider_lineage
from app.modules.external_document_sources import evidence_admission_execution_service
from app.modules.external_document_sources import generation_3_change_detection_service
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
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_family_version_admission import _bound_v1
from tests.ci_due_tick_stage_timing import ci_due_tick_sql_aggregate, ci_due_tick_stage
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


def setup_function() -> None:
    _phase_y_setup()


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


def test_same_due_tick_concurrent_consumers_create_one_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with ci_due_tick_stage("same_tick_seed"):
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
        with ci_due_tick_stage("same_tick_schedule"):
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
        trace_worker = local()
        # Engine-level SQLAlchemy hooks attribute only DBAPI execute duration
        # and count to the active, fixed-label synthetic test worker stages.
        # Never inspect/store SQL, bind parameters, DB IDs or cursor results.
        def on_sql_before(_connection, _cursor, _statement, _parameters, context, _many):
            context._mcri_due_tick_sql_started = perf_counter()

        def on_sql_after(_connection, _cursor, _statement, _parameters, context, _many):
            started = getattr(context, "_mcri_due_tick_sql_started", None)
            if started is None:
                return
            duration = max(0.0, perf_counter() - started)
            # Inclusive counts for nested integrity sub-stages; every active
            # frame observes the same executed DBAPI statement.
            for frame in getattr(trace_worker, "sql_frames", ()):
                frame["count"] += 1
                frame["seconds"] += duration

        event.listen(engine, "before_cursor_execute", on_sql_before)
        event.listen(engine, "after_cursor_execute", on_sql_after)

        sql_phases = {
            "legacy_resolution", "legacy_admission_integrity",
            "legacy_generation3_integrity", "legacy_checkpoint",
            "legacy_generation3_lineage",
            "nested_authorization_integrity",
            "nested_checkpoint_integrity",
            "nested_restaging_integrity",
            "nested_change_integrity",
            "nested_profile_integrity",
        }

        def trace_phase(operation, phase: str):
            # Original production service functions remain unmodified.
            # These wrappers run only in this synthetic PG regression and
            # bind fixed stage labels to the calling test worker thread.
            def recorded(*args, **kwargs):
                worker = getattr(trace_worker, "label", None)
                if worker is None:
                    return operation(*args, **kwargs)
                fixed_stage = f"same_tick_{worker}_{phase}"
                if phase not in sql_phases:
                    with ci_due_tick_stage(fixed_stage):
                        return operation(*args, **kwargs)
                frame = {"count": 0, "seconds": 0.0}
                if not hasattr(trace_worker, "sql_frames"):
                    trace_worker.sql_frames = []
                trace_worker.sql_frames.append(frame)
                try:
                    with ci_due_tick_stage(fixed_stage):
                        return operation(*args, **kwargs)
                finally:
                    popped = trace_worker.sql_frames.pop()
                    assert popped is frame
                    ci_due_tick_sql_aggregate(
                        fixed_stage, frame["count"], float(frame["seconds"]),
                    )
            return recorded

        for name, phase in (
            ("_schedule_binding_for_update", "binding_lock"),
            ("_schedule_for_update", "schedule_verify"),
            ("_lock_current_family_document", "current_document"),
            ("_prior_source_state", "source_state"),
            ("resolve_recurring_provider_lineage", "provider_lineage"),
            ("read_recurring_provider_metadata", "provider_metadata"),
            ("ensure_due_tick_observation_integrity", "integrity"),
            ("write_audit_log", "audit_write"),
        ):
            original = getattr(due_tick_observation_service, name)
            monkeypatch.setattr(
                due_tick_observation_service, name,
                trace_phase(original, phase),
            )

        # Measure the specific security-validation subcalls within the
        # provider-lineage resolver, not just the outer 12-second interval.
        # Wrappers delegate to the ORIGINAL functions and only log fixed
        # test-owned stage labels for the two synthetic PostgreSQL workers.
        for name, phase in (
            ("_resolve_legacy", "legacy_resolution"),
            ("_ensure_legacy_admission_integrity", "legacy_admission_integrity"),
            ("_ensure_legacy_generation3_integrity", "legacy_generation3_integrity"),
            ("_checkpoint_generation_3", "legacy_checkpoint"),
            ("_legacy_generation3_lineage", "legacy_generation3_lineage"),
        ):
            original = getattr(recurring_observation_provider_lineage, name)
            monkeypatch.setattr(
                recurring_observation_provider_lineage, name,
                trace_phase(original, phase),
            )

        # Profile deeper internal validation boundaries, keeping the same
        # unmodified code, arguments and race behavior. These names are fixed
        # and private; per-stage DBAPI totals include nested SQL calls.
        for module, name, phase in (
            (
                evidence_admission_execution_service,
                "_ensure_authorization_integrity",
                "nested_authorization_integrity",
            ),
            (
                generation_3_change_detection_service,
                "_ensure_checkpoint_generation_3_integrity",
                "nested_checkpoint_integrity",
            ),
            (
                generation_3_change_detection_service,
                "_ensure_successor_versioned_restaging_integrity",
                "nested_restaging_integrity",
            ),
            (
                generation_3_change_detection_service,
                "_ensure_successor_change_detection_integrity",
                "nested_change_integrity",
            ),
            (
                generation_3_change_detection_service,
                "_ensure_profile_integrity",
                "nested_profile_integrity",
            ),
        ):
            original = getattr(module, name)
            monkeypatch.setattr(module, name, trace_phase(original, phase))

        def consume(label: str):
            assert label in {"a", "b"}
            # Record each worker session and the service's binding lock and
            # metadata stages without SQL, source payloads, or session IDs.
            trace_worker.label = label
            try:
                with ci_due_tick_stage(f"same_tick_{label}_session"):
                    with SessionLocal() as db:
                        # Capture the actual final transaction commit and
                        # refresh, rather than inferring their durations from
                        # application stages. The session remains test-local.
                        db.commit = trace_phase(db.commit, "commit")
                        db.refresh = trace_phase(db.refresh, "refresh")
                        with ci_due_tick_stage(f"same_tick_{label}_barrier"):
                            barrier.wait(timeout=10)
                        with ci_due_tick_stage(f"same_tick_{label}_execute"):
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
            finally:
                del trace_worker.label

        with ci_due_tick_stage("same_tick_workers"):
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
    with ci_due_tick_stage("disable_race_seed"):
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
        with ci_due_tick_stage("disable_race_schedule"):
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
            with ci_due_tick_stage("disable_race_consume_session"):
                with SessionLocal() as db:
                    with ci_due_tick_stage("disable_race_consume_barrier"):
                        barrier.wait(timeout=10)
                    with ci_due_tick_stage("disable_race_consume_execute"):
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
            with ci_due_tick_stage("disable_race_disable_session"):
                with SessionLocal() as db:
                    with ci_due_tick_stage("disable_race_disable_barrier"):
                        barrier.wait(timeout=10)
                    with ci_due_tick_stage("disable_race_disable_execute"):
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

        with ci_due_tick_stage("disable_race_workers"):
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
