from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import ExactItemMetadataResult
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
    ensure_observation_refresh_admission_authorization_integrity,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
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
    ExternalDocumentSourceNotFoundError,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_generation_3_change_detection import (
    _baseline_projection,
)
from tests.test_external_document_source_observation_refresh_execution import (
    _approved_refresh,
    _refresh_io,
    setup_function as _ah_setup,
    teardown_function as _ah_teardown,
)
from tests.test_external_document_source_observation_review_decision import (
    _mfa_headers,
    _prepare_handoff,
)
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_successor_versioned_restaging import (
    _TReadAdapter,
    _T_BODY,
)


_AUTH_REASON = (
    "Authorize the exact verified observation refresh for later canonical "
    "N+1 Evidence admission under a separate human authority boundary."
)


def setup_function() -> None:
    _ah_setup()


def teardown_function() -> None:
    _ah_teardown()


def _completed_refresh(monkeypatch: pytest.MonkeyPatch, suffix: str):
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        refresh_authorization_id,
        _decision_id,
        metadata_adapter,
    ) = _approved_refresh(monkeypatch, suffix)
    _body, read_adapter, store = _refresh_io()
    with TestingSessionLocal() as db:
        refresh, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key=f"{suffix}-refresh",
            request_reason=(
                "Consume the approved changed-item refresh and stage the exact "
                "remote content before any Evidence admission authority exists."
            ),
            now=datetime(2026, 9, 21, 1, 0, tzinfo=UTC),
        )
        assert outcome == "completed"
        refresh_id = refresh.id
    return (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        refresh_id,
        metadata_adapter,
        read_adapter,
        store,
    )


def test_phase_ai_authorizes_exact_completed_refresh_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        refresh_id,
        metadata_adapter,
        read_adapter,
        store,
    ) = _completed_refresh(monkeypatch, "ai-success")

    provider_calls_before = (metadata_adapter.calls, read_adapter.calls)
    storage_calls_before = (store.put_calls, store.head_calls, store.get_calls)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

        authorization, outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key="ai-success-auth",
            authorization_reason=_AUTH_REASON,
            now=datetime(2026, 9, 21, 1, 1, tzinfo=UTC),
        )
        assert outcome == "authorized"
        assert authorization.refresh_execution_id == refresh_id
        assert authorization.expected_prior_document_id == document_id
        assert authorization.status == "authorized"
        assert authorization.refresh_execution_verified is True
        assert authorization.durable_family_binding_verified is True
        assert authorization.stable_source_identity_verified is True
        assert authorization.current_document_verified is True
        assert authorization.staged_content_proof_verified is True
        assert authorization.human_authorization_recorded is True
        assert authorization.provider_client_constructed is False
        assert authorization.oauth_token_acquired is False
        assert authorization.remote_metadata_read_performed is False
        assert authorization.remote_content_read_performed is False
        assert authorization.storage_read_performed is False
        assert authorization.storage_write_performed is False
        assert authorization.file_signature_validated is False
        assert authorization.malware_scan_completed is False
        assert authorization.document_mutated is False
        assert authorization.evidence_admitted is False
        assert authorization.processing_enqueued is False
        assert authorization.ai_executed is False
        assert authorization.claim_mutated is False
        assert authorization.checkpoint_advanced is False
        ensure_observation_refresh_admission_authorization_integrity(
            db,
            authorization,
        )
        authorization_id = authorization.id

        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization
            ).count()
            == 1
        )
        receipts = list(
            db.scalars(
                select(
                    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt
                ).where(
                    ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt.authorization_id
                    == authorization.id
                )
            ).all()
        )
        assert len(receipts) == 1
        assert receipts[0].event_type == "authorized"

    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before
    assert (store.put_calls, store.head_calls, store.get_calls) == storage_calls_before

    with TestingSessionLocal() as db:
        replay, outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key="ai-success-auth",
            authorization_reason=_AUTH_REASON,
        )
        assert outcome == "replayed"
        assert replay.id == authorization_id
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization
            ).count()
            == 1
        )
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorizationReceipt
            ).count()
            == 1
        )

    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before
    assert (store.put_calls, store.head_calls, store.get_calls) == storage_calls_before


def test_phase_ai_altered_replay_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        refresh_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _completed_refresh(monkeypatch, "ai-altered-replay")

    with TestingSessionLocal() as db:
        first, outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key="ai-altered-replay-auth",
            authorization_reason=_AUTH_REASON,
        )
        assert outcome == "authorized"
        first_id = first.id

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="request_key is already bound",
        ):
            authorize_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                refresh_execution_id=refresh_id,
                authorized_by_id=actor_id,
                request_key="ai-altered-replay-auth",
                authorization_reason=(
                    "A materially altered reason must not replay the prior "
                    "human admission authorization."
                ),
            )
        db.rollback()
        rows = db.query(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization
        ).all()
        assert len(rows) == 1
        assert rows[0].id == first_id


def test_phase_ai_stale_current_document_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        refresh_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _completed_refresh(monkeypatch, "ai-stale-current")

    with TestingSessionLocal() as db:
        prior = db.get(Document, document_id)
        assert prior is not None
        prior.is_current = False
        successor = Document(
            id=uuid4(),
            organization_id=prior.organization_id,
            claim_id=prior.claim_id,
            uploaded_by_id=prior.uploaded_by_id,
            supersedes_document_id=prior.id,
            document_family_id=prior.document_family_id,
            filename="ai-stale-successor.pdf",
            original_filename="ai-stale-successor.pdf",
            mime_type=prior.mime_type,
            file_size_bytes=prior.file_size_bytes + 2,
            file_hash="6" * 64,
            storage_key="claims/ai-stale-successor.pdf",
            version_number=prior.version_number + 1,
            is_current=True,
        )
        db.add(successor)
        db.commit()

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="current Document changed after authorization",
        ):
            authorize_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                refresh_execution_id=refresh_id,
                authorized_by_id=actor_id,
                request_key="ai-stale-current-auth",
                authorization_reason=_AUTH_REASON,
            )
        db.rollback()
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization
            ).count()
            == 0
        )


