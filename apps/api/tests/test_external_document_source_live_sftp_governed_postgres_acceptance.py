"""Real OpenSSH metadata -> governed PostgreSQL due-tick/replay Pilot P0 slice.

The initial v1 Evidence fixture is deterministic. Only the due-tick provider
observation uses real OpenSSH via the production LiveSftpRuntime adapter.
Test-only destination remapping permits a loopback CI server: it is NOT an
approval to weaken the production destination restriction or an end-to-end
v1->N+1 proof.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
    ExternalDocumentSourceDueTickDispatchConsumptionReceipt,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
    ExternalDocumentSourceDueTickObservationReceipt,
)
from app.modules.external_document_sources.live_sftp_adapters import (
    LiveSftpRuntime,
    _SftpExactMetadataAdapter,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    clear_external_document_source_sftp_exact_file_metadata_adapter,
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_live_sftp_real_server_acceptance import (
    _fingerprint,
    _settings,
)
from tests.test_external_document_source_sftp_due_tick_service_executor import (
    _SERVICE_ID,
    _prepare,
    setup_function as _setup,
    teardown_function as _teardown,
)

pytestmark = pytest.mark.skipif(
    os.getenv("MCRI_REAL_SFTP_ACCEPTANCE") != "1"
    or not os.getenv("MCRI_TEST_DATABASE_URL")
    or not os.getenv("MCRI_REAL_SFTP_PRIVATE_KEY_FILE"),
    reason="opt-in controlled OpenSSH + PostgreSQL acceptance only",
)


class _ControlledPrivateKeySecretRuntime:
    """Loads only the short-lived key generated inside the CI runner."""

    def load_secret(self, _locator) -> str:
        _host, _port, username, _password, _root = _settings()
        private_key_file = Path(os.environ["MCRI_REAL_SFTP_PRIVATE_KEY_FILE"])
        return json.dumps(
            {
                "username": username,
                "authentication_kind": "private_key",
                "private_key": private_key_file.read_text(encoding="utf-8"),
            }
        )


class _LocalOnlyProviderBridge:
    """Test-harness rewrite of *one* provider request, never production state."""

    adapter_kind = "controlled_openssh_postgres_metadata_bridge_v1"

    def __init__(self, runtime: LiveSftpRuntime, fingerprint: str):
        self._adapter = _SftpExactMetadataAdapter(runtime)
        self._fingerprint = fingerprint
        self.calls = 0

    def stat_metadata(self, request):
        self.calls += 1
        host, port, username, _password, root = _settings()
        assert host == "127.0.0.1", "private CI loopback host required"
        assert request.authentication_kind == "private_key"
        assert request.allow_private_destinations is False
        assert request.read_only_intent is True
        assert request.follow_symlinks is False
        assert request.max_stat_attempts == 1
        assert request.max_connection_attempts == 1
        assert request.max_authentication_attempts == 1

        # Original governed fixture remains synthetic. Rebind *only* the
        # ephemeral provider call to real OpenSSH with matching auth material.
        real_request = replace(
            request,
            hostname=host,
            port=port,
            username=username,
            pinned_host_key_fingerprint=self._fingerprint,
            reference_backend="azure_key_vault",
            reference_namespace="ci-only",
            reference_name="ephemeral-openssh-key",
            reference_version=None,
            remote_root_path=root,
            entry_relative_path="survey.txt",
            effective_remote_path=f"{root}/survey.txt",
            allow_private_destinations=True,
        )
        return self._adapter.stat_metadata(real_request)


def setup_function() -> None:
    _setup()


def teardown_function() -> None:
    _teardown()


def test_real_openssh_stat_persists_changed_observation_and_replays_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DB-backed v1 approval/admission and schedule are created using existing
    # deterministic fixtures; this test proves the provider/DB observation seam.
    _chain, _fixture_adapter, execution, _binding, dispatch_id = _prepare(
        monkeypatch, "real-openssh-postgres"
    )

    runtime = LiveSftpRuntime(secret_runtime=_ControlledPrivateKeySecretRuntime())
    fingerprint = _fingerprint(runtime)
    assert fingerprint == os.environ["MCRI_REAL_SFTP_FINGERPRINT"]

    bridge = _LocalOnlyProviderBridge(runtime, fingerprint)
    register_external_document_source_sftp_exact_file_metadata_adapter(bridge)
    document_id = UUID(execution["document_id"])

    with TestingSessionLocal() as db:
        baseline = db.get(Document, document_id)
        assert baseline is not None
        baseline_version = (
            baseline.version_number, baseline.is_current,
            baseline.file_hash, baseline.processing_status,
        )
        documents_before = db.query(Document).count()
        observation, consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        assert observation.result_status == "changed"
        assert observation.provider_kind == "sftp"
        assert observation.observed_byte_size == len(b"controlled-real-sftp-evidence\n")
        assert observation.observed_projection_hash is not None
        assert observation.observed_projection_hash != observation.baseline_projection_hash
        assert consumption.status == "executed"
        observation_id, consumption_id = observation.id, consumption.id
        assert db.query(Document).count() == documents_before

    assert bridge.calls == 1, "one real, read-only OpenSSH stat expected"

    # Loss of the registered adapter simulates restart. Previously committed
    # receipts must be returned without any new SSH connection/provider call.
    clear_external_document_source_sftp_exact_file_metadata_adapter()
    with TestingSessionLocal() as db:
        replay_observation, replay_consumption, replay_result = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 28, 18, 5, tzinfo=UTC),
        )
        assert replay_result == "replayed"
        assert replay_observation.id == observation_id
        assert replay_consumption.id == consumption_id
        assert db.query(ExternalDocumentSourceDueTickObservationExecution).count() == 1
        assert db.query(ExternalDocumentSourceDueTickObservationReceipt).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumption).count() == 1
        assert db.query(ExternalDocumentSourceDueTickDispatchConsumptionReceipt).count() == 1
        document = db.get(Document, document_id)
        assert document is not None
        assert (
            document.version_number, document.is_current,
            document.file_hash, document.processing_status,
        ) == baseline_version
        assert db.query(Document).count() == documents_before
    assert bridge.calls == 1
