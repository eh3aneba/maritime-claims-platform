from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
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
from app.modules.external_document_sources.recurring_baseline_transition_service import (
    establish_recurring_baseline_transition,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _enable_clean_aj,
)
from tests.test_external_document_source_remote_content_staging import _QuarantineStore
from tests.test_external_document_source_sftp_due_tick_service_executor import _SERVICE_ID
from tests.test_external_document_source_sftp_file_content_proof import _FileReadAdapter
from tests.test_external_document_source_sftp_observation_refresh_execution import (
    _approved_sftp_refresh,
    setup_function as _ab_setup,
    teardown_function as _ab_teardown,
)


def setup_function() -> None:
    _ab_setup()


def teardown_function() -> None:
    _ab_teardown()


def test_ae_c_contiguous_changed_refresh_n_plus_one_baseline_then_next_tick_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _chain,
        metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        refresh_authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "fl")

    # The metadata adapter is still returning the same provider projection that
    # was observed as changed against v1. After AD transition that projection
    # must become the explicit recurring baseline for canonical N+1.
    assert metadata_adapter.mode == "changed"

    read_adapter = _FileReadAdapter(content=b"l" * observed_size)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        documents_at_v1 = db.query(Document).count()
        refresh, refresh_outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ae-c-full-refresh",
            request_reason=(
                "Stage the exact approved changed SFTP file for full lifecycle acceptance."
            ),
            now=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
        )
        assert refresh_outcome == "completed"
        assert refresh.observed_projection_hash is not None

        admission_auth, auth_outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh.id,
            authorized_by_id=actor_id,
            request_key="ae-c-full-admission-auth",
            authorization_reason=(
                "Authorize the exact verified SFTP refresh for canonical lifecycle acceptance."
            ),
            now=datetime(2026, 9, 29, 9, 1, tzinfo=UTC),
        )
        assert auth_outcome == "authorized"
        admission_authorization_id = admission_auth.id
        binding_id = admission_auth.binding_id

    _enable_clean_aj(monkeypatch)
    with TestingSessionLocal() as db:
        admission, admission_outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="ae-c-full-admission",
            execution_reason=(
                "Admit canonical SFTP N+1 for full production lifecycle acceptance."
            ),
        )
        assert admission_outcome == "admitted"
        assert admission.new_version_number == 2
        n_plus_one_id = admission.new_document_id
        admission_id = admission.id
        assert db.query(Document).count() == documents_at_v1 + 1

    with TestingSessionLocal() as db:
        transition, transition_outcome = establish_recurring_baseline_transition(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=admission_id,
            authorized_by_id=actor_id,
            request_key="ae-c-full-baseline-transition",
            reason=(
                "Establish the exact admitted SFTP N+1 provider projection as recurring baseline."
            ),
            now=datetime(2026, 9, 29, 9, 2, tzinfo=UTC),
        )
        assert transition_outcome == "established"
        assert transition.current_document_id == n_plus_one_id
        assert transition.current_version_number == 2
        assert transition.baseline_projection_hash == refresh.observed_projection_hash
        documents_before_next_tick = db.query(Document).count()

        dispatch = dispatch_next_due_tick(
            db,
            worker_id="ae-c-full-lifecycle-scheduler",
            now=datetime(2026, 9, 29, 9, 3, tzinfo=UTC),
        )
        assert dispatch is not None
        assert dispatch.provider_kind == "sftp"
        assert dispatch.current_document_id == n_plus_one_id
        assert dispatch.current_version_number == 2
        dispatch_id = dispatch.id

    stat_calls_before = len(metadata_adapter.calls)
    content_reads_before = len(read_adapter.calls)

    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 29, 9, 3, tzinfo=UTC),
        )
        assert outcome == "consumed"
        assert observation.result_status == "unchanged"
        assert observation.current_document_id == n_plus_one_id
        assert observation.current_version_number == 2
        assert observation.baseline_projection_hash == transition.baseline_projection_hash
        assert observation.observed_projection_hash == transition.baseline_projection_hash
        assert db.query(Document).count() == documents_before_next_tick

        current = db.get(Document, n_plus_one_id)
        assert current is not None
        assert current.is_current is True
        assert current.version_number == 2

    assert len(metadata_adapter.calls) == stat_calls_before + 1
    assert len(read_adapter.calls) == content_reads_before == 1
    assert store.put_calls == 1
