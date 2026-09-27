from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_service import (
    execute_external_document_source_sftp_generation3_checkpoint_advancement,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    ExternalDocumentSourceSftpGeneration3Restaging,
)
from tests.test_external_document_source_sftp_generation3_checkpoint_advancement import (
    _REASON,
    _completed_phase_p,
    setup_function as _q_setup,
    teardown_function as _q_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_GENERATION3_CHECKPOINT_ADVANCEMENT_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-Q concurrency regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _q_setup()


def teardown_function() -> None:
    _q_teardown()


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


def test_concurrent_generation3_checkpoint_advancement_allows_one_successor() -> None:
    chain = _completed_phase_p("sftp-g3-cp-pg")
    restaging_id = UUID(chain["generation3_restaging_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    read_before = len(chain["p_read_adapter"].calls)
    put_before = chain["p_store"].put_calls
    head_before = chain["p_store"].head_calls
    get_before = chain["p_store"].get_calls

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpGeneration3Restaging)
                .where(
                    ExternalDocumentSourceSftpGeneration3Restaging.id == restaging_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_generation3_checkpoint_advancement(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        generation3_restaging_id=restaging_id,
                        requested_by_id=requester_id,
                        request_key="q3",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = execute_external_document_source_sftp_generation3_checkpoint_advancement(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                generation3_restaging_id=restaging_id,
                requested_by_id=requester_id,
                request_key="q3",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert row.result_status == "checkpoint_advanced"
            assert row.successor_checkpoint_generation == 3
            winner_id = row.id
            winner_db.commit()

        with SessionLocal() as replay_db:
            replay, outcome = execute_external_document_source_sftp_generation3_checkpoint_advancement(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                generation3_restaging_id=restaging_id,
                requested_by_id=requester_id,
                request_key="q3",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id

            with pytest.raises(ExternalDocumentSourceConflictError):
                execute_external_document_source_sftp_generation3_checkpoint_advancement(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    generation3_restaging_id=restaging_id,
                    requested_by_id=requester_id,
                    request_key="q3-second",
                    request_reason=_REASON,
                )
            replay_db.rollback()

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].predecessor_checkpoint_generation == 2
            assert rows[0].successor_checkpoint_generation == 3
            assert rows[0].provider_network_performed is False
            assert rows[0].remote_read_performed is False
            assert rows[0].storage_read_performed is False
            assert rows[0].storage_write_performed is False
            assert rows[0].document_created is False
            assert rows[0].evidence_admitted is False

        assert len(chain["p_read_adapter"].calls) == read_before
        assert chain["p_store"].put_calls == put_before
        assert chain["p_store"].head_calls == head_before
        assert chain["p_store"].get_calls == get_before
    finally:
        engine.dispose()
