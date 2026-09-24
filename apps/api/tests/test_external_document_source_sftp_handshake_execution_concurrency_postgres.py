from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.sftp_handshake_authorization_models import (
    ExternalDocumentSourceSftpHandshakeAuthorization,
)
from app.modules.external_document_sources.sftp_handshake_execution_models import (
    ExternalDocumentSourceSftpHandshakeExecution,
)
from app.modules.external_document_sources.sftp_handshake_execution_service import (
    execute_external_document_source_sftp_handshake_authorization,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_handshake_authorization import (
    _qualified_health,
    _request_authorization,
)
from tests.test_external_document_source_sftp_handshake_execution import (
    _EXECUTION_REASON,
    _approve,
    setup_function as _e_setup,
    teardown_function as _e_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_HANDSHAKE_EXECUTION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "Phase 17.6-E concurrency regression runs only in the dedicated "
        "PostgreSQL CI job"
    ),
)


def setup_function() -> None:
    _e_setup()


def teardown_function() -> None:
    _e_teardown()


def _seed_authorized_handshake(seed: str):
    (
        requester_id,
        approver_id,
        profile_id,
        _binding_id,
        qualification_id,
    ) = _qualified_health(seed)

    requested = _request_authorization(
        profile_id,
        qualification_id,
        requester_id,
        key=f"{seed}-authorization",
    )
    assert requested.status_code == 201, requested.text
    authorization_id = requested.json()["id"]

    approved = _approve(profile_id, authorization_id, approver_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "authorized"

    with TestingSessionLocal() as db:
        authorization = db.get(
            ExternalDocumentSourceSftpHandshakeAuthorization,
            authorization_id,
        )
        assert authorization is not None
        organization_id = authorization.organization_id

    return (
        requester_id,
        profile_id,
        organization_id,
        authorization_id,
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


def test_concurrent_sftp_handshake_consumers_serialize_on_exact_authorization() -> None:
    (
        requester_id,
        profile_id,
        organization_id,
        authorization_id,
    ) = _seed_authorized_handshake("sftp-handshake-exec-pg-race")

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpHandshakeAuthorization)
                .where(
                    ExternalDocumentSourceSftpHandshakeAuthorization.id
                    == authorization_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_handshake_authorization(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        authorization_id=authorization_id,
                        requested_by_id=requester_id,
                        request_key="sftp-handshake-exec-pg-blocked",
                        request_reason=_EXECUTION_REASON,
                    )
                blocked_db.rollback()

            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpHandshakeExecution
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            execution, outcome = (
                execute_external_document_source_sftp_handshake_authorization(
                    winner_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    authorization_id=authorization_id,
                    requested_by_id=requester_id,
                    request_key="sftp-handshake-exec-pg-winner",
                    request_reason=_EXECUTION_REASON,
                )
            )
            assert outcome == "completed"
            assert execution is not None
            winner_id = execution.id
            winner_db.commit()

        with SessionLocal() as replay_db:
            replay, outcome = (
                execute_external_document_source_sftp_handshake_authorization(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    authorization_id=authorization_id,
                    requested_by_id=requester_id,
                    request_key="sftp-handshake-exec-pg-winner",
                    request_reason=_EXECUTION_REASON,
                )
            )
            assert outcome == "unchanged"
            assert replay is not None
            assert replay.id == winner_id

            with pytest.raises(ExternalDocumentSourceConflictError):
                execute_external_document_source_sftp_handshake_authorization(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    authorization_id=authorization_id,
                    requested_by_id=requester_id,
                    request_key="sftp-handshake-exec-pg-second",
                    request_reason=_EXECUTION_REASON,
                )
            replay_db.rollback()

        with SessionLocal() as verify_db:
            assert (
                verify_db.query(
                    ExternalDocumentSourceSftpHandshakeExecution
                ).count()
                == 1
            )
            authorization = verify_db.get(
                ExternalDocumentSourceSftpHandshakeAuthorization,
                authorization_id,
            )
            assert authorization is not None
            assert authorization.status == "expired"
            assert authorization.sftp_handshake_authorized is False
            assert authorization.terminal_hash is not None
    finally:
        engine.dispose()
