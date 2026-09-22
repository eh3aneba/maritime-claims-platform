from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import app.modules.external_document_sources.observation_refresh_admission_execution_service as aj_service
from app.modules.documents.malware import (
    MalwareScannerError,
    MalwareScanResult,
    MalwareScanVerdict,
)
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
    ExternalDocumentSourceObservationRefreshAdmissionReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    ensure_observation_refresh_admission_execution_integrity,
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_observation_refresh_admission_authorization import (
    _AUTH_REASON as _AI_AUTH_REASON,
    _completed_refresh,
    setup_function as _ai_setup,
    teardown_function as _ai_teardown,
)
from tests.test_external_document_source_observation_review_decision import (
    _mfa_headers,
)


_EXEC_REASON = (
    "Admit the exact separately authorized verified observation refresh as "
    "the next immutable canonical Evidence version after fresh security checks."
)


def setup_function() -> None:
    _ai_setup()


def teardown_function() -> None:
    _ai_teardown()


def _authorized_refresh(monkeypatch: pytest.MonkeyPatch, suffix: str):
    (
        actor_id,
        profile_id,
        organization_id,
        document_id,
        refresh_id,
        metadata_adapter,
        read_adapter,
        store,
    ) = _completed_refresh(monkeypatch, suffix)

    with TestingSessionLocal() as db:
        authorization, outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key=f"{suffix}-ai-auth",
            authorization_reason=_AI_AUTH_REASON,
            now=datetime(2026, 9, 22, 1, 0, tzinfo=UTC),
        )
        assert outcome == "authorized"
        authorization_id = authorization.id
        binding_id = authorization.binding_id
        claim_id = authorization.claim_id

    return (
        actor_id,
        profile_id,
        organization_id,
        claim_id,
        document_id,
        refresh_id,
        authorization_id,
        binding_id,
        metadata_adapter,
        read_adapter,
        store,
    )


def _enable_clean_aj(monkeypatch: pytest.MonkeyPatch):
    calls = {"signature": 0, "malware": 0}
    monkeypatch.setattr(aj_service.settings, "malware_scan_enabled", True)

    def _signature(*_args, **_kwargs):
        calls["signature"] += 1

    def _scan(*_args, **_kwargs):
        calls["malware"] += 1
        return MalwareScanResult(verdict=MalwareScanVerdict.CLEAN)

    monkeypatch.setattr(aj_service, "validate_file_signature", _signature)
    monkeypatch.setattr(aj_service, "scan_file", _scan)
    return calls


