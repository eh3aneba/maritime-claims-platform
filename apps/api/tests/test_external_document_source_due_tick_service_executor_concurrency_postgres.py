from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
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
from app.modules.external_document_sources.family_version_admission_service import (
    _binding_for_update as _aa_binding_for_update,
    _establish_next_document_version,
    _lock_current_family_document as _aa_lock_current_family_document,
)
from app.modules.external_document_sources.recurring_observation_schedule_service import (
    _binding_for_update as _schedule_binding_for_update,
    authorize_recurring_observation_schedule,
    disable_recurring_observation_schedule,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.db_harness import reset_database
from tests.test_external_document_source_change_detection import _ChangeAdapter
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_family_version_admission import _bound_v1
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_DUE_TICK_SERVICE_EXECUTOR_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase AE concurrency regressions run only in the dedicated PostgreSQL CI job",
)

_SCHEDULE_REASON = (
    "Authorize one recurring exact-item observation schedule for Phase AE "
    "PostgreSQL service-executor concurrency validation."
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


def _seed_dispatch(monkeypatch: pytest.MonkeyPatch, suffix: str):
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        suffix,
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
            request_key=f"phase-ae-pg-schedule-{suffix}",
            reason=_SCHEDULE_REASON,
            cadence_class="hourly",
            effective_at=due_now,
        )
        schedule_id = schedule.id

    with SessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id=f"phase-ae-pg-scheduler-{suffix}",
            now=due_now,
        )
        assert dispatch is not None
        dispatch_id = dispatch.id

    return (
        engine,
        SessionLocal,
        due_now,
        actor_id,
        UUID(profile_id),
        organization_id,
        schedule_id,
        dispatch_id,
        adapter,
    )


def test_two_service_workers_consume_one_dispatch_with_one_provider_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        engine,
        SessionLocal,
        due_now,
        _actor_id,
        _profile_id,
        _organization_id,
        _schedule_id,
        dispatch_id,
        adapter,
    ) = _seed_dispatch(monkeypatch, "two-service")
    barrier = Barrier(2)
    try:
        def consume(label: str):
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    observation, consumption, outcome = consume_due_tick_dispatch(
                        db,
                        dispatch_id=dispatch_id,
                        service_executor_id="external-evidence-observer-v1",
                        now=due_now,
                    )
                    return observation.id, consumption.id, outcome
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, ("a", "b")))

        successful = [row for row in results if row is not None]
        assert successful
        with SessionLocal() as db:
            observations = list(
                db.scalars(select(ExternalDocumentSourceDueTickObservationExecution)).all()
            )
            consumptions = list(
                db.scalars(select(ExternalDocumentSourceDueTickDispatchConsumption)).all()
            )
            assert len(observations) == 1
            assert len(consumptions) == 1
            assert consumptions[0].dispatch_id == dispatch_id
            assert consumptions[0].observation_execution_id == observations[0].id
            assert observations[0].actor_kind == "service"
            assert observations[0].executed_by_id is None

        assert adapter.calls == 1
    finally:
        engine.dispose()


def test_human_ac_vs_service_ae_same_tick_yields_one_observation_and_one_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        engine,
        SessionLocal,
        due_now,
        actor_id,
        profile_id,
        organization_id,
        schedule_id,
        dispatch_id,
        adapter,
    ) = _seed_dispatch(monkeypatch, "human-service")
    barrier = Barrier(2)
    try:
        def human_execute():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    observation, outcome = execute_due_tick_observation(
                        db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        schedule_id=schedule_id,
                        executed_by_id=actor_id,
                        request_key="phase-ae-pg-human-race",
                        reason=(
                            "Race the existing human AC due-tick execution against "
                            "the internal Phase AE service executor."
                        ),
                        now=due_now,
                    )
                    return ("human", observation.id, outcome)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("human", None, "conflict")

        def service_consume():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    observation, consumption, outcome = consume_due_tick_dispatch(
                        db,
                        dispatch_id=dispatch_id,
                        service_executor_id="external-evidence-observer-v1",
                        now=due_now,
                    )
                    return ("service", observation.id, consumption.id, outcome)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("service", None, None, "conflict")

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(human_execute)
            b = pool.submit(service_consume)
            results = [a.result(timeout=30), b.result(timeout=30)]

        with SessionLocal() as db:
            observations = list(
                db.scalars(
                    select(ExternalDocumentSourceDueTickObservationExecution).where(
                        ExternalDocumentSourceDueTickObservationExecution.schedule_id
                        == schedule_id
                    )
                ).all()
            )
            consumptions = list(
                db.scalars(select(ExternalDocumentSourceDueTickDispatchConsumption)).all()
            )
            dispatches = list(
                db.scalars(
                    select(ExternalDocumentSourceDueTickDispatch).where(
                        ExternalDocumentSourceDueTickDispatch.id == dispatch_id
                    )
                ).all()
            )
            assert len(dispatches) == 1
            assert len(observations) == 1
            assert len(consumptions) == 1
            assert consumptions[0].observation_execution_id == observations[0].id
            assert observations[0].actor_kind in {"human", "service"}

        service_result = next(row for row in results if row[0] == "service")
        assert service_result[1] is not None
        assert adapter.calls == 1
    finally:
        engine.dispose()


