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
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    ExternalDocumentSourceSftpGeneration3Restaging,
)
from app.modules.external_document_sources.sftp_generation3_restaging_service import (
    execute_external_document_source_sftp_generation3_restaging,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from app.modules.external_document_sources.sftp_successor_change_detection_models import (
    ExternalDocumentSourceSftpSuccessorChangeDetection,
)
from tests.test_external_document_source_sftp_file_content_proof import _FileReadAdapter
from tests.test_external_document_source_sftp_generation3_restaging import (
    _REASON,
    _changed_phase_o,
    setup_function as _p_setup,
    teardown_function as _p_teardown,
)
from tests.test_external_document_source_sftp_quarantine_staging import _QuarantineStore


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_GENERATION3_RESTAGING_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-P concurrency regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _p_setup()


def teardown_function() -> None:
    _p_teardown()


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


def test_generation3_restaging_lock_prevents_duplicate_reread_and_put() -> None:
    chain = _changed_phase_o("sftp-g3-pg")
    successor_body = b"p" * chain["o_observed_size"]
    read_adapter = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    observation_id = UUID(chain["successor_change_detection_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpSuccessorChangeDetection)
                .where(ExternalDocumentSourceSftpSuccessorChangeDetection.id == observation_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_generation3_restaging(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        successor_change_detection_id=observation_id,
                        requested_by_id=requester_id,
                        request_key="winner",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert read_adapter.calls == []
            assert store.put_calls == 0
            assert lock_owner.query(
                ExternalDocumentSourceSftpGeneration3Restaging
            ).count() == 0
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = execute_external_document_source_sftp_generation3_restaging(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                successor_change_detection_id=observation_id,
                requested_by_id=requester_id,
                request_key="winner",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert row.result_status == "generation3_staged_verified"
            winner_id = row.id
            winner_db.commit()

        assert len(read_adapter.calls) == 1
        assert store.put_calls == 1

        with SessionLocal() as replay_db:
            replay, outcome = execute_external_document_source_sftp_generation3_restaging(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                successor_change_detection_id=observation_id,
                requested_by_id=requester_id,
                request_key="winner",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            replay_db.rollback()

        assert len(read_adapter.calls) == 1
        assert store.put_calls == 1
    finally:
        engine.dispose()

def test_content_verified_recovery_serializes_before_reread_or_put() -> None:
    chain = _changed_phase_o("sftp-g3-recovery-lock-pg")
    successor_body = b"q" * chain["o_observed_size"]
    read_adapter = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore(fail_first_head_after_put=True)
    register_external_document_source_sftp_quarantine_staging_store(store)

    observation_id = UUID(chain["successor_change_detection_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        # Force one crash after PUT. The content proof must remain committed.
        with SessionLocal() as first_db:
            with pytest.raises(ExternalDocumentSourceConflictError):
                execute_external_document_source_sftp_generation3_restaging(
                    first_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    successor_change_detection_id=observation_id,
                    requested_by_id=requester_id,
                    request_key="recovery",
                    request_reason=_REASON,
                )
            first_db.rollback()

        assert len(read_adapter.calls) == 1
        assert store.put_calls == 1

        with SessionLocal() as verify_db:
            anchor = verify_db.scalar(
                select(ExternalDocumentSourceSftpGeneration3Restaging).where(
                    ExternalDocumentSourceSftpGeneration3Restaging.successor_change_detection_id
                    == observation_id
                )
            )
            assert anchor is not None
            assert anchor.status == "content_verified"
            assert anchor.content_proof_hash is not None
            anchor_id = anchor.id

        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpGeneration3Restaging)
                .where(ExternalDocumentSourceSftpGeneration3Restaging.id == anchor_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_generation3_restaging(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        successor_change_detection_id=observation_id,
                        requested_by_id=requester_id,
                        request_key="recovery",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert len(read_adapter.calls) == 1
            assert store.put_calls == 1
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = execute_external_document_source_sftp_generation3_restaging(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                successor_change_detection_id=observation_id,
                requested_by_id=requester_id,
                request_key="recovery",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert row.id == anchor_id
            assert row.result_status == "generation3_staged_verified"
            winner_db.commit()

        assert len(read_adapter.calls) == 1
        assert store.put_calls == 1
    finally:
        engine.dispose()

