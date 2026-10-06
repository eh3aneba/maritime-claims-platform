from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
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
    "Consume the exact approved changed SFTP file for AE-C crash-window recovery acceptance."
)


def setup_function() -> None:
    _ab_setup()
    clear_external_document_source_sftp_file_content_read_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_file_content_read_adapter()
    _ab_teardown()


def test_ae_c_quarantine_write_followed_by_db_commit_failure_is_not_replay_authority(
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
    ) = _approved_sftp_refresh(monkeypatch, "crash-after-quarantine-write")

    read_adapter = _FileReadAdapter(content=b"c" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        real_commit = db.commit
        commit_calls = {"count": 0}

        def _fail_commit() -> None:
            commit_calls["count"] += 1
            raise RuntimeError("simulated-db-commit-crash")

        monkeypatch.setattr(db, "commit", _fail_commit)
        with pytest.raises(RuntimeError, match="simulated-db-commit-crash"):
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
        assert commit_calls["count"] == 1
        db.rollback()
        monkeypatch.setattr(db, "commit", real_commit)

    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceObservationRefreshExecution).count() == 0
        assert db.query(ExternalDocumentSourceObservationRefreshReceipt).count() == 0

    # The quarantine object can outlive the failed transaction, but it cannot
    # become authority by itself. With the live provider read adapter gone,
    # the same request must fail rather than replaying an uncommitted success.
    clear_external_document_source_sftp_file_content_read_adapter()
    with TestingSessionLocal() as db:
        with pytest.raises(ExternalDocumentSourceConflictError):
            execute_observation_refresh_authorization(
                db,
                organization_id=organization_id,
                profile_id=profile_id,
                authorization_id=refresh_authorization_id,
                requested_by_id=actor_id,
                request_key="ae-c-crash-refresh-key",
                request_reason=_REASON,
                now=datetime(2026, 9, 29, 8, 1, tzinfo=UTC),
            )
        db.rollback()

    assert store.put_calls == 1
    assert len(read_adapter.calls) == 1
