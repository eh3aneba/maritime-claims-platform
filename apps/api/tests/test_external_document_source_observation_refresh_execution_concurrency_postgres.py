from __future__ import annotations

from datetime import UTC, datetime
import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
)
from tests.test_external_document_source_observation_refresh_admission_execution_concurrency_postgres import (
    _seed_authorized_refresh,
)
from tests.test_external_document_source_observation_refresh_execution import (
    _refresh_io,
    setup_function as _ah_setup,
    teardown_function as _ah_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_REFRESH_EXECUTION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase AH concurrency regression runs only in the dedicated PostgreSQL CI job",
)


def setup_function() -> None:
    _ah_setup()


def teardown_function() -> None:
    _ah_teardown()


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


def test_two_refresh_consumers_serialize_on_exact_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        authorization_id,
        _metadata_adapter,
    ) = _seed_authorized_refresh(
        monkeypatch,
        "ah-pg-race",
        include_refresh_execution=False,
    )
    _body, read_adapter, store = _refresh_io()

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceObservationRefreshAuthorization)
                .where(
                    ExternalDocumentSourceObservationRefreshAuthorization.id
                    == authorization_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_observation_refresh_authorization(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        authorization_id=authorization_id,
                        requested_by_id=actor_id,
                        request_key="ah-pg-blocked",
                        request_reason="A concurrent consumer must block on the exact refresh authorization.",
                        now=datetime(2026, 9, 21, 0, 3, tzinfo=UTC),
                    )
                blocked_db.rollback()

            assert read_adapter.calls == 0
            assert store.put_calls == 0
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            execution, outcome = execute_observation_refresh_authorization(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                requested_by_id=actor_id,
                request_key="ah-pg-winner",
                request_reason="One consumer wins the exact authorization and stages the changed content.",
                now=datetime(2026, 9, 21, 0, 4, tzinfo=UTC),
            )
            assert outcome == "completed"
            execution_id = execution.id

        assert read_adapter.calls == 1
        assert store.put_calls == 1
        with SessionLocal() as db:
            rows = db.query(ExternalDocumentSourceObservationRefreshExecution).all()
            assert len(rows) == 1
            assert rows[0].id == execution_id
            assert rows[0].authorization_id == authorization_id
    finally:
        engine.dispose()
