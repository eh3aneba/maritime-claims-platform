import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.modules.external_document_sources.sftp_evidence_admission_execution_service as admission_service
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_evidence_admission_execution_models import (
    ExternalDocumentSourceSftpEvidenceAdmissionExecution,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_evidence_admission_execution import (
    _authorized_phase_s,
    _enable_clean_admission,
    _execute,
    setup_function as _t_setup,
    teardown_function as _t_teardown,
)


def setup_function() -> None:
    _t_setup()


def teardown_function() -> None:
    _t_teardown()


def test_phase_t_post_commit_refresh_failure_preserves_canonical_evidence_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, adapter, _r_body, _claim_id, authorization = _authorized_phase_s(
        "sftp-phase-t-post-commit"
    )
    _enable_clean_admission(monkeypatch)

    original_refresh = Session.refresh

    def _fail_execution_refresh(self, instance, *args, **kwargs):
        if isinstance(instance, ExternalDocumentSourceSftpEvidenceAdmissionExecution):
            raise SQLAlchemyError("simulated post-commit refresh failure")
        return original_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", _fail_execution_refresh)
    response = _execute(
        chain,
        authorization["id"],
        key="t-post-commit-execution",
    )
    assert response.status_code == 409, response.text
    assert "committed" in response.json()["detail"].lower()

    metadata_calls_after_commit = len(adapter.calls)
    storage_gets_after_commit = chain["p_store"].get_calls

    with TestingSessionLocal() as db:
        execution = db.query(
            ExternalDocumentSourceSftpEvidenceAdmissionExecution
        ).one()
        document = db.get(Document, execution.document_id)
        assert document is not None
        canonical_key = document.storage_key
        execution_id = execution.id

    assert admission_service._storage().path_for(canonical_key).is_file()

    monkeypatch.setattr(Session, "refresh", original_refresh)
    replay = _execute(
        chain,
        authorization["id"],
        key="t-post-commit-execution",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == str(execution_id)
    assert len(adapter.calls) == metadata_calls_after_commit
    assert chain["p_store"].get_calls == storage_gets_after_commit
