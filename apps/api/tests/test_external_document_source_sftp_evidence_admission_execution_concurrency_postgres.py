from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.documents.models import ConfidentialityLevel
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecution,
)
from app.modules.external_document_sources.sftp_evidence_admission_execution_service import (
    execute_external_document_source_sftp_evidence_admission,
)
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_evidence_admission_execution import (
    _EXECUTION_REASON,
    _authorized_phase_s,
    _enable_clean_admission,
    setup_function as _t_setup,
    teardown_function as _t_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_EVIDENCE_ADMISSION_EXECUTION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-T single-use/currentness regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _t_setup()


def teardown_function() -> None:
    _t_teardown()


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


def test_sftp_evidence_admission_execution_locks_authorization_for_single_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, _claim_id, authorization = _authorized_phase_s(
        "sftp-phase-t-pg"
    )
    _enable_clean_admission(monkeypatch)
    authorization_id = UUID(authorization["id"])
    profile_id = UUID(chain["profile_id"])
    requester_id = chain["requester_id"]
    with TestingSessionLocal() as db:
        actor = db.get(User, requester_id)
        assert actor is not None
        organization_id = actor.organization_id

    provider_calls_before = len(adapter.calls)
    staged_gets_before = chain["p_store"].get_calls

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpEvidenceAdmissionAuthorization)
                .where(
                    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization.id
                    == authorization_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_evidence_admission(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        authorization_id=authorization_id,
                        executed_by_id=requester_id,
                        request_key="t-pg-exec",
                        execution_reason=_EXECUTION_REASON,
                        document_type="External SFTP survey evidence",
                        confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
                    )
                blocked_db.rollback()

            assert len(adapter.calls) == provider_calls_before
            assert chain["p_store"].get_calls == staged_gets_before
            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpEvidenceAdmissionExecution
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = execute_external_document_source_sftp_evidence_admission(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                executed_by_id=requester_id,
                request_key="t-pg-exec",
                execution_reason=_EXECUTION_REASON,
                document_type="External SFTP survey evidence",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            )
            assert outcome == "admitted"
            winner_id = row.id

        calls_after = len(adapter.calls)
        gets_after = chain["p_store"].get_calls

        with SessionLocal() as replay_db:
            replay, outcome = execute_external_document_source_sftp_evidence_admission(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                executed_by_id=requester_id,
                request_key="t-pg-exec",
                execution_reason=_EXECUTION_REASON,
                document_type="External SFTP survey evidence",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
            )
            assert outcome == "replayed"
            assert replay.id == winner_id

        assert len(adapter.calls) == calls_after
        assert chain["p_store"].get_calls == gets_after
    finally:
        engine.dispose()
