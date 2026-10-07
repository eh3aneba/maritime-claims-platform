from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

import app.modules.external_document_sources.observation_refresh_execution_service as refresh_service
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
    ExternalDocumentSourceObservationRefreshRecoveryAnchor,
    ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    clear_external_document_source_sftp_file_content_read_adapter,
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_sftp_file_content_proof import _FileReadAdapter
from tests.test_external_document_source_sftp_observation_refresh_execution import (
    _approved_sftp_refresh,
    setup_function as _ab_setup,
    teardown_function as _ab_teardown,
)


_REASON = (
    "Consume the exact approved changed SFTP file through the durable AE-C crash recovery anchor."
)


def setup_function() -> None:
    _ab_setup()
    clear_external_document_source_sftp_file_content_read_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_file_content_read_adapter()
    _ab_teardown()


def test_ae_c_object_write_then_final_db_failure_recovers_without_second_provider_io(
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
    ) = _approved_sftp_refresh(monkeypatch, "cw")

    first_adapter = _FileReadAdapter(content=b"c" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(first_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        real_commit = db.commit
        commit_calls = {"count": 0}

        def _fail_final_commit() -> None:
            commit_calls["count"] += 1
            if commit_calls["count"] == 2:
                raise RuntimeError("simulated-final-db-commit-crash")
            real_commit()

        monkeypatch.setattr(db, "commit", _fail_final_commit)
        with pytest.raises(RuntimeError, match="simulated-final-db-commit-crash"):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=refresh_authorization_id,
                requested_by_id=actor_id,
                request_key="ae-c-crash-refresh-key",
                request_reason=_REASON,
                now=datetime(2026, 9, 29, 8, 0, tzinfo=UTC),
            )
        assert commit_calls["count"] == 2
        db.rollback()
        monkeypatch.setattr(db, "commit", real_commit)

    assert len(first_adapter.calls) == 1
    assert store.put_calls == 1

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 0

    # Simulate process/runtime replacement. The replacement adapter must be
    # policy-compatible but must never be called because the anchored object
    # is now the recoverable custody fact.
    replacement_adapter = _FileReadAdapter(content=b"z" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(replacement_adapter)
    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-crash-refresh-key",
            request_reason=_REASON,
            now=datetime(2026, 9, 29, 8, 1, tzinfo=UTC),
        )
        assert outcome == "completed"
        execution_id = execution.id

    assert len(first_adapter.calls) == 1
    assert len(replacement_adapter.calls) == 0
    assert store.put_calls == 1

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 1
        persisted = db.get(ExternalDocumentSourceObservationRefreshExecution, execution_id)
        assert persisted is not None
        assert persisted.requested_at == datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


def test_ae_c_anchor_only_restart_performs_one_controlled_provider_read(
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
    ) = _approved_sftp_refresh(monkeypatch, "anchor-only")

    adapter = _FileReadAdapter(content=b"d" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    real_read = refresh_service._read_exact_changed_content

    def _crash_before_provider_read(*_args, **_kwargs):
        raise RuntimeError("simulated-crash-after-anchor-commit")

    monkeypatch.setattr(
        refresh_service,
        "_read_exact_changed_content",
        _crash_before_provider_read,
    )
    with TestingSessionLocal() as db:
        with pytest.raises(RuntimeError, match="simulated-crash-after-anchor-commit"):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=refresh_authorization_id,
                requested_by_id=actor_id,
                request_key="ae-c-anchor-only-key",
                request_reason=_REASON,
                now=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
            )
        db.rollback()

    assert len(adapter.calls) == 0
    assert store.put_calls == 0
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 1
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0

    monkeypatch.setattr(refresh_service, "_read_exact_changed_content", real_read)
    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-anchor-only-key",
            request_reason=_REASON,
            now=datetime(2026, 9, 29, 9, 1, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert execution.requested_at == datetime(2026, 9, 29, 9, 0, tzinfo=UTC)

    assert len(adapter.calls) == 1
    assert store.put_calls == 1


def test_ae_c_unanchored_preexisting_quarantine_object_fails_closed_before_provider_read(
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
    ) = _approved_sftp_refresh(monkeypatch, "orphan")

    adapter = _FileReadAdapter(content=b"e" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    execution_id = uuid5(
        NAMESPACE_URL,
        f"mcri:observation-refresh:{refresh_authorization_id}",
    )
    storage_key = refresh_service._storage_key(
        refresh_authorization_id,
        execution_id,
    )
    store.objects[storage_key] = b"unproven-orphan"

    with TestingSessionLocal() as db:
        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="already occupied without durable authority",
        ):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=refresh_authorization_id,
                requested_by_id=actor_id,
                request_key="ae-c-orphan-key",
                request_reason=_REASON,
                now=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
            )
        db.rollback()

    assert len(adapter.calls) == 0
    assert store.put_calls == 0
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchor).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshRecoveryAnchorReceipt).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0
