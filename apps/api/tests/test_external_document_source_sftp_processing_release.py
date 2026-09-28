from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.external_document_sources.processing_release_models import (
    ExternalDocumentSourceProcessingRelease,
)
from app.modules.external_document_sources.processing_release_service import (
    get_active_processing_release_for_document,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_evidence_admission_authorization_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
)
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobType
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_processing_release import (
    _RELEASE_REASON,
    _REVOKE_REASON,
    _grant,
    _revoke,
)
from tests.test_external_document_source_profiles import _headers
from tests.test_external_document_source_sftp_evidence_admission_execution import (
    _authorized_phase_s,
    _enable_clean_admission,
    _execute,
)
from tests.test_external_document_source_sftp_evidence_family_binding import (
    _bind,
    setup_function as _u_setup,
    teardown_function as _u_teardown,
)


def setup_function() -> None:
    _u_setup()


def teardown_function() -> None:
    _u_teardown()


def _bound_sftp(monkeypatch: pytest.MonkeyPatch, seed: str):
    chain, adapter, _r_body, claim_id, authorization = _authorized_phase_s(seed)
    _enable_clean_admission(monkeypatch)
    admitted = _execute(
        chain,
        authorization["id"],
        key=f"{seed}-t-admit",
    )
    assert admitted.status_code == 201, admitted.text
    execution = admitted.json()

    binding = _bind(
        chain,
        execution["id"],
        key=f"{seed}-u-bind",
    )
    assert binding.status_code == 201, binding.text
    assert binding.json()["provider_kind"] == "sftp"
    return chain, adapter, claim_id, authorization, execution, binding.json()


def test_phase_v_generic_release_unlocks_sftp_evidence_without_widening_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, claim_id, _authorization, execution, binding = _bound_sftp(
        monkeypatch,
        "sftp-phase-v-release",
    )
    actor_id = chain["requester_id"]
    document_id = UUID(execution["document_id"])

    blocked = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert blocked.status_code == 409, blocked.text

    provider_calls_before = len(adapter.calls)
    staged_heads_before = chain["p_store"].head_calls
    staged_gets_before = chain["p_store"].get_calls
    remote_reads_before = len(chain["p_read_adapter"].calls)

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-v-sftp-release",
        reason=_RELEASE_REASON,
    )
    assert release.status_code == 201, release.text
    body = release.json()
    assert body["status"] == "active"
    assert body["binding_id"] == binding["id"]
    assert body["document_family_id"] == execution["document_id"]
    assert body["document_id"] == execution["document_id"]
    assert body["document_version_number"] == 1
    assert body["local_text_processing_authorized"] is True
    assert body["ai_processing_authorized"] is False
    assert body["provider_io_performed"] is False
    assert body["storage_io_performed"] is False
    assert body["document_mutated"] is False
    assert body["processing_enqueued"] is False
    assert body["claim_mutated"] is False

    assert len(adapter.calls) == provider_calls_before
    assert chain["p_store"].head_calls == staged_heads_before
    assert chain["p_store"].get_calls == staged_gets_before
    assert len(chain["p_read_adapter"].calls) == remote_reads_before

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.processing_status == DocumentProcessingStatus.UPLOADED
        assert (
            db.query(DocumentProcessingJob)
            .filter(DocumentProcessingJob.document_id == document_id)
            .count()
            == 0
        )
        release_row = db.get(
            ExternalDocumentSourceProcessingRelease,
            UUID(body["id"]),
        )
        assert release_row is not None
        assert release_row.ai_processing_authorized is False

    replay = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-v-sftp-release",
        reason=_RELEASE_REASON,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    assert len(adapter.calls) == provider_calls_before
    assert chain["p_store"].get_calls == staged_gets_before

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["processing_release_required"] is False
    assert summary.json()["processing_release_status"] == "active"

    retry = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["job_type"] == ProcessingJobType.EXTRACT_TEXT.value


def test_phase_v_generic_revocation_reblocks_sftp_evidence_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, claim_id, _authorization, execution, _binding = _bound_sftp(
        monkeypatch,
        "sftp-phase-v-revoke",
    )
    actor_id = chain["requester_id"]
    document_id = UUID(execution["document_id"])

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-v-sftp-release-before-revoke",
        reason=_RELEASE_REASON,
    )
    assert release.status_code == 201, release.text

    provider_calls_before = len(adapter.calls)
    staged_gets_before = chain["p_store"].get_calls

    revoked = _revoke(
        claim_id,
        document_id,
        actor_id,
        key="phase-v-sftp-revoke",
        reason=_REVOKE_REASON,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["ai_processing_authorized"] is False
    assert revoked.json()["provider_io_performed"] is False
    assert revoked.json()["storage_io_performed"] is False
    assert revoked.json()["processing_enqueued"] is False

    assert len(adapter.calls) == provider_calls_before
    assert chain["p_store"].get_calls == staged_gets_before

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["processing_release_required"] is True
    assert summary.json()["processing_release_status"] == "revoked"

    blocked = client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing/retry",
        headers=_headers(actor_id),
    )
    assert blocked.status_code == 409, blocked.text

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        assert document.processing_status == DocumentProcessingStatus.UPLOADED
        assert (
            db.query(DocumentProcessingJob)
            .filter(DocumentProcessingJob.document_id == document_id)
            .count()
            == 0
        )


def test_phase_v_release_fails_closed_when_sftp_binding_lineage_is_tampered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, _adapter, claim_id, authorization, execution, _binding = _bound_sftp(
        monkeypatch,
        "sftp-phase-v-tamper",
    )
    actor_id = chain["requester_id"]
    document_id = UUID(execution["document_id"])

    release = _grant(
        claim_id,
        document_id,
        actor_id,
        key="phase-v-sftp-release-tamper",
        reason=_RELEASE_REASON,
    )
    assert release.status_code == 201, release.text

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpEvidenceAdmissionAuthorization,
            UUID(authorization["id"]),
        )
        assert row is not None
        row.authorized_relative_path_hash = "e" * 64
        db.commit()

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/processing",
        headers=_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["processing_release_required"] is True
    assert summary.json()["processing_release_status"] == "required"

    with TestingSessionLocal() as db:
        document = db.get(Document, document_id)
        assert document is not None
        with pytest.raises(ExternalDocumentSourceConflictError):
            get_active_processing_release_for_document(
                db,
                document=document,
            )
