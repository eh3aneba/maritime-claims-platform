from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.external_document_sources.live_sftp_adapters import (
    _SftpContentReadAdapter,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadResult,
    clear_external_document_source_sftp_file_content_read_adapter,
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_sftp_file_content_proof import (
    _FILE_BODY,
    _listed_chain,
    _proof,
    setup_function as _proof_setup,
    teardown_function as _proof_teardown,
)
from tests.test_external_document_source_sftp_observation_refresh_execution import (
    _approved_sftp_refresh,
)


class _CountingProductionReadRuntime:
    def __init__(self, content: bytes):
        self.content = content
        self.calls = []

    def read_content(self, request):
        self.calls.append(request)
        authentication_method = (
            "password"
            if request.authentication_kind == "password"
            else "public_key"
        )
        return SftpFileContentReadResult(
            content=self.content,
            failure_code=None,
            authentication_method=authentication_method,
            latency_class="normal",
            secret_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=True,
            host_key_verification_performed=True,
            host_key_verified=True,
            authentication_performed=True,
            authentication_succeeded=True,
            sftp_session_opened=True,
            remote_read_performed=True,
            content_read_count=1,
            sftp_session_closed=True,
            credential_persisted=False,
            session_persisted=False,
            raw_response_persisted=False,
            remote_content_persisted=False,
            remote_content_returned=False,
            remote_content_logged=False,
            content_parsed=False,
            content_extracted=False,
            remote_list_performed=False,
            remote_stat_performed=True,
            remote_write_performed=False,
            remote_rename_performed=False,
            remote_delete_performed=False,
            remote_mkdir_performed=False,
            remote_chmod_performed=False,
            remote_chown_performed=False,
            remote_touch_performed=False,
            command_executed=False,
        )


def setup_function() -> None:
    _proof_setup()


def teardown_function() -> None:
    clear_external_document_source_sftp_file_content_read_adapter()
    _proof_teardown()


def test_committed_initial_content_proof_replay_after_registry_restart_does_not_reread() -> None:
    chain = _listed_chain("sftp-ae-c-initial-proof-restart")

    first_runtime = _CountingProductionReadRuntime(_FILE_BODY)
    register_external_document_source_sftp_file_content_read_adapter(
        _SftpContentReadAdapter(first_runtime)
    )

    first = _proof(chain, key="ae-c-initial-proof")
    assert first.status_code == 201, first.text
    proof_id = first.json()["id"]
    assert len(first_runtime.calls) == 1

    # Simulate a process/runtime restart: adapter globals disappear, then the
    # production adapter class is registered around a fresh runtime instance.
    clear_external_document_source_sftp_file_content_read_adapter()
    restarted_runtime = _CountingProductionReadRuntime(_FILE_BODY)
    register_external_document_source_sftp_file_content_read_adapter(
        _SftpContentReadAdapter(restarted_runtime)
    )

    replay = _proof(chain, key="ae-c-initial-proof")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == proof_id
    assert len(restarted_runtime.calls) == 0

    # A different request key for the already-proven exact listing entry is
    # rejected before provider I/O.
    duplicate = _proof(chain, key="ae-c-initial-proof-duplicate")
    assert duplicate.status_code == 409, duplicate.text
    assert len(restarted_runtime.calls) == 0


def test_committed_changed_refresh_replay_after_registry_restart_does_not_reread(
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
    ) = _approved_sftp_refresh(monkeypatch, "ae-c-refresh-restart")

    refreshed_body = b"c" * observed_size
    first_runtime = _CountingProductionReadRuntime(refreshed_body)
    register_external_document_source_sftp_file_content_read_adapter(
        _SftpContentReadAdapter(first_runtime)
    )
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-refresh-execution",
            request_reason=(
                "Execute the approved changed SFTP refresh before restart replay proof."
            ),
            now=datetime(2026, 9, 29, 8, 0, tzinfo=UTC),
        )
        assert outcome == "completed"
        execution_id = execution.id

    assert len(first_runtime.calls) == 1
    assert store.put_calls == 1

    clear_external_document_source_sftp_file_content_read_adapter()
    restarted_runtime = _CountingProductionReadRuntime(refreshed_body)
    register_external_document_source_sftp_file_content_read_adapter(
        _SftpContentReadAdapter(restarted_runtime)
    )

    with TestingSessionLocal() as db:
        replay, replay_outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-refresh-execution",
            request_reason=(
                "Execute the approved changed SFTP refresh before restart replay proof."
            ),
        )
        assert replay_outcome == "replayed"
        assert replay.id == execution_id

    assert len(restarted_runtime.calls) == 0
    assert store.put_calls == 1
