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
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from app.modules.external_document_sources.sftp_successor_restaging_models import (
    ExternalDocumentSourceSftpSuccessorRestaging,
)
from app.modules.external_document_sources.sftp_successor_restaging_service import (
    execute_external_document_source_sftp_successor_restaging,
)
from tests.test_external_document_source_sftp_file_content_proof import (
    _FileReadAdapter,
)
from tests.test_external_document_source_sftp_quarantine_staging import (
    _QuarantineStore,
)
from tests.test_external_document_source_sftp_successor_restaging import (
    _REASON,
    _changed_phase_l,
    setup_function as _m_setup,
    teardown_function as _m_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_SUCCESSOR_RESTAGING_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-M concurrency regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _m_setup()


def teardown_function() -> None:
    _m_teardown()


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


def test_concurrent_sftp_successor_restaging_allows_one_reread_per_changed_observation() -> None:
    chain = _changed_phase_l("sftp-successor-pg")
    successor_body = b"r" * chain["baseline"]["byte_size"] + b"x"
    read_adapter = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    change_id = UUID(chain["change_detection_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpChangeDetection)
                .where(ExternalDocumentSourceSftpChangeDetection.id == change_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_successor_restaging(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        change_detection_id=change_id,
                        requested_by_id=requester_id,
                        request_key="winner",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert read_adapter.calls == []
            assert store.put_calls == 0
            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpSuccessorRestaging
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = execute_external_document_source_sftp_successor_restaging(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                change_detection_id=change_id,
                requested_by_id=requester_id,
                request_key="winner",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert row.result_status == "successor_staged_verified"
            winner_id = row.id
            winner_db.commit()
            assert len(read_adapter.calls) == 1
            assert store.put_calls == 1

        with SessionLocal() as replay_db:
            replay, outcome = execute_external_document_source_sftp_successor_restaging(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                change_detection_id=change_id,
                requested_by_id=requester_id,
                request_key="winner",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            assert len(read_adapter.calls) == 1
            assert store.put_calls == 1

            with pytest.raises(ExternalDocumentSourceConflictError):
                execute_external_document_source_sftp_successor_restaging(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    change_detection_id=change_id,
                    requested_by_id=requester_id,
                    request_key="second",
                    request_reason=_REASON,
                )
            replay_db.rollback()
            assert len(read_adapter.calls) == 1

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpSuccessorRestaging)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].successor_generation == 2
            assert rows[0].checkpoint_advanced is False
            assert rows[0].storage_delete_performed is False
            assert rows[0].storage_copy_performed is False
            assert rows[0].document_created is False
            assert rows[0].evidence_admitted is False
    finally:
        engine.dispose()