def test_phase_aj_admits_exact_authorized_refresh_without_provider_io_or_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        metadata_adapter,
        read_adapter,
        store,
    ) = _authorized_refresh(monkeypatch, "aj-success")
    security_calls = _enable_clean_aj(monkeypatch)

    provider_calls_before = (metadata_adapter.calls, read_adapter.calls)
    staged_calls_before = (store.put_calls, store.head_calls, store.get_calls)

    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=authorization_id,
            executed_by_id=actor_id,
            request_key="aj-success-exec",
            execution_reason=_EXEC_REASON,
        )
        assert outcome == "admitted"
        assert execution.status == "admitted"
        assert execution.prior_document_id == prior_document_id
        assert execution.prior_version_number == 1
        assert execution.new_version_number == 2
        assert execution.authorization_verified is True
        assert execution.refresh_execution_verified is True
        assert execution.staged_storage_read_performed is True
        assert execution.staged_content_integrity_verified is True
        assert execution.file_signature_validated is True
        assert execution.malware_scan_completed is True
        assert execution.canonical_document_write_completed is True
        assert execution.refreshed_version_admitted is True
        assert execution.provider_client_constructed is False
        assert execution.oauth_token_acquired is False
        assert execution.remote_list_performed is False
        assert execution.remote_metadata_read_performed is False
        assert execution.remote_content_read_performed is False
        assert execution.processing_enqueued is False
        assert execution.ai_executed is False
        assert execution.claim_mutated is False
        assert execution.checkpoint_advanced is False
        ensure_observation_refresh_admission_execution_integrity(db, execution)
        execution_id = execution.id
        new_document_id = execution.new_document_id

        prior = db.get(Document, prior_document_id)
        new = db.get(Document, new_document_id)
        assert prior is not None and new is not None
        assert prior.is_current is False
        assert prior.superseded_by_id == actor_id
        assert new.is_current is True
        assert new.version_number == 2
        assert new.supersedes_document_id == prior.id
        assert new.document_family_id == prior.document_family_id
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

    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before
    assert store.put_calls == staged_calls_before[0]
    assert store.head_calls == staged_calls_before[1] + 1
    assert store.get_calls == staged_calls_before[2] + 1
    assert security_calls == {"signature": 1, "malware": 1}

    with TestingSessionLocal() as db:
        replay, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=authorization_id,
            executed_by_id=actor_id,
            request_key="aj-success-exec",
            execution_reason=_EXEC_REASON,
        )
        assert outcome == "replayed"
        assert replay.id == execution_id
        assert replay.new_document_id == new_document_id
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 1
        )
        assert db.query(DocumentProcessingJob).count() == 0

    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before
    assert store.head_calls == staged_calls_before[1] + 1
    assert store.get_calls == staged_calls_before[2] + 1
    assert security_calls == {"signature": 1, "malware": 1}

    summary = client.get(
        f"/api/v1/claims/{claim_id}/documents/{new_document_id}/processing",
        headers=_mfa_headers(actor_id),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["processing_release_required"] is True
    assert summary.json()["processing_release_status"] == "required"


def test_phase_aj_altered_replay_conflicts_without_second_security_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        _prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        store,
    ) = _authorized_refresh(monkeypatch, "aj-altered")
    security_calls = _enable_clean_aj(monkeypatch)

    with TestingSessionLocal() as db:
        first, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=authorization_id,
            executed_by_id=actor_id,
            request_key="aj-altered-exec",
            execution_reason=_EXEC_REASON,
        )
        assert outcome == "admitted"
        first_id = first.id

    reads_after_first = (store.head_calls, store.get_calls)
    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="already consumed",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-altered-other",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()
        rows = db.query(
            ExternalDocumentSourceObservationRefreshAdmissionExecution
        ).all()
        assert len(rows) == 1
        assert rows[0].id == first_id

    assert (store.head_calls, store.get_calls) == reads_after_first
    assert security_calls == {"signature": 1, "malware": 1}


def test_phase_aj_stale_current_document_fails_before_staged_storage_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        store,
    ) = _authorized_refresh(monkeypatch, "aj-stale")
    _enable_clean_aj(monkeypatch)

    with TestingSessionLocal() as db:
        prior = db.get(Document, prior_document_id)
        assert prior is not None
        prior.is_current = False
        prior.superseded_by_id = actor_id
        prior.superseded_at = datetime(2026, 9, 22, 2, 0, tzinfo=UTC)
        successor = Document(
            id=uuid4(),
            organization_id=prior.organization_id,
            claim_id=prior.claim_id,
            uploaded_by_id=actor_id,
            supersedes_document_id=prior.id,
            document_family_id=prior.document_family_id,
            version_number=prior.version_number + 1,
            is_current=True,
            replacement_reason="Simulate a competing canonical Evidence transition.",
            source_admission_note="Simulated competing current version.",
            filename=prior.filename,
            original_filename=prior.original_filename,
            document_type=prior.document_type,
            mime_type=prior.mime_type,
            file_size_bytes=prior.file_size_bytes + 1,
            file_hash="7" * 64,
            storage_key=f"test/aj-stale/{uuid4().hex}.pdf",
            confidentiality_level=prior.confidentiality_level,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
            malware_scanned_at=datetime(2026, 9, 22, 2, 0, tzinfo=UTC),
        )
        db.add(successor)
        db.commit()

    staged_calls_before = (store.head_calls, store.get_calls)
    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="current Document changed after authorization",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-stale-exec",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 0
        )
    assert (store.head_calls, store.get_calls) == staged_calls_before


