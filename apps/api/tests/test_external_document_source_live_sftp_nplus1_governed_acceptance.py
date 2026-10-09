"""Controlled real OpenSSH changed-file read -> governed PostgreSQL N+1.

Initial canonical v1 is seeded through the existing deterministic synthetic
fixture. Only the due-tick stat and approved refreshed-content read contact
real OpenSSH. This does not claim a fully real-server initial v1 admission,
or production malware scanning, or cross-process fault injection.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import os
from uuid import UUID

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
)
from app.modules.external_document_sources.live_sftp_adapters import (
    LiveSftpRuntime,
    _SftpContentReadAdapter,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
)
from app.modules.external_document_sources.observation_review_handoff_service import (
    project_observation_review_handoff,
)
from app.modules.external_document_sources.recurring_baseline_transition_service import (
    establish_recurring_baseline_transition,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    clear_external_document_source_sftp_file_content_read_adapter,
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_live_sftp_governed_postgres_acceptance import (
    _ControlledPrivateKeySecretRuntime,
    _LocalOnlyProviderBridge,
    setup_function as _setup,
    teardown_function as _teardown,
)
from tests.test_external_document_source_live_sftp_real_server_acceptance import (
    _fingerprint,
    _settings,
)
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _enable_clean_aj,
)
from tests.test_external_document_source_remote_content_staging import (
    _QuarantineStore,
)
from tests.test_external_document_source_sftp_due_tick_service_executor import (
    _SERVICE_ID,
    _prepare,
)

pytestmark = pytest.mark.skipif(
    os.getenv("MCRI_REAL_SFTP_ACCEPTANCE") != "1"
    or not os.getenv("MCRI_TEST_DATABASE_URL")
    or not os.getenv("MCRI_REAL_SFTP_PRIVATE_KEY_FILE"),
    reason="controlled OpenSSH + real PostgreSQL acceptance is opt-in",
)

_REAL_BYTES = b"controlled-real-sftp-evidence\n"
_REASON = "Verify the approved OpenSSH synthetic changed-file source."


class _LocalOnlyRealContentBridge:
    adapter_kind = "controlled_openssh_postgres_content_bridge_v1"

    def __init__(self, runtime: LiveSftpRuntime, fingerprint: str):
        self._adapter = _SftpContentReadAdapter(runtime)
        self._fingerprint = fingerprint
        self.calls = 0

    def read_content(self, request):
        self.calls += 1
        host, port, username, _password, root = _settings()
        assert host == "127.0.0.1"
        assert request.authentication_kind == "private_key"
        assert request.allow_private_destinations is False
        assert request.read_only_intent is True
        assert request.exact_file_only is True
        assert request.follow_symlinks is False
        assert request.max_connection_attempts == 1
        assert request.max_authentication_attempts == 1
        assert request.max_read_attempts == 1
        request_for_runner = replace(
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
        result = self._adapter.read_content(request_for_runner)
        assert result.remote_write_performed is False
        assert result.remote_rename_performed is False
        assert result.remote_delete_performed is False
        assert result.command_executed is False
        return result


def setup_function() -> None:
    _setup()


def teardown_function() -> None:
    clear_external_document_source_sftp_file_content_read_adapter()
    _teardown()


def test_real_openssh_changed_read_then_human_authorized_nplus1_and_next_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the real service/API v1 chain and schedule using deterministic
    # synthetic data, without promising that the initial v1 came from OpenSSH.
    chain, _fixture_adapter, execution, _binding, dispatch_id = _prepare(
        monkeypatch, "real-sftp-nplus1"
    )
    actor_id = UUID(str(chain["requester_id"]))
    organization_id = UUID(str(chain["org_id"]))
    profile_id = UUID(str(chain["profile_id"]))
    prior_document_id = UUID(execution["document_id"])

    runtime = LiveSftpRuntime(secret_runtime=_ControlledPrivateKeySecretRuntime())
    fingerprint = _fingerprint(runtime)
    assert fingerprint == os.environ["MCRI_REAL_SFTP_FINGERPRINT"]

    metadata_bridge = _LocalOnlyProviderBridge(runtime, fingerprint)
    register_external_document_source_sftp_exact_file_metadata_adapter(metadata_bridge)

    with TestingSessionLocal() as db:
        v1 = db.get(Document, prior_document_id)
        assert v1 is not None
        assert v1.version_number == 1 and v1.is_current is True
        original_v1_hash = v1.file_hash
        original_v1_family = v1.document_family_id
        initial_document_count = db.query(Document).count()

        observed, first_consumption, observed_result = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 28, 18, 0, tzinfo=UTC),
        )
        assert observed_result == "consumed"
        assert observed.result_status == "changed"
        assert observed.observed_byte_size == len(_REAL_BYTES)
        assert observed.observed_projection_hash != observed.baseline_projection_hash
        assert first_consumption.status == "executed"

        handoff, projected = project_observation_review_handoff(
            db,
            observation_execution_id=observed.id,
            projector_id="external-evidence-review-projector-v1",
            now=datetime(2026, 9, 28, 18, 1, tzinfo=UTC),
        )
        assert projected == "projected"
        assert handoff is not None and handoff.status == "pending"
        decision, approval, decided = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff.id,
            decided_by_id=actor_id,
            request_key="real-sftp-nplus1-human-refresh-approval",
            decision_kind="approve_refresh",
            decision_reason="Human review approves the single synthetic changed OpenSSH file.",
            now=datetime(2026, 9, 28, 18, 2, tzinfo=UTC),
        )
        assert decided == "decided"
        assert decision.status == "refresh_authorized"
        assert approval is not None and approval.provider_kind == "sftp"
        refresh_auth_id = approval.id
        observed_projection_hash = observed.observed_projection_hash

    content_bridge = _LocalOnlyRealContentBridge(runtime, fingerprint)
    register_external_document_source_sftp_file_content_read_adapter(content_bridge)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        refresh, result = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_auth_id,
            requested_by_id=actor_id,
            request_key="real-sftp-nplus1-approved-content-read",
            request_reason="Read and quarantine the exact human-approved changed OpenSSH file.",
            now=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
        )
        assert result == "completed"
        assert refresh.result_status == "staged_refresh_verified"
        assert refresh.content_byte_count == len(_REAL_BYTES)
        assert refresh.content_sha256 == hashlib.sha256(_REAL_BYTES).hexdigest()
        assert refresh.observed_projection_hash == observed_projection_hash
        assert refresh.exact_item_content_read_performed is True
        assert refresh.remote_write_performed is False
        assert refresh.document_mutated is False
        assert db.query(Document).count() == initial_document_count
        refresh_id = refresh.id

        # Real content read must be completed only after approval and never
        # re-read on the same committed operation's replay.
        replayed, replay_outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_auth_id,
            requested_by_id=actor_id,
            request_key="real-sftp-nplus1-approved-content-read",
            request_reason="Read and quarantine the exact human-approved changed OpenSSH file.",
        )
        assert replay_outcome == "replayed"
        assert replayed.id == refresh_id

        admission_auth, auth_outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key="real-sftp-nplus1-human-admission",
            authorization_reason="Human reviewer separately authorizes the verified staged evidence update.",
            now=datetime(2026, 9, 29, 9, 1, tzinfo=UTC),
        )
        assert auth_outcome == "authorized"
        admission_auth_id = admission_auth.id
        binding_id = admission_auth.binding_id

    assert content_bridge.calls == 1
    assert store.put_calls == 1

    security_calls = _enable_clean_aj(monkeypatch)
    with TestingSessionLocal() as db:
        admitted, admit_outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_auth_id,
            executed_by_id=actor_id,
            request_key="real-sftp-nplus1-admit",
            execution_reason="Create the exact next canonical synthetic survey evidence version.",
        )
        assert admit_outcome == "admitted"
        assert admitted.new_version_number == 2
        assert admitted.prior_document_id == prior_document_id
        assert db.query(Document).count() == initial_document_count + 1
        new_document_id = admitted.new_document_id
        assert new_document_id != prior_document_id

        v1 = db.get(Document, prior_document_id)
        v2 = db.get(Document, new_document_id)
        assert v1 is not None and v2 is not None
        assert v1.version_number == 1 and v1.is_current is False
        assert v1.file_hash == original_v1_hash
        assert v1.document_family_id == original_v1_family
        assert v2.version_number == 2 and v2.is_current is True
        assert v2.file_hash == hashlib.sha256(_REAL_BYTES).hexdigest()
        assert v2.document_family_id == original_v1_family

        replay_admission, replay_admit_outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_auth_id,
            executed_by_id=actor_id,
            request_key="real-sftp-nplus1-admit",
            execution_reason="Create the exact next canonical synthetic survey evidence version.",
        )
        assert replay_admit_outcome == "replayed"
        assert replay_admission.new_document_id == new_document_id
        assert db.query(Document).count() == initial_document_count + 1
        admission_id = admitted.id

        transition, transition_outcome = establish_recurring_baseline_transition(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=admission_id,
            authorized_by_id=actor_id,
            request_key="real-sftp-nplus1-baseline-transition",
            reason="Rebase recurring observation onto the exact admitted N+1 projection.",
            now=datetime(2026, 9, 29, 9, 2, tzinfo=UTC),
        )
        assert transition_outcome == "established"
        assert transition.current_document_id == new_document_id
        assert transition.current_version_number == 2
        assert transition.baseline_projection_hash == observed_projection_hash

        next_tick = dispatch_next_due_tick(
            db,
            worker_id="real-sftp-nplus1-observer",
            now=datetime(2026, 9, 29, 9, 3, tzinfo=UTC),
        )
        assert next_tick is not None
        assert next_tick.current_document_id == new_document_id
        assert next_tick.current_version_number == 2
        next_dispatch_id = next_tick.id

    with TestingSessionLocal() as db:
        observed_next, consumed_next, next_outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=next_dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 29, 9, 3, tzinfo=UTC),
        )
        assert next_outcome == "consumed"
        assert consumed_next.status == "executed"
        assert observed_next.result_status == "unchanged"
        assert observed_next.current_document_id == new_document_id
        assert observed_next.baseline_projection_hash == observed_projection_hash
        assert observed_next.observed_projection_hash == observed_projection_hash
        assert db.query(Document).count() == initial_document_count + 1

    assert metadata_bridge.calls == 2
    assert content_bridge.calls == 1
    assert store.put_calls == 1
    assert security_calls["signature"] == 1
    assert security_calls["malware"] == 1
