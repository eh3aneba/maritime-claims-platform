from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.change_detection_service import ExactItemMetadataResult
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
    ExternalDocumentSourceObservationReviewHandoffReceipt,
)
from app.modules.external_document_sources.observation_review_handoff_service import (
    project_observation_review_handoff,
)
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_external_document_source_due_tick_service_executor import _prepare
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_generation_3_change_detection import _baseline_projection


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_REVIEW_HANDOFF_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase AF concurrency regression runs only in the dedicated PostgreSQL CI job",
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


def test_two_projectors_racing_one_changed_observation_create_one_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _actor_id,
        _profile_id,
        _schedule_id,
        _organization_id,
        _document_id,
        dispatch_id,
        adapter,
    ) = _prepare(monkeypatch, "af-pg-race")

    baseline = _baseline_projection()
    changed = baseline.__class__(
        provider_item_id=baseline.provider_item_id,
        parent_item_id=baseline.parent_item_id,
        item_kind=baseline.item_kind,
        display_name=baseline.display_name,
        mime_type_class=baseline.mime_type_class,
        byte_size=(baseline.byte_size or 0) + 31,
        modified_at=datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
        version_token_hash="d" * 64,
    )
    adapter.result = ExactItemMetadataResult(found=True, item=changed)

    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        assert observation.result_status == "changed"
        observation_id = observation.id

    assert adapter.calls == 1

    engine, SessionLocal = _session_factory()
    barrier = Barrier(2)
    try:
        def project():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                handoff, outcome = project_observation_review_handoff(
                    db,
                    observation_execution_id=observation_id,
                    projector_id="external-evidence-review-projector-v1",
                    now=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
                )
                assert handoff is not None
                return handoff.id, outcome

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(project)
            second = pool.submit(project)
            results = [first.result(timeout=30), second.result(timeout=30)]

        ids = {row[0] for row in results}
        assert len(ids) == 1
        assert {row[1] for row in results} == {"projected", "replayed"}

        with SessionLocal() as db:
            handoffs = list(
                db.scalars(select(ExternalDocumentSourceObservationReviewHandoff)).all()
            )
            receipts = list(
                db.scalars(
                    select(ExternalDocumentSourceObservationReviewHandoffReceipt)
                ).all()
            )
            assert len(handoffs) == 1
            assert len(receipts) == 1
            assert handoffs[0].observation_execution_id == observation_id
            assert receipts[0].handoff_id == handoffs[0].id

        assert adapter.calls == 1
    finally:
        engine.dispose()
