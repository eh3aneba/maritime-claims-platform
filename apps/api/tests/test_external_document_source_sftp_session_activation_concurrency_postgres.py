from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.sftp_session_activation_models import (
    ExternalDocumentSourceSftpSessionActivation,
)
from app.modules.external_document_sources.sftp_session_activation_service import (
    activate_external_document_source_sftp_session,
    register_external_document_source_sftp_session_activation_adapter,
)
from app.modules.external_document_sources.sftp_transport_verification_models import (
    ExternalDocumentSourceSftpTransportVerification,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.test_external_document_source_sftp_session_activation import (
    _REASON,
    _DeterministicSessionActivationAdapter,
    _success_activation_result,
    _verified_transport,
    setup_function as _g_setup,
    teardown_function as _g_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_SESSION_ACTIVATION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "Phase 17.6-G concurrency regression runs only in the dedicated "
        "PostgreSQL CI job"
    ),
)


def setup_function() -> None:
    _g_setup()


def teardown_function() -> None:
    _g_teardown()


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


def test_concurrent_sftp_session_activations_allow_one_authentication_attempt() -> None:
    chain = _verified_transport("sftp-session-pg-race")
    adapter = _DeterministicSessionActivationAdapter(_success_activation_result())
    register_external_document_source_sftp_session_activation_adapter(adapter)

    verification_id = UUID(chain["verification_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpTransportVerification)
                .where(ExternalDocumentSourceSftpTransportVerification.id == verification_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    activate_external_document_source_sftp_session(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        transport_verification_id=verification_id,
                        requested_by_id=requester_id,
                        request_key="sftp-session-pg-winner",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert adapter.calls == []
            assert (
                lock_owner.query(ExternalDocumentSourceSftpSessionActivation).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            activation, outcome = activate_external_document_source_sftp_session(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                transport_verification_id=verification_id,
                requested_by_id=requester_id,
                request_key="sftp-session-pg-winner",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert activation.result_status == "activated"
            winner_id = activation.id
            winner_db.commit()
            assert len(adapter.calls) == 1

        with SessionLocal() as replay_db:
            replay, outcome = activate_external_document_source_sftp_session(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                transport_verification_id=verification_id,
                requested_by_id=requester_id,
                request_key="sftp-session-pg-winner",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            assert len(adapter.calls) == 1

            with pytest.raises(ExternalDocumentSourceConflictError):
                activate_external_document_source_sftp_session(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    transport_verification_id=verification_id,
                    requested_by_id=requester_id,
                    request_key="sftp-session-pg-second",
                    request_reason=_REASON,
                )
            replay_db.rollback()
            assert len(adapter.calls) == 1

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpSessionActivation)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].result_status == "activated"
            assert rows[0].authentication_succeeded is True
            assert rows[0].sftp_session_opened is True
            assert rows[0].sftp_session_closed is True
    finally:
        engine.dispose()