def test_phase_aj_tampered_staged_bytes_fail_closed_before_document_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        store,
    ) = _authorized_refresh(monkeypatch, "aj-storage-tamper")
    _enable_clean_aj(monkeypatch)

    with TestingSessionLocal() as db:
        refresh = db.get(ExternalDocumentSourceObservationRefreshExecution, refresh_id)
        assert refresh is not None
        staged_key = refresh.storage_object_key
    store.objects[staged_key] = b"tampered-observation-refresh-bytes"

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="staged object metadata drifted|integrity verification failed",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-storage-tamper-exec",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()
        prior = db.get(Document, prior_document_id)
        assert prior is not None and prior.is_current is True
        assert db.query(Document).count() == 1
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 0
        )


def test_phase_aj_malware_nonclean_rolls_back_canonical_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _authorized_refresh(monkeypatch, "aj-malware")

    monkeypatch.setattr(aj_service.settings, "malware_scan_enabled", True)
    monkeypatch.setattr(
        aj_service,
        "validate_file_signature",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        aj_service,
        "scan_file",
        lambda *_args, **_kwargs: MalwareScanResult(
            verdict=MalwareScanVerdict.INFECTED,
            threat_name="test-only",
        ),
    )

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="Malware was detected",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-malware-exec",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()
        prior = db.get(Document, prior_document_id)
        assert prior is not None and prior.is_current is True
        assert db.query(Document).count() == 1
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 0
        )


def test_phase_aj_cross_tenant_authorization_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _actor_id,
        profile_id,
        _organization_id,
        _claim_id,
        _prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _authorized_refresh(monkeypatch, "aj-cross-tenant")
    other_org, other_admin, _other_approver = _seed_tenant("aj-cross-tenant-other")

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceNotFoundError,
            match="authorization not found",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=other_org,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=other_admin,
                request_key="aj-cross-tenant-exec",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()


def test_phase_aj_endpoint_requires_current_mfa_and_rejects_caller_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        _organization_id,
        _claim_id,
        _prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        metadata_adapter,
        read_adapter,
        store,
    ) = _authorized_refresh(monkeypatch, "aj-api")
    _enable_clean_aj(monkeypatch)

    endpoint = (
        f"/api/v1/external-document-sources/profiles/{profile_id}"
        f"/evidence-family-bindings/{binding_id}"
        f"/observation-refresh-admissions/{authorization_id}"
    )
    payload = {
        "request_key": "aj-api-exec",
        "reason": _EXEC_REASON,
    }
    provider_calls_before = (metadata_adapter.calls, read_adapter.calls)
    staged_calls_before = (store.head_calls, store.get_calls)

    no_mfa = client.post(
        endpoint,
        headers=_headers(actor_id),
        json=payload,
    )
    assert no_mfa.status_code == 403, no_mfa.text

    injected = client.post(
        endpoint,
        headers=_mfa_headers(actor_id),
        json={
            **payload,
            "storage_object_key": "caller-controlled",
            "document_id": str(uuid4()),
            "malware_scan_verdict": "clean",
            "processing_authorized": True,
            "ai_authorized": True,
        },
    )
    assert injected.status_code == 422, injected.text
    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before
    assert (store.head_calls, store.get_calls) == staged_calls_before

    allowed = client.post(
        endpoint,
        headers=_mfa_headers(actor_id),
        json=payload,
    )
    assert allowed.status_code == 201, allowed.text
    body = allowed.json()
    assert body["status"] == "admitted"
    assert body["authorization_id"] == str(authorization_id)
    assert body["provider_client_constructed"] is False
    assert body["remote_metadata_read_performed"] is False
    assert body["remote_content_read_performed"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert "storage_object_key" not in body
    assert "canonical_storage_key" not in body
    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before


def test_phase_aj_tampered_ai_authorization_fails_before_staged_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        store,
    ) = _authorized_refresh(monkeypatch, "aj-auth-tamper")
    _enable_clean_aj(monkeypatch)

    with TestingSessionLocal() as db:
        authorization = db.get(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
            authorization_id,
        )
        assert authorization is not None
        authorization.authorization_hash = "0" * 64
        db.commit()

    staged_calls_before = (store.head_calls, store.get_calls)
    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="cryptographic integrity failed",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-auth-tamper-exec",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()
        prior = db.get(Document, prior_document_id)
        assert prior is not None and prior.is_current is True
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 0
        )
    assert (store.head_calls, store.get_calls) == staged_calls_before


