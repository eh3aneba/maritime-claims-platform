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
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_checkpoint_service import (
    create_external_document_source_sftp_checkpoint,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    ExternalDocumentSourceSftpQuarantineStaging,
)
from tests.test_external_document_source_sftp_checkpoint import (
    _REASON,
    _completed_phase_j,
    setup_function as _k_setup,
    teardown_function as _k_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_CHECKPOINT_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-K concurrency regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _k_setup()


def teardown_function() -> None:
    _k_teardown()


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


def test_concurrent_sftp_checkpoint_allows_one_checkpoint_per_exact_staging() -> None:
    chain = _completed_phase_j("sftp-checkpoint-pg")
    staging_id = UUID(chain["staging_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpQuarantineStaging)
                .where(
                    ExternalDocumentSourceSftpQuarantineStaging.id
                    == staging_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    create_external_document_source_sftp_checkpoint(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        quarantine_staging_id=staging_id,
                        requested_by_id=requester_id,
                        request_key="winner",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpCheckpoint
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = create_external_document_source_sftp_checkpoint(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                quarantine_staging_id=staging_id,
                requested_by_id=requester_id,
                request_key="winner",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert row.result_status == "checkpoint_recorded"
            winner_id = row.id
            winner_db.commit()

        with SessionLocal() as replay_db:
            replay, outcome = create_external_document_source_sftp_checkpoint(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                quarantine_staging_id=staging_id,
                requested_by_id=requester_id,
                request_key="winner",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id

            with pytest.raises(ExternalDocumentSourceConflictError):
                create_external_document_source_sftp_checkpoint(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    quarantine_staging_id=staging_id,
                    requested_by_id=requester_id,
                    request_key="second",
                    request_reason=_REASON,
                )
            replay_db.rollback()

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpCheckpoint)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].checkpoint_generation == 1
            assert rows[0].provider_network_performed is False
            assert rows[0].storage_read_performed is False
            assert rows[0].storage_write_performed is False
            assert rows[0].document_created is False
            assert rows[0].evidence_admitted is False
    finally:
        engine.dispose()
