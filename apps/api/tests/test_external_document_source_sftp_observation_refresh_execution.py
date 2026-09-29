from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
    ensure_observation_refresh_execution_integrity,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_sftp_file_content_proof import _FileReadAdapter
from tests.test_external_document_source_sftp_observation_review_decision import (
    _prepare_handoff,
    setup_function as _aa_setup,
    teardown_function as _aa_teardown,
)


def setup_function() -> None:
    _aa_setup()


def teardown_function() -> None:
    _aa_teardown()


def _approved_sftp_refresh(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
):
    (
        chain,
        metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        handoff_id,
        result_status,
    ) = _prepare_handoff(
        monkeypatch,
        f"sftp-phase-ab-{suffix}",
        mode="changed",
    )
    assert result_status == "changed"

    with TestingSessionLocal() as db:
        decision, authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key=f"sftp-phase-ab-{suffix}-approve",
            decision_kind="approve_refresh",
            decision_reason="Human reviewer authorizes one controlled SFTP changed-file refresh.",
            now=datetime(2026, 9, 29, 4, 0, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert decision.provider_kind == "sftp"
        assert decision.status == "refresh_authorized"
        assert authorization is not None
        assert authorization.provider_kind == "sftp"

        observation = db.get(
            ExternalDocumentSourceDueTickObservationExecution,
            decision.observation_execution_id,
        )
        assert observation is not None
        assert observation.result_status == "changed"
        assert observation.observed_byte_size is not None
        observed_size = observation.observed_byte_size
        authorization_id = authorization.id

    return (
        chain,
        metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        authorization_id,
        observed_size,
    )


def test_phase_ab_sftp_approve_refresh_executes_one_exact_read_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        chain,
        metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "once")

    changed_body = b"r" * observed_size
    read_adapter = _FileReadAdapter(content=changed_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

        execution, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=actor_id,
            request_key="sftp-phase-ab-execute-once",
            request_reason="Consume the approved SFTP changed-file refresh into governed quarantine.",
            now=datetime(2026, 9, 29, 4, 1, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert execution.provider_kind == "sftp"
        assert execution.result_status == "staged_refresh_verified"
        assert execution.content_byte_count == observed_size
        assert execution.exact_item_content_read_performed is True
        assert execution.remote_list_performed is False
        assert execution.remote_write_performed is False
        assert execution.remote_delete_performed is False
        assert execution.document_mutated is False
        assert execution.evidence_admitted is False
        assert execution.processing_enqueued is False
        assert execution.ai_executed is False

        ensure_observation_refresh_execution_integrity(
            db,
            execution,
            verify_storage=True,
        )
        execution_id = execution.id

        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 1

    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1

    request = read_adapter.calls[0]
    assert request.max_read_attempts == 1
    assert request.read_only_intent is True
    assert request.exact_file_only is True
    assert request.follow_symlinks is False
    assert not hasattr(request, "password")
    assert not hasattr(request, "private_key")

    with TestingSessionLocal() as db:
        replay, replay_outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=actor_id,
            request_key="sftp-phase-ab-execute-once",
            request_reason="Consume the approved SFTP changed-file refresh into governed quarantine.",
        )
        assert replay_outcome == "replayed"
        assert replay.id == execution_id

    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1
    assert len(chain["p_read_adapter"].calls) >= 1
    assert metadata_adapter.calls


def test_phase_ab_sftp_refresh_size_mismatch_fails_before_quarantine_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _chain,
        _metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "size-mismatch")

    mismatched_body = b"x" * (observed_size + 1)
    read_adapter = _FileReadAdapter(content=mismatched_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        with pytest.raises(ExternalDocumentSourceConflictError):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                requested_by_id=actor_id,
                request_key="sftp-phase-ab-size-mismatch",
                request_reason="This SFTP refresh must fail because the content size drifted.",
            )
        db.rollback()

    assert len(read_adapter.calls) == 1
    assert store.put_calls == 0
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 0
