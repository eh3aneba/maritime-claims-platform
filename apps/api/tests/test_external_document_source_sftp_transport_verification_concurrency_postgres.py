from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.sftp_handshake_execution_models import (
    ExternalDocumentSourceSftpHandshakeExecution,
)
from app.modules.external_document_sources.sftp_transport_verification_models import (
    ExternalDocumentSourceSftpTransportVerification,
)
from app.modules.external_document_sources.sftp_transport_verification_service import (
    register_external_document_source_sftp_transport_adapter,
    verify_external_document_source_sftp_transport,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.test_external_document_source_sftp_transport_verification import (
    _REASON,
    _DeterministicTransportAdapter,
    _completed_execution,
    _success_result,
    setup_function as _f_setup,
    teardown_function as _f_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_TRANSPORT_VERIFICATION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "Phase 17.6-F concurrency regression runs only in the dedicated "
        "PostgreSQL CI job"
    ),
)


def setup_function() -> None:
    _f_setup()


def teardown_function() -> None:
    _f_teardown()


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


def test_concurrent_sftp_transport_verifiers_allow_one_network_attempt() -> None:
    chain = _completed_execution("sftp-transport-pg-race")
    adapter = _DeterministicTransportAdapter(
        _success_result(chain["fingerprint"])
    )
    register_external_document_source_sftp_transport_adapter(adapter)

    execution_id = UUID(chain["execution_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpHandshakeExecution)
                .where(
                    ExternalDocumentSourceSftpHandshakeExecution.id
                    == execution_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    verify_external_document_source_sftp_transport(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        handshake_execution_id=execution_id,
                        requested_by_id=requester_id,
                        request_key="sftp-transport-pg-winner",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert adapter.calls == []
            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpTransportVerification
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            verification, outcome = (
                verify_external_document_source_sftp_transport(
                    winner_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    handshake_execution_id=execution_id,
                    requested_by_id=requester_id,
                    request_key="sftp-transport-pg-winner",
                    request_reason=_REASON,
                )
            )
            assert outcome == "completed"
            assert verification.result_status == "verified"
            winner_id = verification.id
            winner_db.commit()
            assert len(adapter.calls) == 1

        with SessionLocal() as replay_db:
            replay, outcome = verify_external_document_source_sftp_transport(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                handshake_execution_id=execution_id,
                requested_by_id=requester_id,
                request_key="sftp-transport-pg-winner",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            assert len(adapter.calls) == 1

            with pytest.raises(ExternalDocumentSourceConflictError):
                verify_external_document_source_sftp_transport(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    handshake_execution_id=execution_id,
                    requested_by_id=requester_id,
                    request_key="sftp-transport-pg-second",
                    request_reason=_REASON,
                )
            replay_db.rollback()
            assert len(adapter.calls) == 1

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpTransportVerification)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].result_status == "verified"
            assert rows[0].host_key_verified is True
    finally:
        engine.dispose()
