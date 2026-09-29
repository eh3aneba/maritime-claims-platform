from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.operator_read_model_service import (
    _sftp_runtime_readiness,
    build_external_document_source_operator_overview,
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


def test_ae_b_operator_overview_reports_sftp_readiness_and_baseline_transition(
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
    ) = _approved_sftp_refresh(monkeypatch, "ae-b-operator-readiness")

    changed_body = b"o" * observed_size
    read_adapter = _FileReadAdapter(content=changed_body)
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
            request_key="ae-b-refresh",
            request_reason="Stage the approved changed SFTP file for operator-readiness validation.",
            now=datetime(2026, 9, 29, 6, 10, tzinfo=UTC),
        )
        assert refresh_outcome == "completed"

        admission_auth, auth_outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh.id,
            authorized_by_id=actor_id,
            request_key="ae-b-admission-auth",
            authorization_reason="Authorize the exact staged SFTP refresh for canonical operator validation.",
            now=datetime(2026, 9, 29, 6, 11, tzinfo=UTC),
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
            request_key="ae-b-admission",
            execution_reason="Admit canonical SFTP N+1 before operator baseline transition validation.",
        )
        assert admission_outcome == "admitted"
        admission_id = admission.id
        new_document_id = admission.new_document_id
        new_version_number = admission.new_version_number

        overview = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        profile = next(row for row in overview.profiles if row.profile_id == profile_id)
        family = next(row for row in overview.families if row.binding_id == binding_id)

        assert profile.provider_kind == "sftp"
        assert profile.sftp_runtime_readiness == "ready"
        assert profile.sftp_credential_health_status == "qualified"
        assert profile.sftp_transport_status == "verified"
        assert profile.sftp_session_status == "activated"

        assert family.current_document_id == new_document_id
        assert family.current_version_number == new_version_number
        assert family.baseline_transition_required is True
        assert family.baseline_transition_id is None
        assert family.baseline_transition_status is None

    with TestingSessionLocal() as db:
        transition, outcome = establish_recurring_baseline_transition(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=admission_id,
            authorized_by_id=actor_id,
            request_key="ae-b-baseline-transition",
            reason="Explicitly establish the exact SFTP N+1 projection as recurring baseline.",
            now=datetime(2026, 9, 29, 6, 12, tzinfo=UTC),
        )
        assert outcome == "established"

        overview = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        family = next(row for row in overview.families if row.binding_id == binding_id)

        assert family.baseline_transition_required is False
        assert family.baseline_transition_id == transition.id
        assert family.baseline_transition_status == "established"
        assert family.baseline_transition_version_number == new_version_number
        assert family.baseline_transition_authorized_at == transition.authorized_at

    assert len(read_adapter.calls) == 1


@pytest.mark.parametrize(
    ("credential_status", "transport_status", "session_status", "expected"),
    (
        ("qualified", "verified", "activated", "ready"),
        ("unqualified", "verified", "activated", "attention"),
        ("qualified", "failed", "activated", "attention"),
        ("qualified", "verified", "failed", "attention"),
        ("qualified", "verified", None, "not_qualified"),
        (None, None, None, "not_qualified"),
    ),
)
def test_ae_b_sftp_runtime_readiness_derivation(
    credential_status: str | None,
    transport_status: str | None,
    session_status: str | None,
    expected: str,
) -> None:
    profile_hash = "a" * 64
    credential = (
        SimpleNamespace(
            id="credential-current",
            profile_hash=profile_hash,
            result_status=credential_status,
        )
        if credential_status is not None
        else None
    )
    transport = (
        SimpleNamespace(
            id="transport-current",
            profile_hash=profile_hash,
            result_status=transport_status,
        )
        if transport_status is not None
        else None
    )
    session = (
        SimpleNamespace(
            profile_hash=profile_hash,
            result_status=session_status,
            health_qualification_id="credential-current",
            transport_verification_id="transport-current",
        )
        if session_status is not None
        else None
    )

    assert _sftp_runtime_readiness(
        profile_hash=profile_hash,
        credential_health=credential,
        transport_verification=transport,
        session_activation=session,
    ) == expected


def test_ae_b_sftp_runtime_readiness_rejects_stale_or_mixed_lineage() -> None:
    profile_hash = "b" * 64
    credential = SimpleNamespace(
        id="credential-new",
        profile_hash=profile_hash,
        result_status="qualified",
    )
    transport = SimpleNamespace(
        id="transport-new",
        profile_hash=profile_hash,
        result_status="verified",
    )
    stale_session = SimpleNamespace(
        profile_hash=profile_hash,
        result_status="activated",
        health_qualification_id="credential-old",
        transport_verification_id="transport-new",
    )
    assert _sftp_runtime_readiness(
        profile_hash=profile_hash,
        credential_health=credential,
        transport_verification=transport,
        session_activation=stale_session,
    ) == "not_qualified"

    stale_transport = SimpleNamespace(
        id="transport-stale",
        profile_hash="c" * 64,
        result_status="verified",
    )
    assert _sftp_runtime_readiness(
        profile_hash=profile_hash,
        credential_health=credential,
        transport_verification=stale_transport,
        session_activation=None,
    ) == "not_qualified"

