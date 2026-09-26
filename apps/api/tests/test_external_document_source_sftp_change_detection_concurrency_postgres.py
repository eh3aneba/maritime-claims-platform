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
from app.modules.external_document_sources.sftp_change_detection_models import (
    ExternalDocumentSourceSftpChangeDetection,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    execute_external_document_source_sftp_change_detection,
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from tests.test_external_document_source_sftp_change_detection import (
    _REASON,
    _StatAdapter,
    _baseline,
    _completed_phase_k,
    setup_function as _l_setup,
    teardown_function as _l_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_CHANGE_DETECTION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-L concurrency regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _l_setup()


def teardown_function() -> None:
    _l_teardown()


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


def test_concurrent_sftp_change_detection_allows_one_stat_per_checkpoint() -> None:
    chain = _completed_phase_k("sftp-change-pg")
    checkpoint_id = UUID(chain["checkpoint_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    adapter = _StatAdapter(mode="unchanged", baseline=_baseline(chain))
    register_external_document_source_sftp_exact_file_metadata_adapter(adapter)

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpCheckpoint)
                .where(ExternalDocumentSourceSftpCheckpoint.id == checkpoint_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_change_detection(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        checkpoint_id=checkpoint_id,
                        requested_by_id=requester_id,
                        request_key="winner",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert adapter.calls == []
            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpChangeDetection
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = (
                execute_external_document_source_sftp_change_detection(
                    winner_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    checkpoint_id=checkpoint_id,
                    requested_by_id=requester_id,
                    request_key="winner",
                    request_reason=_REASON,
                )
            )
            assert outcome == "completed"
            assert row.result_status == "unchanged"
            winner_id = row.id
            winner_db.commit()
            assert len(adapter.calls) == 1

        with SessionLocal() as replay_db:
            replay, outcome = (
                execute_external_document_source_sftp_change_detection(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    checkpoint_id=checkpoint_id,
                    requested_by_id=requester_id,
                    request_key="winner",
                    request_reason=_REASON,
                )
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            assert len(adapter.calls) == 1

            with pytest.raises(ExternalDocumentSourceConflictError):
                execute_external_document_source_sftp_change_detection(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    checkpoint_id=checkpoint_id,
                    requested_by_id=requester_id,
                    request_key="second",
                    request_reason=_REASON,
                )
            replay_db.rollback()
            assert len(adapter.calls) == 1

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpChangeDetection)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].remote_stat_performed is True
            assert rows[0].remote_list_performed is False
            assert rows[0].remote_read_performed is False
            assert rows[0].checkpoint_advanced is False
            assert rows[0].document_created is False
            assert rows[0].evidence_admitted is False
    finally:
        engine.dispose()
