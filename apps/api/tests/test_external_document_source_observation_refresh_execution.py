from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
    ensure_observation_refresh_execution_integrity,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_observation_review_decision import (
    _changed_result,
    _mfa_headers,
    _prepare_handoff,
    setup_function as _ag_setup,
    teardown_function as _ag_teardown,
)
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_successor_versioned_restaging import (
    _TReadAdapter,
    _T_BODY,
)


def setup_function() -> None:
    _ag_setup()


def teardown_function() -> None:
    _ag_teardown()


def _approved_refresh(monkeypatch: pytest.MonkeyPatch, suffix: str):
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        handoff_id,
        result_status,
        metadata_adapter,
    ) = _prepare_handoff(monkeypatch, suffix, _changed_result())
    assert result_status == "changed"
    with TestingSessionLocal() as db:
        decision, authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key=f"{suffix}-approve",
            decision_kind="approve_refresh",
            decision_reason="Human reviewer authorizes one exact changed-item content refresh.",
            now=datetime(2026, 9, 21, 0, 2, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert authorization is not None
        authorization_id = authorization.id
        decision_id = decision.id
    return (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        authorization_id,
        decision_id,
        metadata_adapter,
    )


def _refresh_io():
    changed_body = b"h" * (len(_T_BODY) + 41)
    read_adapter = _TReadAdapter(
        content=changed_body,
        version="f" * 64,
        media="application/pdf",
    )
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        read_adapter,
    )
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)
    return changed_body, read_adapter, store


def test_phase_ah_consumes_approved_refresh_once_and_replay_has_no_second_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        authorization_id,
        _decision_id,
        metadata_adapter,
    ) = _approved_refresh(monkeypatch, "ah-refresh-once")
    changed_body, read_adapter, store = _refresh_io()

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        execution, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=actor_id,
            request_key="ah-refresh-once",
            request_reason="Consume the approved changed-item refresh and stage only the exact item.",
            now=datetime(2026, 9, 21, 0, 3, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert execution.current_document_id == document_id
        assert execution.result_status == "staged_refresh_verified"
        assert execution.content_byte_count == len(changed_body)
        assert execution.content_version_token_hash == "f" * 64
        assert execution.remote_list_performed is False
        assert execution.exact_item_content_read_performed is True
        assert execution.document_mutated is False
        assert execution.evidence_admitted is False
        assert execution.processing_enqueued is False
        assert execution.ai_executed is False
        ensure_observation_refresh_execution_integrity(db, execution, verify_storage=True)
        execution_id = execution.id
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 1

    assert metadata_adapter.calls == 1
    assert read_adapter.calls == 1
    assert store.put_calls == 1

    with TestingSessionLocal() as db:
        replay, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=authorization_id,
            requested_by_id=actor_id,
            request_key="ah-refresh-once",
            request_reason="Consume the approved changed-item refresh and stage only the exact item.",
        )
        assert outcome == "replayed"
        assert replay.id == execution_id
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 1

    assert read_adapter.calls == 1
    assert store.put_calls == 1


def test_phase_ah_stale_current_document_fails_before_provider_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        authorization_id,
        _decision_id,
        _metadata_adapter,
    ) = _approved_refresh(monkeypatch, "ah-stale-current")
    _changed_body, read_adapter, store = _refresh_io()

    with TestingSessionLocal() as db:
        current = db.get(Document, document_id)
        assert current is not None
        current.is_current = False
        successor = Document(
            id=uuid4(),
            organization_id=current.organization_id,
            claim_id=current.claim_id,
            uploaded_by_id=current.uploaded_by_id,
            supersedes_document_id=current.id,
            document_family_id=current.document_family_id,
            filename="ah-stale-successor.pdf",
            original_filename="ah-stale-successor.pdf",
            mime_type=current.mime_type,
            file_size_bytes=current.file_size_bytes + 1,
            file_hash="7" * 64,
            storage_key="claims/ah-stale-successor.pdf",
            version_number=current.version_number + 1,
            is_current=True,
        )
        db.add(successor)
        db.commit()

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="canonical Evidence changed",
        ):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                requested_by_id=actor_id,
                request_key="ah-stale-current",
                request_reason="Attempt the approved refresh after canonical Evidence authority changed.",
            )
        db.rollback()
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0

    assert read_adapter.calls == 0
    assert store.put_calls == 0


def test_phase_ah_content_version_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        authorization_id,
        _decision_id,
        _metadata_adapter,
    ) = _approved_refresh(monkeypatch, "ah-version-mismatch")
    changed_body = b"h" * (len(_T_BODY) + 41)
    read_adapter = _TReadAdapter(
        content=changed_body,
        version="e" * 64,
        media="application/pdf",
    )
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        read_adapter,
    )
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="version no longer matches",
        ):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=authorization_id,
                requested_by_id=actor_id,
                request_key="ah-version-mismatch",
                request_reason="Reject content that no longer matches the approved changed observation.",
            )
        db.rollback()
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0

    assert read_adapter.calls == 1
    assert store.put_calls == 0


def test_phase_ah_endpoint_requires_current_mfa_and_returns_no_storage_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        _organization_id,
        _document_id,
        authorization_id,
        _decision_id,
        _metadata_adapter,
    ) = _approved_refresh(monkeypatch, "ah-api-mfa")
    _changed_body, read_adapter, _store = _refresh_io()
    endpoint = (
        f"/api/v1/external-document-sources/profiles/{profile_id}"
        f"/observation-refresh-authorizations/{authorization_id}/execute"
    )
    payload = {
        "request_key": "ah-api-mfa",
        "reason": "Consume one approved exact-item refresh through the human MFA boundary.",
    }

    from tests.test_external_document_source_discovery import _headers

    forbidden = client.post(endpoint, headers=_headers(actor_id), json=payload)
    assert forbidden.status_code == 403, forbidden.text

    allowed = client.post(endpoint, headers=_mfa_headers(actor_id), json=payload)
    assert allowed.status_code == 201, allowed.text
    body = allowed.json()
    assert body["authorization_id"] == str(authorization_id)
    assert body["result_status"] == "staged_refresh_verified"
    assert body["remote_list_performed"] is False
    assert body["evidence_admitted"] is False
    assert body["ai_executed"] is False
    assert "storage_object_key" not in body
    assert read_adapter.calls == 1
