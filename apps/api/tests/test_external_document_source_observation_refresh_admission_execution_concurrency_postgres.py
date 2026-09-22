from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.modules.external_document_sources.observation_refresh_admission_execution_service as aj_service
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
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _EXEC_REASON,
    _authorized_refresh,
    setup_function as _aj_setup,
    teardown_function as _aj_teardown,
)


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
    ) = _authorized_refresh(monkeypatch, "aj-pg-race")

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