def test_phase_ai_tampered_refresh_proof_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        refresh_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _completed_refresh(monkeypatch, "ai-tampered-refresh")

    with TestingSessionLocal() as db:
        refresh = db.get(ExternalDocumentSourceObservationRefreshExecution, refresh_id)
        assert refresh is not None
        refresh.content_proof_hash = "0" * 64
        db.commit()

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="cryptographic integrity failed",
        ):
            authorize_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                refresh_execution_id=refresh_id,
                authorized_by_id=actor_id,
                request_key="ai-tampered-refresh-auth",
                authorization_reason=_AUTH_REASON,
            )
        db.rollback()
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization
            ).count()
            == 0
        )


def test_phase_ai_same_content_refresh_cannot_be_authorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _baseline_projection()
    changed_only_by_version = baseline.__class__(
        provider_item_id=baseline.provider_item_id,
        parent_item_id=baseline.parent_item_id,
        item_kind=baseline.item_kind,
        display_name=baseline.display_name,
        mime_type_class=baseline.mime_type_class,
        byte_size=baseline.byte_size,
        modified_at=datetime(2026, 9, 21, 1, 10, tzinfo=UTC),
        version_token_hash="f" * 64,
    )
    (
        actor_id,
        profile_id,
        organization_id,
        _document_id,
        handoff_id,
        result_status,
        _metadata_adapter,
    ) = _prepare_handoff(
        monkeypatch,
        "ai-same-content",
        ExactItemMetadataResult(found=True, item=changed_only_by_version),
    )
    assert result_status == "changed"

    with TestingSessionLocal() as db:
        _decision, refresh_authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="ai-same-content-approve",
            decision_kind="approve_refresh",
            decision_reason=(
                "Human reviewer approves one exact refresh where only the "
                "provider version marker changed."
            ),
            now=datetime(2026, 9, 21, 1, 11, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert refresh_authorization is not None
        refresh_authorization_id = refresh_authorization.id

    read_adapter = _TReadAdapter(
        content=_T_BODY,
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

    with TestingSessionLocal() as db:
        refresh, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ai-same-content-refresh",
            request_reason=(
                "Stage the exact approved item even though its bytes remain "
                "identical to the current canonical Evidence."
            ),
            now=datetime(2026, 9, 21, 1, 12, tzinfo=UTC),
        )
        assert outcome == "completed"
        refresh_id = refresh.id

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="identical to the current canonical Evidence|already exists in Claim Evidence",
        ):
            authorize_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                refresh_execution_id=refresh_id,
                authorized_by_id=actor_id,
                request_key="ai-same-content-auth",
                authorization_reason=_AUTH_REASON,
            )
        db.rollback()
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization
            ).count()
            == 0
        )


def test_phase_ai_cross_tenant_refresh_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _actor_id,
        profile_id,
        _organization_id,
        _document_id,
        refresh_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _completed_refresh(monkeypatch, "ai-cross-tenant")
    other_org, other_admin, _other_approver = _seed_tenant("ai-cross-tenant-other")

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceNotFoundError,
            match="Observation refresh execution not found",
        ):
            authorize_observation_refresh_admission(
                db,
                organization_id=other_org,
                profile_id=profile_id,
                refresh_execution_id=refresh_id,
                authorized_by_id=other_admin,
                request_key="ai-cross-tenant-auth",
                authorization_reason=_AUTH_REASON,
            )
        db.rollback()


def test_phase_ai_endpoint_requires_current_mfa_and_hides_raw_storage_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        _organization_id,
        _document_id,
        refresh_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _completed_refresh(monkeypatch, "ai-api-mfa")

    endpoint = (
        f"/api/v1/external-document-sources/profiles/{profile_id}"
        f"/observation-refresh-executions/{refresh_id}/admission-authorizations"
    )
    payload = {
        "request_key": "ai-api-mfa-auth",
        "reason": _AUTH_REASON,
    }

    forbidden = client.post(
        endpoint,
        headers=_headers(actor_id),
        json=payload,
    )
    assert forbidden.status_code == 403, forbidden.text
    assert "mfa" in forbidden.text.lower()

    caller_controlled = client.post(
        endpoint,
        headers=_mfa_headers(actor_id),
        json={
            **payload,
            "storage_object_key": "caller-controlled",
            "processing_authorized": True,
        },
    )
    assert caller_controlled.status_code == 422, caller_controlled.text

    allowed = client.post(
        endpoint,
        headers=_mfa_headers(actor_id),
        json=payload,
    )
    assert allowed.status_code == 201, allowed.text
    body = allowed.json()
    assert body["refresh_execution_id"] == str(refresh_id)
    assert body["status"] == "authorized"
    assert body["document_mutated"] is False
    assert body["evidence_admitted"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert "storage_object_key" not in body
    assert body["storage_object_key_hash"]

    receipt = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{profile_id}"
            f"/observation-refresh-admission-authorizations/{body['id']}/receipts"
        ),
        headers=_mfa_headers(actor_id),
    )
    assert receipt.status_code == 200, receipt.text
    rows = receipt.json()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "authorized"
    assert "storage_object_key" not in rows[0]
