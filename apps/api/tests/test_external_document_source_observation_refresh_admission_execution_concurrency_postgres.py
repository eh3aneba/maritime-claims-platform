from __future__ import annotations

import os
from datetime import UTC, datetime
from time import perf_counter

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.modules.external_document_sources.observation_refresh_admission_execution_service as aj_service
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import consume_due_tick_dispatch
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import authorize_observation_refresh_admission
from app.modules.external_document_sources.observation_refresh_execution_service import execute_observation_refresh_authorization
from app.modules.external_document_sources.observation_review_decision_service import decide_observation_review_handoff
from app.modules.external_document_sources.observation_review_handoff_service import project_observation_review_handoff
from app.modules.documents.malware import MalwareScanResult, MalwareScanVerdict
from app.modules.documents.models import Document
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_due_tick_service_executor import _prepare
from tests.test_external_document_source_observation_refresh_admission_authorization import (
    _AUTH_REASON as _AI_AUTH_REASON,
)
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _EXEC_REASON,
    setup_function as _aj_setup,
    teardown_function as _aj_teardown,
)
from tests.test_external_document_source_observation_refresh_execution import _refresh_io
from tests.test_external_document_source_observation_review_decision import _changed_result


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_REFRESH_ADMISSION_EXEC_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "Phase AJ concurrency regression runs only in the dedicated PostgreSQL CI job"
    ),
)


def setup_function() -> None:
    _aj_setup()


def teardown_function() -> None:
    _aj_teardown()


def _profiled_authorized_refresh(monkeypatch: pytest.MonkeyPatch, suffix: str):
    timings: dict[str, float] = {}

    started = perf_counter()
    (
        actor_id,
        profile_id,
        _schedule_id,
        organization_id,
        document_id,
        dispatch_id,
        metadata_adapter,
    ) = _prepare(monkeypatch, suffix)
    timings["prepare"] = perf_counter() - started

    metadata_adapter.result = _changed_result()
    started = perf_counter()
    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        handoff, projected = project_observation_review_handoff(
            db,
            observation_execution_id=observation.id,
            projector_id="external-evidence-review-projector-v1",
            now=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
        )
        assert handoff is not None
        assert projected == "projected"
        assert handoff.result_status == "changed"
        handoff_id = handoff.id
    timings["observe_and_handoff"] = perf_counter() - started

    started = perf_counter()
    with TestingSessionLocal() as db:
        decision, refresh_authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key=f"{suffix}-approve",
            decision_kind="approve_refresh",
            decision_reason="Human reviewer authorizes one exact changed-item content refresh.",
            now=datetime(2026, 9, 21, 0, 2, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert refresh_authorization is not None
        refresh_authorization_id = refresh_authorization.id
        _decision_id = decision.id
    timings["review_decision"] = perf_counter() - started

    started = perf_counter()
    _body, read_adapter, store = _refresh_io()
    timings["refresh_io_registration"] = perf_counter() - started

    started = perf_counter()
    with TestingSessionLocal() as db:
        refresh, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key=f"{suffix}-refresh",
            request_reason=(
                "Consume the approved changed-item refresh and stage the exact "
                "remote content before any Evidence admission authority exists."
            ),
            now=datetime(2026, 9, 21, 1, 0, tzinfo=UTC),
        )
        assert outcome == "completed"
        refresh_id = refresh.id
    timings["refresh_execution"] = perf_counter() - started

    started = perf_counter()
    with TestingSessionLocal() as db:
        authorization, outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key=f"{suffix}-ai-auth",
            authorization_reason=_AI_AUTH_REASON,
            now=datetime(2026, 9, 22, 1, 0, tzinfo=UTC),
        )
        assert outcome == "authorized"
        authorization_id = authorization.id
        binding_id = authorization.binding_id
        claim_id = authorization.claim_id
    timings["admission_authorization"] = perf_counter() - started

    total = sum(timings.values())
    timing_text = ", ".join(f"{name}={seconds:.3f}s" for name, seconds in timings.items())
    print(f"AJ fixture timing: {timing_text}, total={total:.3f}s")

    return (
        actor_id,
        profile_id,
        organization_id,
        claim_id,
        document_id,
        refresh_id,
        authorization_id,
        binding_id,
        metadata_adapter,
        read_adapter,
        store,
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


def test_concurrent_aj_consumers_serialize_on_exact_ai_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _profiled_authorized_refresh(monkeypatch, "aj-pg-race")

    monkeypatch.setattr(aj_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(
        aj_service,
        "validate_file_signature",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        aj_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(
            verdict=MalwareScanVerdict.CLEAN
        ),
    )

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(
                    ExternalDocumentSourceObservationRefreshAdmissionAuthorization
                )
                .where(
                    ExternalDocumentSourceObservationRefreshAdmissionAuthorization.id
                    == authorization_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_observation_refresh_admission(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        binding_id=binding_id,
                        authorization_id=authorization_id,
                        executed_by_id=actor_id,
                        request_key="aj-pg-blocked",
                        execution_reason=_EXEC_REASON,
                    )
                blocked_db.rollback()

            assert (
                lock_owner.query(
                    ExternalDocumentSourceObservationRefreshAdmissionExecution
                ).count()
                == 0
            )
            prior = lock_owner.get(Document, prior_document_id)
            assert prior is not None and prior.is_current is True
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            execution, outcome = execute_observation_refresh_admission(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-pg-winner",
                execution_reason=_EXEC_REASON,
            )
            assert outcome == "admitted"
            execution_id = execution.id
            new_document_id = execution.new_document_id

        with SessionLocal() as db:
            rows = db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).all()
            assert len(rows) == 1
            assert rows[0].id == execution_id
            assert rows[0].authorization_id == authorization_id

            prior = db.get(Document, prior_document_id)
            new = db.get(Document, new_document_id)
            assert prior is not None and new is not None
            assert prior.is_current is False
            assert new.is_current is True
            assert new.version_number == prior.version_number + 1
            assert new.supersedes_document_id == prior.id
            current = list(
                db.scalars(
                    select(Document).where(
                        Document.organization_id == organization_id,
                        Document.claim_id == new.claim_id,
                        Document.document_family_id == new.document_family_id,
                        Document.is_current.is_(True),
                        Document.deleted_at.is_(None),
                    )
                ).all()
            )
            assert len(current) == 1
            assert current[0].id == new.id
    finally:
        engine.dispose()
