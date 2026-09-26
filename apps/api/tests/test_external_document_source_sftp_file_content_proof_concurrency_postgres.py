from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListingEntry,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    create_external_document_source_sftp_file_content_proof,
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.test_external_document_source_sftp_file_content_proof import (
    _FileReadAdapter,
    _REASON,
    _listed_chain,
    setup_function as _i_setup,
    teardown_function as _i_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_FILE_CONTENT_PROOF_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-I concurrency regression runs only in the dedicated PostgreSQL CI job",
)


def setup_function() -> None:
    _i_setup()


def teardown_function() -> None:
    _i_teardown()


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


def test_concurrent_sftp_file_content_proofs_allow_one_remote_read() -> None:
    chain = _listed_chain("sftp-content-pg-race")
    adapter = _FileReadAdapter()
    register_external_document_source_sftp_file_content_read_adapter(adapter)

    entry_id = UUID(chain["file_entry_id"])
    listing_id = UUID(chain["listing_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpDirectoryListingEntry)
                .where(ExternalDocumentSourceSftpDirectoryListingEntry.id == entry_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    create_external_document_source_sftp_file_content_proof(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        directory_listing_id=listing_id,
                        listing_entry_id=entry_id,
                        requested_by_id=requester_id,
                        request_key="sftp-content-pg-winner",
                        request_reason=_REASON,
                    )
                blocked_db.rollback()

            assert adapter.calls == []
            assert lock_owner.query(ExternalDocumentSourceSftpFileContentProof).count() == 0
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            proof, outcome = create_external_document_source_sftp_file_content_proof(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                directory_listing_id=listing_id,
                listing_entry_id=entry_id,
                requested_by_id=requester_id,
                request_key="sftp-content-pg-winner",
                request_reason=_REASON,
            )
            assert outcome == "completed"
            assert proof.result_status == "read_verified"
            winner_id = proof.id
            winner_db.commit()
            assert len(adapter.calls) == 1

        with SessionLocal() as replay_db:
            replay, outcome = create_external_document_source_sftp_file_content_proof(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                directory_listing_id=listing_id,
                listing_entry_id=entry_id,
                requested_by_id=requester_id,
                request_key="sftp-content-pg-winner",
                request_reason=_REASON,
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            assert len(adapter.calls) == 1

            with pytest.raises(ExternalDocumentSourceConflictError):
                create_external_document_source_sftp_file_content_proof(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    directory_listing_id=listing_id,
                    listing_entry_id=entry_id,
                    requested_by_id=requester_id,
                    request_key="sftp-content-pg-second",
                    request_reason=_REASON,
                )
            replay_db.rollback()
            assert len(adapter.calls) == 1

        with SessionLocal() as verify_db:
            rows = list(verify_db.scalars(select(ExternalDocumentSourceSftpFileContentProof)).all())
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].remote_read_performed is True
            assert rows[0].remote_content_transiently_observed is True
            assert rows[0].remote_content_stored is False
    finally:
        engine.dispose()
