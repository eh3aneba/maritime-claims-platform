from __future__ import annotations

from datetime import UTC, datetime
import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from tests.test_external_document_source_observation_refresh_admission_authorization import (
    _AUTH_REASON,
    setup_function as _ai_setup,
    teardown_function as _ai_teardown,
)
from tests.test_external_document_source_observation_refresh_admission_execution_concurrency_postgres import (
    _seed_authorized_refresh,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_REFRESH_ADMISSION_AUTH_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase AI concurrency regression runs only in the dedicated PostgreSQL CI job",
)


def setup_function() -> None:
    _ai_setup()


def teardown_function() -> None:
    _ai_teardown()


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


def test_concurrent_refresh_admission_authorizers_serialize_on_exact_ah_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        _document_id,
        refresh_id,
        existing_authorization_id,
        _binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _seed_authorized_refresh(
        monkeypatch,
        "ai-pg-race",
        include_admission_authorization=False,
    )
    assert existing_authorization_id is None

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceObservationRefreshExecution)
                .where(
                    ExternalDocumentSourceObservationRefreshExecution.id
                    == refresh_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    authorize_observation_refresh_admission(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        refresh_execution_id=refresh_id,
                        authorized_by_id=actor_id,
                        request_key="ai-pg-blocked",
                        authorization_reason=_AUTH_REASON,
                        now=datetime(2026, 9, 21, 1, 1, tzinfo=UTC),
                    )
                blocked_db.rollback()

            assert (
                lock_owner.query(
                    ExternalDocumentSourceObservationRefreshAdmissionAuthorization
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            authorization, outcome = authorize_observation_refresh_admission(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                refresh_execution_id=refresh_id,
                authorized_by_id=actor_id,
                request_key="ai-pg-winner",
                authorization_reason=_AUTH_REASON,
                now=datetime(2026, 9, 21, 1, 2, tzinfo=UTC),
            )
            assert outcome == "authorized"
            authorization_id = authorization.id

        with SessionLocal() as db:
            rows = db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization
            ).all()
            assert len(rows) == 1
            assert rows[0].id == authorization_id
            assert rows[0].refresh_execution_id == refresh_id
    finally:
        engine.dispose()
