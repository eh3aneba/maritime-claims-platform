from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
)
from app.modules.external_document_sources.recurring_observation_schedule_service import (
    authorize_recurring_observation_schedule,
    disable_recurring_observation_schedule,
    replace_recurring_observation_schedule,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_family_version_admission import _bound_v1


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_OBSERVATION_SCHEDULE_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "PostgreSQL recurring observation schedule concurrency regressions run "
        "only in the dedicated PostgreSQL CI job"
    ),
)

_REASON = (
    "Authorize this bounded recurring metadata-only observation schedule for "
    "the exact external Evidence family under PostgreSQL concurrency."
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


def test_schedule_authorization_and_transition_races_reuse_one_evidence_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id, profile_id, _claim_id, _initial_execution, binding = _bound_v1(
        monkeypatch,
        "ab-pg-shared-races",
    )
    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as db:
            from app.modules.external_document_sources.evidence_family_binding_models import (
                ExternalDocumentSourceEvidenceFamilyBinding,
            )

            family = db.get(
                ExternalDocumentSourceEvidenceFamilyBinding,
                UUID(binding["id"]),
            )
            assert family is not None
            organization_id = family.organization_id

        # Scenario 1: concurrent initial authorizations create exactly one
        # active schedule authority for the Evidence family.
        barrier = Barrier(2)

        def authorize_one(label: str):
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    schedule, outcome = authorize_recurring_observation_schedule(
                        db,
                        organization_id=organization_id,
                        profile_id=UUID(profile_id),
                        binding_id=UUID(binding["id"]),
                        authorized_by_id=actor_id,
                        request_key=f"phase-ab-pg-auth-{label}",
                        reason=_REASON,
                        cadence_class="hourly",
                        effective_at=None,
                    )
                    return ("ok", schedule.id, outcome)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("conflict", None, None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            authorization_results = list(pool.map(authorize_one, ("a", "b")))

        assert sorted(result[0] for result in authorization_results) == [
            "conflict",
            "ok",
        ]

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(ExternalDocumentSourceRecurringObservationSchedule)
                    .where(
                        ExternalDocumentSourceRecurringObservationSchedule.binding_id
                        == UUID(binding["id"])
                    )
                    .order_by(
                        ExternalDocumentSourceRecurringObservationSchedule.revision_number.asc()
                    )
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].status == "active"
            assert rows[0].revision_number == 1
            assert rows[0].active_binding_guard == UUID(binding["id"])
            initial_id = rows[0].id

        # Scenario 2: reuse the exact winning active authority for the
        # replace-vs-disable race instead of rebuilding the prerequisite family.
        barrier = Barrier(2)

        def replace_one():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    schedule, _ = replace_recurring_observation_schedule(
                        db,
                        organization_id=organization_id,
                        profile_id=UUID(profile_id),
                        schedule_id=initial_id,
                        actor_id=actor_id,
                        request_key="phase-ab-pg-race-replace",
                        reason=(
                            "Replace the active recurring observation schedule "
                            "atomically during the PostgreSQL race regression."
                        ),
                        cadence_class="every_6_hours",
                        effective_at=None,
                    )
                    return ("replace", "ok", schedule.id)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("replace", "conflict", None)

        def disable_one():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                try:
                    schedule, _ = disable_recurring_observation_schedule(
                        db,
                        organization_id=organization_id,
                        profile_id=UUID(profile_id),
                        schedule_id=initial_id,
                        actor_id=actor_id,
                        request_key="phase-ab-pg-race-disable",
                        reason=(
                            "Disable the active recurring observation schedule "
                            "atomically during the PostgreSQL race regression."
                        ),
                    )
                    return ("disable", "ok", schedule.id)
                except (ExternalDocumentSourceConflictError, IntegrityError):
                    db.rollback()
                    return ("disable", "conflict", None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(replace_one)
            second = pool.submit(disable_one)
            transition_results = [first.result(), second.result()]

        assert sorted(result[1] for result in transition_results) == [
            "conflict",
            "ok",
        ]

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(ExternalDocumentSourceRecurringObservationSchedule)
                    .where(
                        ExternalDocumentSourceRecurringObservationSchedule.binding_id
                        == UUID(binding["id"])
                    )
                    .order_by(
                        ExternalDocumentSourceRecurringObservationSchedule.revision_number.asc()
                    )
                ).all()
            )
            active = [row for row in rows if row.status == "active"]
            assert len(active) <= 1
            assert len({row.revision_number for row in rows}) == len(rows)
            if len(rows) == 2:
                assert rows[0].status == "disabled"
                assert rows[1].revision_number == 2
                assert rows[1].prior_schedule_id == rows[0].id
                assert rows[1].status == "active"
            else:
                assert len(rows) == 1
                assert rows[0].status == "disabled"
    finally:
        engine.dispose()

