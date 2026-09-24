from __future__ import annotations

from datetime import UTC, datetime
import os
from uuid import UUID

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


def assert_two_human_decisions_serialize_to_one_terminal_approval(
    *,
    actor_id: UUID,
    profile_id: UUID,
    organization_id: UUID,
    handoff_id: UUID,
) -> None:
    engine, SessionLocal = _session_factory()
    try:
        # Hold the exact handoff authority in one PostgreSQL transaction.
        # A concurrent human decision must be unable to cross that row lock.
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
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
                        request_key="ag-pg-blocked-race",
                        decision_kind="approve_refresh",
                        decision_reason="Concurrent reviewer is blocked by exact handoff authority.",
                        now=datetime(2026, 9, 20, 0, 2, tzinfo=UTC),
                    )
                blocked_db.rollback()

            # This transaction is only the deterministic lock holder. Release
            # it without deciding so one clean post-lock transaction can win.
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            decision, authorization, outcome = decide_observation_review_handoff(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                handoff_id=handoff_id,
                decided_by_id=actor_id,
                request_key="ag-pg-winning-decision",
                decision_kind="approve_refresh",
                decision_reason="Human reviewer authorizes one exact future refresh.",
                now=datetime(2026, 9, 20, 0, 3, tzinfo=UTC),
            )
            assert outcome == "decided"
            assert authorization is not None
            assert decision.status == "refresh_authorized"
            assert authorization.status == "authorized"

        with SessionLocal() as db:
            assert db.query(ExternalDocumentSourceObservationReviewDecision).count() == 1
            assert db.query(ExternalDocumentSourceObservationReviewDecisionReceipt).count() == 1
            assert db.query(ExternalDocumentSourceObservationRefreshAuthorization).count() == 1
    finally:
        engine.dispose()
