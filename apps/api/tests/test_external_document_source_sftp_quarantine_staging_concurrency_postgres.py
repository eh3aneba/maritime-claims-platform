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
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    ExternalDocumentSourceSftpQuarantineStaging,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    execute_external_document_source_sftp_quarantine_staging,
    register_external_document_source_sftp_quarantine_staging_store,
)
from tests.test_external_document_source_sftp_quarantine_staging import (
    _QuarantineStore,
    _STAGE_REASON,
    _completed_phase_i,
    setup_function as _j_setup,
    teardown_function as _j_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_QUARANTINE_STAGING_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "Phase 17.6-J concurrency regression runs only in the dedicated "
        "PostgreSQL CI job"
    ),
)


def setup_function() -> None:
    _j_setup()


def teardown_function() -> None:
    _j_teardown()


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


def test_concurrent_sftp_quarantine_staging_allows_one_remote_reread_and_one_object() -> None:
    chain = _completed_phase_i("sftp-qstage-pg-race")
    adapter = chain["read_adapter"]
    before_j_calls = len(adapter.calls)

    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    proof_id = UUID(chain["proof_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpFileContentProof)
                .where(
                    ExternalDocumentSourceSftpFileContentProof.id == proof_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    execute_external_document_source_sftp_quarantine_staging(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        file_content_proof_id=proof_id,
                        requested_by_id=requester_id,
                        request_key="sftp-qstage-pg-winner",
                        request_reason=_STAGE_REASON,
                    )
                blocked_db.rollback()

            assert len(adapter.calls) == before_j_calls
            assert store.put_calls == 0
            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpQuarantineStaging
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = (
                execute_external_document_source_sftp_quarantine_staging(
                    winner_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    file_content_proof_id=proof_id,
                    requested_by_id=requester_id,
                    request_key="sftp-qstage-pg-winner",
                    request_reason=_STAGE_REASON,
                )
            )
            assert outcome == "completed"
            assert row.result_status == "staged_verified"
            winner_id = row.id
            winner_db.commit()
            assert len(adapter.calls) == before_j_calls + 1
            assert store.put_calls == 1
            assert len(store.objects) == 1

        with SessionLocal() as replay_db:
            replay, outcome = (
                execute_external_document_source_sftp_quarantine_staging(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    file_content_proof_id=proof_id,
                    requested_by_id=requester_id,
                    request_key="sftp-qstage-pg-winner",
                    request_reason=_STAGE_REASON,
                )
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            assert len(adapter.calls) == before_j_calls + 1
            assert store.put_calls == 1

            with pytest.raises(ExternalDocumentSourceConflictError):
                execute_external_document_source_sftp_quarantine_staging(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    file_content_proof_id=proof_id,
                    requested_by_id=requester_id,
                    request_key="sftp-qstage-pg-second",
                    request_reason=_STAGE_REASON,
                )
            replay_db.rollback()
            assert len(adapter.calls) == before_j_calls + 1
            assert store.put_calls == 1

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpQuarantineStaging)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].status == "completed"
            assert rows[0].durable_content_staged is True
            assert rows[0].storage_delete_performed is False
            assert rows[0].document_created is False
            assert rows[0].evidence_admitted is False
    finally:
        engine.dispose()
