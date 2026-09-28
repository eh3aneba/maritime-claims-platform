from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.sftp_change_detection_service import (
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_generation3_change_detection_models import (
    ExternalDocumentSourceSftpGeneration3ChangeDetection,
)
from app.modules.external_document_sources.sftp_generation3_change_detection_service import (
    execute_external_document_source_sftp_generation3_change_detection,
)
from tests.test_external_document_source_sftp_change_detection import _StatAdapter
from tests.test_external_document_source_sftp_generation3_change_detection import (
    _REASON,
    _completed_phase_q,
    _generation_3_baseline,
    setup_function as _r_setup,
    teardown_function as _r_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_GENERATION3_CHANGE_DETECTION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-R concurrency regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _r_setup()


def teardown_function() -> None:
    _r_teardown()


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


def test_generation3_observation_lock_prevents_duplicate_provider_call_for_same_key() -> None:
    chain = _completed_phase_q("sftp-successor-observe-pg")
    adapter = _StatAdapter(mode="unchanged", baseline=_generation_3_baseline(chain))
    register_external_document_source_sftp_exact_file_metadata_adapter(adapter)

    advancement_id = UUID(chain["generation3_checkpoint_advancement_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement)
                .where(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.id == advancement_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_generation3_change_detection(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        generation3_checkpoint_advancement_id=advancement_id,
                        requested_by_id=requester_id,
                        request_key="o1",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert adapter.calls == []
            assert lock_owner.query(
                ExternalDocumentSourceSftpGeneration3ChangeDetection
            ).count() == 0
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = execute_external_document_source_sftp_generation3_change_detection(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                generation3_checkpoint_advancement_id=advancement_id,
                requested_by_id=requester_id,
                request_key="o1",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert row.result_status == "unchanged"
            winner_id = row.id
            winner_db.commit()
        assert len(adapter.calls) == 1

        with SessionLocal() as replay_db:
            replay, outcome = execute_external_document_source_sftp_generation3_change_detection(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                generation3_checkpoint_advancement_id=advancement_id,
                requested_by_id=requester_id,
                request_key="o1",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            replay_db.rollback()
        assert len(adapter.calls) == 1
    finally:
        engine.dispose()
