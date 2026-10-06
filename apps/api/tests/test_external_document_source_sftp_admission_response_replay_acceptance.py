from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.modules.documents.models import Document
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
    ExternalDocumentSourceObservationRefreshAdmissionReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _EXEC_REASON,
    _authorized_refresh,
    _enable_clean_aj,
    setup_function as _aj_setup,
    teardown_function as _aj_teardown,
)


def setup_function() -> None:
    _aj_setup()


def teardown_function() -> None:
    _aj_teardown()


def test_ae_c_committed_admission_survives_response_finalization_failure_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        claim_id,
        _prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _authorized_refresh(monkeypatch, "rf")
    security_calls = _enable_clean_aj(monkeypatch)

    request_key = "ae-c-response-finalization-exec"
    with TestingSessionLocal() as db:
        real_refresh = db.refresh

        def _fail_execution_refresh(instance, *args, **kwargs):
            if isinstance(
                instance,
                ExternalDocumentSourceObservationRefreshAdmissionExecution,
            ):
                raise SQLAlchemyError("simulated response finalization failure")
            return real_refresh(instance, *args, **kwargs)

        monkeypatch.setattr(db, "refresh", _fail_execution_refresh)
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="committed but response finalization failed; replay the same request key",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key=request_key,
                execution_reason=_EXEC_REASON,
            )

    assert security_calls == {"signature": 1, "malware": 1}

    with TestingSessionLocal() as db:
        execution = (
            db.query(ExternalDocumentSourceObservationRefreshAdmissionExecution)
            .filter(
                ExternalDocumentSourceObservationRefreshAdmissionExecution.organization_id
                == organization_id,
                ExternalDocumentSourceObservationRefreshAdmissionExecution.request_key
                == request_key,
            )
            .one()
        )
        execution_id = execution.id
        new_document_id = execution.new_document_id
        durable_counts = (
            db.query(ExternalDocumentSourceObservationRefreshAdmissionExecution).count(),
            db.query(ExternalDocumentSourceObservationRefreshAdmissionReceipt).count(),
            db.query(Document).count(),
            db.query(Document)
            .filter(
                Document.claim_id == claim_id,
                Document.document_family_id == execution.document_family_id,
                Document.is_current.is_(True),
                Document.deleted_at.is_(None),
            )
            .count(),
        )
        assert durable_counts[-1] == 1

    with TestingSessionLocal() as db:
        replay, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=authorization_id,
            executed_by_id=actor_id,
            request_key=request_key,
            execution_reason=_EXEC_REASON,
        )
        assert outcome == "replayed"
        assert replay.id == execution_id
        assert replay.new_document_id == new_document_id
        assert (
            db.query(ExternalDocumentSourceObservationRefreshAdmissionExecution).count(),
            db.query(ExternalDocumentSourceObservationRefreshAdmissionReceipt).count(),
            db.query(Document).count(),
            db.query(Document)
            .filter(
                Document.claim_id == claim_id,
                Document.document_family_id == replay.document_family_id,
                Document.is_current.is_(True),
                Document.deleted_at.is_(None),
            )
            .count(),
        ) == durable_counts

    assert security_calls == {"signature": 1, "malware": 1}