@pytest.mark.parametrize("failure_kind", ["signature", "scanner"])
def test_phase_aj_security_verification_failures_leave_prior_current(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _authorized_refresh(monkeypatch, f"aj-{failure_kind}")
    monkeypatch.setattr(aj_service.settings, "malware_scan_enabled", True)

    if failure_kind == "signature":
        def _bad_signature(*_args, **_kwargs):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="test signature mismatch",
            )

        monkeypatch.setattr(
            aj_service,
            "validate_file_signature",
            _bad_signature,
        )
        monkeypatch.setattr(
            aj_service,
            "scan_file",
            lambda *_args, **_kwargs: MalwareScanResult(
                verdict=MalwareScanVerdict.CLEAN
            ),
        )
        expected = "do not match the validated file type"
    else:
        monkeypatch.setattr(
            aj_service,
            "validate_file_signature",
            lambda *_args, **_kwargs: None,
        )

        def _scanner_error(*_args, **_kwargs):
            raise MalwareScannerError("test scanner unavailable")

        monkeypatch.setattr(aj_service, "scan_file", _scanner_error)
        expected = "could not return an authoritative verdict"

    with TestingSessionLocal() as db:
        with pytest.raises(ExternalDocumentSourceConflictError, match=expected):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key=f"aj-{failure_kind}-exec",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()
        prior = db.get(Document, prior_document_id)
        assert prior is not None and prior.is_current is True
        assert db.query(Document).count() == 1
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 0
        )


def test_phase_aj_database_failure_rolls_back_prior_and_cleans_promoted_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        _claim_id,
        prior_document_id,
        _refresh_id,
        authorization_id,
        binding_id,
        _metadata_adapter,
        _read_adapter,
        _store,
    ) = _authorized_refresh(monkeypatch, "aj-db-rollback")
    _enable_clean_aj(monkeypatch)

    original_establish = aj_service._establish_next_document_version
    original_cleanup = aj_service._cleanup_local_storage
    cleanup_calls: list[dict] = []

    def _establish_then_fail(*args, **kwargs):
        original_establish(*args, **kwargs)
        raise SQLAlchemyError("test post-version-insert failure")

    def _cleanup_spy(**kwargs):
        cleanup_calls.append(dict(kwargs))
        return original_cleanup(**kwargs)

    monkeypatch.setattr(
        aj_service,
        "_establish_next_document_version",
        _establish_then_fail,
    )
    monkeypatch.setattr(
        aj_service,
        "_cleanup_local_storage",
        _cleanup_spy,
    )

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="could not be committed safely",
        ):
            execute_observation_refresh_admission(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                binding_id=binding_id,
                authorization_id=authorization_id,
                executed_by_id=actor_id,
                request_key="aj-db-rollback-exec",
                execution_reason=_EXEC_REASON,
            )
        db.rollback()

    assert len(cleanup_calls) == 1
    assert cleanup_calls[0]["promoted"] is True

    with TestingSessionLocal() as db:
        prior = db.get(Document, prior_document_id)
        assert prior is not None
        assert prior.is_current is True
        assert prior.superseded_at is None
        assert prior.superseded_by_id is None
        assert db.query(Document).count() == 1
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 0
        )
