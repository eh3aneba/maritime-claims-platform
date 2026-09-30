from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    ensure_observation_refresh_admission_execution_integrity,
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _enable_clean_aj,
)
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_sftp_file_content_proof import _FileReadAdapter
from tests.test_external_document_source_sftp_observation_refresh_execution import (
    _approved_sftp_refresh,
    setup_function as _ab_setup,
    teardown_function as _ab_teardown,
)


def setup_function() -> None:
    _ab_setup()


def teardown_function() -> None:
    _ab_teardown()


def test_phase_ac_admits_sftp_refresh_as_canonical_n_plus_one_without_second_remote_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _chain,
        _metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        refresh_authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "canonical-n-plus-one")

    changed_body = b"v" * observed_size
    read_adapter = _FileReadAdapter(content=changed_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        refresh, refresh_outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="sftp-phase-ac-refresh",
            request_reason="Stage the approved SFTP changed-file refresh for canonical admission.",
            now=datetime(2026, 9, 29, 4, 10, tzinfo=UTC),
        )
        assert refresh_outcome == "completed"
        assert refresh.provider_kind == "sftp"
        refresh_id = refresh.id
        prior_document_id = refresh.current_document_id
        binding_id = refresh.binding_id
        claim_id = refresh.claim_id

        admission_auth, auth_outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key="sftp-phase-ac-admission-auth",
            authorization_reason=(
                "Authorize this exact verified SFTP refresh for canonical Evidence admission."
            ),
            now=datetime(2026, 9, 29, 4, 11, tzinfo=UTC),
        )
        assert auth_outcome == "authorized"
        assert admission_auth.provider_kind == "sftp"
        assert admission_auth.expected_prior_document_id == prior_document_id
        admission_authorization_id = admission_auth.id

    assert len(read_adapter.calls) == 1
    provider_reads_before_admission = len(read_adapter.calls)
    security_calls = _enable_clean_aj(monkeypatch)

    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="sftp-phase-ac-admit",
            execution_reason=(
                "Admit the exact verified SFTP refresh as the next canonical Evidence version."
            ),
        )
        assert outcome == "admitted"
        assert execution.provider_kind == "sftp"
        assert execution.status == "admitted"
        assert execution.prior_document_id == prior_document_id
        assert execution.new_version_number == execution.prior_version_number + 1
        assert execution.remote_content_read_performed is False
        assert execution.remote_metadata_read_performed is False
        assert execution.processing_enqueued is False
        assert execution.ai_executed is False
        assert execution.claim_mutated is False
        assert execution.checkpoint_advanced is False
        assert execution.file_signature_validated is True
        assert execution.malware_scan_completed is True
        ensure_observation_refresh_admission_execution_integrity(db, execution)

        prior = db.get(Document, prior_document_id)
        new = db.get(Document, execution.new_document_id)
        assert prior is not None and new is not None
        assert prior.is_current is False
        assert new.is_current is True
        assert new.document_family_id == prior.document_family_id
        assert new.version_number == prior.version_number + 1
        assert new.processing_status == DocumentProcessingStatus.UPLOADED
        assert new.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert db.query(DocumentProcessingJob).count() == 0
        assert (
            db.query(Document)
            .filter(
                Document.claim_id == claim_id,
                Document.document_family_id == new.document_family_id,
                Document.is_current.is_(True),
                Document.deleted_at.is_(None),
            )
            .count()
            == 1
        )

        receipts = list(
            db.scalars(
                select(ExternalDocumentSourceObservationRefreshAdmissionReceipt).where(
                    ExternalDocumentSourceObservationRefreshAdmissionReceipt.execution_id
                    == execution.id
                )
            ).all()
        )
        assert len(receipts) == 1
        assert receipts[0].event_type == "admitted"

    assert len(read_adapter.calls) == provider_reads_before_admission
    assert security_calls == {"signature": 1, "malware": 1}
