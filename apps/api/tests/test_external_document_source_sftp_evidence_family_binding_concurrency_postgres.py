from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.evidence_family_binding_service import (
    bind_external_document_source_evidence_family,
)
from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from app.modules.external_document_sources.sftp_evidence_admission_execution_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecution,
)
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_evidence_admission_execution import (
    _authorized_phase_s,
    _enable_clean_admission,
    _execute,
    setup_function as _t_setup,
    teardown_function as _t_teardown,
)
from tests.test_external_document_source_sftp_evidence_family_binding import (
    _BIND_REASON,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_EVIDENCE_FAMILY_BINDING_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-U binding concurrency regression runs only in PostgreSQL CI",
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


def test_sftp_family_binding_serializes_on_phase_t_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, _claim_id, authorization = _authorized_phase_s(
        "sftp-phase-u-pg"
    )
    _enable_clean_admission(monkeypatch)
    admitted = _execute(
        chain,
        authorization["id"],
        key="u-pg-admit",
    )
    assert admitted.status_code == 201, admitted.text

    execution_id = UUID(admitted.json()["id"])
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
                select(ExternalDocumentSourceSftpEvidenceAdmissionExecution)
                .where(
                    ExternalDocumentSourceSftpEvidenceAdmissionExecution.id
                    == execution_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    bind_external_document_source_evidence_family(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        sftp_admission_execution_id=execution_id,
                        bound_by_id=requester_id,
                        request_key="u-pg-bind",
                        binding_reason=_BIND_REASON,
                    )
                blocked_db.rollback()

            assert len(adapter.calls) == provider_calls_before
            assert chain["p_store"].get_calls == staged_gets_before
            assert (
                lock_owner.query(ExternalDocumentSourceEvidenceFamilyBinding).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = bind_external_document_source_evidence_family(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                sftp_admission_execution_id=execution_id,
                bound_by_id=requester_id,
                request_key="u-pg-bind",
                binding_reason=_BIND_REASON,
            )
            assert outcome == "bound"
            winner_id = row.id

        with SessionLocal() as replay_db:
            replay, outcome = bind_external_document_source_evidence_family(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                sftp_admission_execution_id=execution_id,
                bound_by_id=requester_id,
                request_key="u-pg-bind",
                binding_reason=_BIND_REASON,
            )
            assert outcome == "replayed"
            assert replay.id == winner_id

        with SessionLocal() as duplicate_db:
            with pytest.raises(ExternalDocumentSourceConflictError) as exc_info:
                bind_external_document_source_evidence_family(
                    duplicate_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    sftp_admission_execution_id=execution_id,
                    bound_by_id=requester_id,
                    request_key="u-pg-bind-second",
                    binding_reason=_BIND_REASON,
                )
            assert "already bound" in str(exc_info.value).lower()

        assert len(adapter.calls) == provider_calls_before
        assert chain["p_store"].get_calls == staged_gets_before
    finally:
        engine.dispose()
