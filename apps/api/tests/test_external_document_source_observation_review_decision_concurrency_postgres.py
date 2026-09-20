from __future__ import annotations

from datetime import UTC, datetime
import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
    ExternalDocumentSourceObservationReviewDecisionReceipt,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
)
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_evidence_family_binding import (
    setup_function as _phase_y_setup,
    teardown_function as _phase_y_teardown,
)
from tests.test_external_document_source_observation_review_decision import (
    _changed_result,
    _prepare_handoff,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_REVIEW_DECISION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase AG concurrency regression runs only in the dedicated PostgreSQL CI job",
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


def test_two_human_decisions_serialize_to_one_terminal_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        handoff_id,
        result_status,
        adapter,
    ) = _prepare_handoff(monkeypatch, "ag-pg-decision-race", _changed_result())
    assert result_status == "changed"
    assert adapter.calls == 1

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as first_db:
            locked = first_db.scalar(
                select(ExternalDocumentSourceObservationReviewHandoff)
                .where(ExternalDocumentSourceObservationReviewHandoff.id == handoff_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    decide_observation_review_handoff(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        handoff_id=handoff_id,
                        decided_by_id=actor_id,
                        request_key="ag-pg-decision-race",
                        decision_kind="approve_refresh",
                        decision_reason="Human reviewer authorizes one exact future refresh.",
                        now=datetime(2026, 9, 20, 0, 2, tzinfo=UTC),
                    )
                blocked_db.rollback()

            decision, authorization, outcome = decide_observation_review_handoff(
                first_db,
                organization_id=organization_id,
                profile_id=profile_id,
                handoff_id=handoff_id,
                decided_by_id=actor_id,
                request_key="ag-pg-decision-race",
                decision_kind="approve_refresh",
                decision_reason="Human reviewer authorizes one exact future refresh.",
                now=datetime(2026, 9, 20, 0, 2, tzinfo=UTC),
            )
            assert outcome == "decided"
            assert authorization is not None
            decision_id = decision.id
            authorization_id = authorization.id

        with SessionLocal() as second_db:
            replay, replay_auth, outcome = decide_observation_review_handoff(
                second_db,
                organization_id=organization_id,
                profile_id=profile_id,
                handoff_id=handoff_id,
                decided_by_id=actor_id,
                request_key="ag-pg-decision-race",
                decision_kind="approve_refresh",
                decision_reason="Human reviewer authorizes one exact future refresh.",
                now=datetime(2026, 9, 20, 0, 3, tzinfo=UTC),
            )
            assert outcome == "replayed"
            assert replay.id == decision_id
            assert replay_auth is not None
            assert replay_auth.id == authorization_id

        with SessionLocal() as conflict_db:
            with pytest.raises(ExternalDocumentSourceConflictError):
                decide_observation_review_handoff(
                    conflict_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    handoff_id=handoff_id,
                    decided_by_id=actor_id,
                    request_key="ag-pg-conflicting-dismissal",
                    decision_kind="dismiss",
                    decision_reason="A conflicting reviewer attempts a later dismissal decision.",
                )
            conflict_db.rollback()

        with SessionLocal() as db:
            assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 1
            assert db.query(ExternalDocumentSourceObservationReviewDecisionReceipt).count() == 1
            assert db.query(ExternalDocumentSourceObservationRefreshAuthorization).count() == 1

        assert adapter.calls == 1
    finally:
        engine.dispose()