def test_disable_vs_service_consumption_serializes_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        engine,
        SessionLocal,
        due_now,
        actor_id,
        profile_id,
        organization_id,
        schedule_id,
        dispatch_id,
        adapter,
    ) = _seed_dispatch(monkeypatch, "disable-service")
    try:
        with SessionLocal() as disable_db:
            schedule = disable_db.get(
                ExternalDocumentSourceRecurringObservationSchedule,
                schedule_id,
            )
            assert schedule is not None
            _schedule_binding_for_update(
                disable_db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=schedule.binding_id,
            )

            # While disable authority owns the shared family lock, AE must not
            # pass the authority boundary or perform a provider metadata read.
            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    consume_due_tick_dispatch(
                        blocked_db,
                        dispatch_id=dispatch_id,
                        service_executor_id="external-evidence-observer-v1",
                        now=due_now,
                    )
                blocked_db.rollback()
            assert adapter.calls == 0

            disabled, outcome = disable_recurring_observation_schedule(
                disable_db,
                organization_id=organization_id,
                profile_id=profile_id,
                schedule_id=schedule_id,
                actor_id=actor_id,
                request_key="phase-ae-pg-disable-service",
                reason=(
                    "Disable the recurring schedule while validating that the "
                    "Phase AE service executor serializes on family authority."
                ),
            )
            assert outcome == "disabled"
            assert disabled.status == "disabled"

        # Once disabled, the immutable prior dispatch is stale authority and
        # must fail closed without reading provider metadata.
        with SessionLocal() as db:
            with pytest.raises(ExternalDocumentSourceConflictError):
                consume_due_tick_dispatch(
                    db,
                    dispatch_id=dispatch_id,
                    service_executor_id="external-evidence-observer-v1",
                    now=due_now,
                )
            db.rollback()

        with SessionLocal() as db:
            assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 0
            assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 0
            assert db.get(ExternalDocumentSourceDueTickDispatch, dispatch_id) is not None

        assert adapter.calls == 0
    finally:
        engine.dispose()

def test_canonical_version_transition_makes_prior_dispatch_fail_closed_without_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, initial_execution, binding = _bound_v1(
        monkeypatch,
        "version-consume",
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
                request_key="phase-ae-pg-version-consume-schedule",
                reason=_SCHEDULE_REASON,
                cadence_class="hourly",
                effective_at=due_now,
            )
            schedule_id = schedule.id

        with SessionLocal() as db:
            dispatch = dispatch_next_due_tick(
                db,
                worker_id="phase-ae-version-consume-scheduler",
                now=due_now,
            )
            assert dispatch is not None
            dispatch_id = dispatch.id
            assert dispatch.current_document_id == UUID(initial_execution["document_id"])

        with SessionLocal() as transition_db:
            family = _aa_binding_for_update(
                transition_db,
                organization_id=organization_id,
                profile_id=UUID(profile_id),
                binding_id=UUID(binding["id"]),
            )
            current = _aa_lock_current_family_document(
                transition_db,
                organization_id=organization_id,
                claim_id=family.claim_id,
                document_family_id=family.document_family_id,
                expected_current_document_id=UUID(initial_execution["document_id"]),
            )

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    consume_due_tick_dispatch(
                        blocked_db,
                        dispatch_id=dispatch_id,
                        service_executor_id="external-evidence-observer-v1",
                        now=due_now,
                    )
                blocked_db.rollback()

            new_document = _establish_next_document_version(
                transition_db,
                prior_document=current,
                executed_by_id=actor_id,
                executed_at=due_now,
                new_document_id=uuid4(),
                original_filename="phase-ae-version-2.pdf",
                mime_type="application/pdf",
                file_size_bytes=4096,
                file_hash="c" * 64,
                storage_key=f"phase-ae-version-consume/{uuid4()}.pdf",
                malware_scanned_at=due_now,
                replacement_reason=(
                    "Advance the canonical Document while the prior AD dispatch "
                    "remains immutable so AE must reject the stale snapshot."
                ),
            )
            new_document_id = new_document.id
            transition_db.commit()

        with SessionLocal() as db:
            with pytest.raises(ExternalDocumentSourceConflictError):
                consume_due_tick_dispatch(
                    db,
                    dispatch_id=dispatch_id,
                    service_executor_id="external-evidence-observer-v1",
                    now=due_now,
                )
            db.rollback()

        with SessionLocal() as db:
            current = db.scalar(
                select(Document).where(
                    Document.organization_id == organization_id,
                    Document.document_family_id == UUID(binding["document_family_id"]),
                    Document.is_current.is_(True),
                    Document.deleted_at.is_(None),
                )
            )
            assert current is not None
            assert current.id == new_document_id
            assert current.version_number == 2
            assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 0
            assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 0
            assert db.get(ExternalDocumentSourceDueTickDispatch, dispatch_id) is not None

        assert adapter.calls == 0
    finally:
        engine.dispose()
