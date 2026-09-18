import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.modules.external_document_sources.evidence_admission_execution_service as admission_service
from app.modules.documents.models import Document
from app.modules.external_document_sources.evidence_admission_execution_models import (
    ExternalDocumentSourceEvidenceAdmissionExecution,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_evidence_admission_authorization import (
    _authorize,
    _seed_claim,
    _unchanged_phase_v,
    setup_function as _phase_w_setup,
    teardown_function as _phase_w_teardown,
)
from tests.test_external_document_source_evidence_admission_execution import (
    _enable_clean_admission,
    _execute,
)


def setup_function() -> None:
    _phase_w_setup()


def teardown_function() -> None:
    _phase_w_teardown()


def test_phase_x_post_commit_refresh_failure_preserves_canonical_evidence_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream, metadata_adapter, observation = _unchanged_phase_v()
    actor_id = upstream[0]
    profile_id = upstream[1]
    store = upstream[14]
    claim_id = _seed_claim(actor_id, "x-post-commit")
    authorization = _authorize(
        profile_id,
        observation["id"],
        claim_id,
        actor_id,
        key="phase-x-auth-post-commit",
    )
    assert authorization.status_code == 201, authorization.text
    authorization_id = authorization.json()["id"]
    _enable_clean_admission(monkeypatch)

    original_refresh = Session.refresh

    def _fail_execution_refresh(self, instance, *args, **kwargs):
        if isinstance(instance, ExternalDocumentSourceEvidenceAdmissionExecution):
            raise SQLAlchemyError("simulated post-commit refresh failure")
        return original_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", _fail_execution_refresh)
    response = _execute(
        profile_id,
        authorization_id,
        actor_id,
        key="phase-x-post-commit-execution",
    )
    assert response.status_code == 409, response.text
    assert "committed" in response.json()["detail"].lower()

    metadata_calls_after_commit = metadata_adapter.calls
    storage_gets_after_commit = store.get_calls

    with TestingSessionLocal() as db:
        execution = db.query(ExternalDocumentSourceEvidenceAdmissionExecution).one()
        document = db.get(Document, execution.document_id)
        assert document is not None
        canonical_key = document.storage_key
        execution_id = execution.id

    # A response-refresh failure happens after the DB transaction committed. The
    # canonical Evidence bytes must therefore remain present; deleting them would
    # leave a committed Document pointing at missing custody.
    assert admission_service._storage().path_for(canonical_key).is_file()

    monkeypatch.setattr(Session, "refresh", original_refresh)
    replay = _execute(
        profile_id,
        authorization_id,
        actor_id,
        key="phase-x-post-commit-execution",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == str(execution_id)
    assert metadata_adapter.calls == metadata_calls_after_commit
    assert store.get_calls == storage_gets_after_commit
