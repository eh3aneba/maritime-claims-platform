from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
    ExternalDocumentSourceObservationRefreshAdmissionReceipt,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.recurring_baseline_transition_models import (
    ExternalDocumentSourceRecurringBaselineTransition,
    ExternalDocumentSourceRecurringBaselineTransitionReceipt,
)
from app.modules.external_document_sources.recurring_baseline_transition_service import (
    establish_recurring_baseline_transition,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
    ExternalDocumentSourceSftpFileContentProofReceipt,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    clear_external_document_source_sftp_file_content_read_adapter,
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _enable_clean_aj,
)
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_sftp_file_content_proof import (
    _FileReadAdapter,
    _listed_chain,
    _proof,
)
from tests.test_external_document_source_sftp_observation_refresh_execution import (
    _approved_sftp_refresh,
    setup_function as _ab_setup,
    teardown_function as _ab_teardown,
)


_REFRESH_REASON = (
    "Consume the exact approved changed SFTP file into governed refresh quarantine "
    "for restart and replay acceptance."
)
_ADMISSION_REASON = (
    "Admit the exact verified SFTP refresh as canonical Evidence N+1 for restart "
    "and replay acceptance."
)


def setup_function() -> None:
    _ab_setup()
    clear_external_document_source_sftp_file_content_read_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_file_content_read_adapter()
    _ab_teardown()


def test_ae_c_content_proof_replay_survives_provider_runtime_reset() -> None:
    chain = _listed_chain("ae-c-content-proof-restart")
    adapter = _FileReadAdapter()
    register_external_document_source_sftp_file_content_read_adapter(adapter)

    first = _proof(chain, key="ae-c-content-proof-key")
    assert first.status_code == 201, first.text
    proof_id = first.json()["id"]
    assert len(adapter.calls) == 1

    with TestingSessionLocal() as db:
        durable_counts = (
            db.query(ExternalDocumentSourceSftpFileContentProof).count(),
            db.query(ExternalDocumentSourceSftpFileContentProofReceipt).count(),
        )

    # Simulate process restart: live provider registry is empty.
    clear_external_document_source_sftp_file_content_read_adapter()

    replay = _proof(chain, key="ae-c-content-proof-key")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == proof_id
    assert len(adapter.calls) == 1

    with TestingSessionLocal() as db:
        assert (
            db.query(ExternalDocumentSourceSftpFileContentProof).count(),
            db.query(ExternalDocumentSourceSftpFileContentProofReceipt).count(),
        ) == durable_counts


def test_ae_c_refresh_replay_survives_sftp_runtime_replacement(
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
    ) = _approved_sftp_refresh(monkeypatch, "rr")

    read_adapter = _FileReadAdapter(content=b"q" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        first, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-refresh-key",
            request_reason=_REFRESH_REASON,
            now=datetime(2026, 9, 29, 7, 0, tzinfo=UTC),
        )
        assert outcome == "completed"
        first_id = first.id
        durable_counts = (
            db.query(ExternalDocumentSourceObservationRefreshExecution).count(),
            db.query(ExternalDocumentSourceObservationRefreshReceipt).count(),
        )

    assert len(read_adapter.calls) == 1
    put_calls = store.put_calls

    # New process has not registered a provider read adapter yet. Durable replay
    # must still return the prior immutable refresh execution.
    clear_external_document_source_sftp_file_content_read_adapter()

    with TestingSessionLocal() as db:
        replay, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-refresh-key",
            request_reason=_REFRESH_REASON,
            now=datetime(2026, 9, 29, 7, 1, tzinfo=UTC),
        )
        assert outcome == "replayed"
        assert replay.id == first_id
        assert (
            db.query(ExternalDocumentSourceObservationRefreshExecution).count(),
            db.query(ExternalDocumentSourceObservationRefreshReceipt).count(),
        ) == durable_counts

    assert len(read_adapter.calls) == 1
    assert store.put_calls == put_calls


def test_ae_c_canonical_admission_and_baseline_transition_replay_without_side_effects(
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
    ) = _approved_sftp_refresh(monkeypatch, "ra")

    read_adapter = _FileReadAdapter(content=b"z" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        refresh, refresh_outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-admission-refresh",
            request_reason=_REFRESH_REASON,
            now=datetime(2026, 9, 29, 7, 10, tzinfo=UTC),
        )
        assert refresh_outcome == "completed"

        admission_auth, auth_outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh.id,
            authorized_by_id=actor_id,
            request_key="ae-c-admission-auth",
            authorization_reason=(
                "Authorize this exact verified SFTP refresh for canonical restart acceptance."
            ),
            now=datetime(2026, 9, 29, 7, 11, tzinfo=UTC),
        )
        assert auth_outcome == "authorized"
        admission_authorization_id = admission_auth.id
        binding_id = admission_auth.binding_id

    security_calls = _enable_clean_aj(monkeypatch)
    with TestingSessionLocal() as db:
        first, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="ae-c-admission-key",
            execution_reason=_ADMISSION_REASON,
        )
        assert outcome == "admitted"
        first_id = first.id
        new_document_id = first.new_document_id
        admission_id = first.id
        admission_counts = (
            db.query(ExternalDocumentSourceObservationRefreshAdmissionExecution).count(),
            db.query(ExternalDocumentSourceObservationRefreshAdmissionReceipt).count(),
            db.query(Document).count(),
        )

    initial_security_calls = dict(security_calls)
    assert initial_security_calls == {"signature": 1, "malware": 1}

    # Replay must not invoke security gates or canonical write a second time.
    with TestingSessionLocal() as db:
        replay, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="ae-c-admission-key",
            execution_reason=_ADMISSION_REASON,
        )
        assert outcome == "replayed"
        assert replay.id == first_id
        assert replay.new_document_id == new_document_id
        assert (
            db.query(ExternalDocumentSourceObservationRefreshAdmissionExecution).count(),
            db.query(ExternalDocumentSourceObservationRefreshAdmissionReceipt).count(),
            db.query(Document).count(),
        ) == admission_counts

    assert security_calls == initial_security_calls
    assert len(read_adapter.calls) == 1

    with TestingSessionLocal() as db:
        transition, outcome = establish_recurring_baseline_transition(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=admission_id,
            authorized_by_id=actor_id,
            request_key="ae-c-baseline-key",
            reason=(
                "Establish the exact admitted SFTP N+1 projection as recurring baseline "
                "for restart and replay acceptance."
            ),
            now=datetime(2026, 9, 29, 7, 12, tzinfo=UTC),
        )
        assert outcome == "established"
        transition_id = transition.id
        baseline_counts = (
            db.query(ExternalDocumentSourceRecurringBaselineTransition).count(),
            db.query(ExternalDocumentSourceRecurringBaselineTransitionReceipt).count(),
            db.query(Document).count(),
        )

    with TestingSessionLocal() as db:
        replay, outcome = establish_recurring_baseline_transition(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=admission_id,
            authorized_by_id=actor_id,
            request_key="ae-c-baseline-key",
            reason=(
                "Establish the exact admitted SFTP N+1 projection as recurring baseline "
                "for restart and replay acceptance."
            ),
            now=datetime(2026, 9, 29, 7, 13, tzinfo=UTC),
        )
        assert outcome == "replayed"
        assert replay.id == transition_id
        assert (
            db.query(ExternalDocumentSourceRecurringBaselineTransition).count(),
            db.query(ExternalDocumentSourceRecurringBaselineTransitionReceipt).count(),
            db.query(Document).count(),
        ) == baseline_counts

    assert len(read_adapter.calls) == 1
