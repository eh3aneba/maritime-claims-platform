from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_service import (
    authorize_external_document_source_sftp_evidence_admission,
)
from app.modules.external_document_sources.sftp_generation3_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement,
)
from tests.test_external_document_source_sftp_evidence_admission_authorization import (
    _AUTH_REASON,
    _seed_claim,
    _unchanged_phase_r,
    setup_function as _s_setup,
    teardown_function as _s_teardown,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SFTP_EVIDENCE_ADMISSION_AUTHORIZATION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Phase 17.6-S currentness serialization regression runs only in PostgreSQL CI",
)


def setup_function() -> None:
    _s_setup()


def teardown_function() -> None:
    _s_teardown()


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


def test_sftp_evidence_authorization_locks_generation3_checkpoint_for_latest_decision() -> None:
    chain, adapter, r_body = _unchanged_phase_r("sftp-phase-s-pg")
    claim_id = _seed_claim(chain["requester_id"], "pg")
    checkpoint_id = UUID(chain["generation3_checkpoint_advancement_id"])
    observation_id = UUID(r_body["id"])
    profile_id = UUID(chain["profile_id"])
    organization_id = chain["org_id"]
    requester_id = chain["requester_id"]
    provider_calls_before = len(adapter.calls)

    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as lock_owner:
            locked = lock_owner.scalar(
                select(ExternalDocumentSourceSftpGeneration3CheckpointAdvancement)
                .where(
                    ExternalDocumentSourceSftpGeneration3CheckpointAdvancement.id
                    == checkpoint_id
                )
                .with_for_update()
            )
            assert locked is not None

            with SessionLocal() as blocked_db:
                blocked_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError):
                    authorize_external_document_source_sftp_evidence_admission(
                        blocked_db,
                        organization_id=organization_id,
                        profile_id=profile_id,
                        generation3_change_detection_id=observation_id,
                        claim_id=claim_id,
                        authorized_by_id=requester_id,
                        request_key="s-pg-auth",
                        authorization_reason=_AUTH_REASON,
                    )
                blocked_db.rollback()

            assert len(adapter.calls) == provider_calls_before
            assert (
                lock_owner.query(
                    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization
                ).count()
                == 0
            )
            lock_owner.rollback()

        with SessionLocal() as winner_db:
            row, outcome = authorize_external_document_source_sftp_evidence_admission(
                winner_db,
                organization_id=organization_id,
                profile_id=profile_id,
                generation3_change_detection_id=observation_id,
                claim_id=claim_id,
                authorized_by_id=requester_id,
                request_key="s-pg-auth",
                authorization_reason=_AUTH_REASON,
            )
            assert outcome == "authorized"
            winner_id = row.id
            winner_db.commit()

        assert len(adapter.calls) == provider_calls_before

        with SessionLocal() as replay_db:
            replay, outcome = authorize_external_document_source_sftp_evidence_admission(
                replay_db,
                organization_id=organization_id,
                profile_id=profile_id,
                generation3_change_detection_id=observation_id,
                claim_id=claim_id,
                authorized_by_id=requester_id,
                request_key="s-pg-auth",
                authorization_reason=_AUTH_REASON,
            )
            assert outcome == "replayed"
            assert replay.id == winner_id
            replay_db.rollback()

        assert len(adapter.calls) == provider_calls_before
    finally:
        engine.dispose()
