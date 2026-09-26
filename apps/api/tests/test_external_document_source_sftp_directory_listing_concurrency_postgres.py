from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.service import ExternalDocumentSourceConflictError
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListing,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    create_external_document_source_sftp_directory_listing,
    register_external_document_source_sftp_directory_listing_adapter,
)
from app.modules.external_document_sources.sftp_session_activation_models import (
    ExternalDocumentSourceSftpSessionActivation,
)
from tests.test_external_document_source_sftp_directory_listing import (
    _DirectoryListingAdapter,
    _REASON,
    _activated_chain,
    _success_listing_result,
    setup_function as _h_setup,
    teardown_function as _h_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_DIRECTORY_LISTING_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-H concurrency regression runs only in the dedicated PostgreSQL CI job",
)


def setup_function() -> None:
    _h_setup()


def teardown_function() -> None:
    _h_teardown()


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


def test_concurrent_sftp_directory_listings_allow_one_remote_listing_attempt() -> None:
    chain = _activated_chain("sftp-dir-pg-race")
    adapter = _DirectoryListingAdapter(_success_listing_result())
    register_external_document_source_sftp_directory_listing_adapter(adapter)

    activation_id = UUID(chain["activation_id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpSessionActivation)
                .where(ExternalDocumentSourceSftpSessionActivation.id == activation_id)
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    create_external_document_source_sftp_directory_listing(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        session_activation_id=activation_id,
                        requested_by_id=requester_id,
                        request_key="sftp-dir-pg-winner",
                        request_reason=_REASON,
                        relative_path="",
                    )
                blocked_db.rollback()

            assert adapter.calls == []
            assert lock_owner.query(ExternalDocumentSourceSftpDirectoryListing).count() == 0
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            listing, entries, outcome = create_external_document_source_sftp_directory_listing(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                session_activation_id=activation_id,
                requested_by_id=requester_id,
                request_key="sftp-dir-pg-winner",
                request_reason=_REASON,
                relative_path="",
            )
            assert outcome == "completed"
            assert listing.result_status == "listed"
            assert len(entries) == 2
            winner_id = listing.id
            winner_db.commit()
            assert len(adapter.calls) == 1

        with SessionLocal() as replay_db:
            replay, entries, outcome = create_external_document_source_sftp_directory_listing(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                session_activation_id=activation_id,
                requested_by_id=requester_id,
                request_key="sftp-dir-pg-winner",
                request_reason=_REASON,
                relative_path="",
            )
            assert outcome == "unchanged"
            assert replay.id == winner_id
            assert len(entries) == 2
            assert len(adapter.calls) == 1

            with pytest.raises(ExternalDocumentSourceConflictError):
                create_external_document_source_sftp_directory_listing(
                    replay_db,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    session_activation_id=activation_id,
                    requested_by_id=requester_id,
                    request_key="sftp-dir-pg-second",
                    request_reason=_REASON,
                    relative_path="",
                )
            replay_db.rollback()
            assert len(adapter.calls) == 1

        with SessionLocal() as verify_db:
            rows = list(
                verify_db.scalars(
                    select(ExternalDocumentSourceSftpDirectoryListing)
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].id == winner_id
            assert rows[0].result_status == "listed"
            assert rows[0].remote_list_performed is True
            assert rows[0].remote_read_performed is False
            assert rows[0].remote_write_performed is False
    finally:
        engine.dispose()
