from __future__ import annotations

from datetime import UTC, datetime

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


def _sftp_profile(overview, profile_id):
    return next(row for row in overview.profiles if row.profile_id == profile_id)


def _sftp_family(overview, profile_id):
    return next(row for row in overview.families if row.profile_id == profile_id)


def test_sftp_operator_overview_exposes_readiness_without_private_locator_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        chain,
        _metadata_adapter,
        _actor_id,
        organization_id,
        profile_id,
        _refresh_authorization_id,
        _observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "operator-readiness")

    with TestingSessionLocal() as db:
        overview = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )

    profile = _sftp_profile(overview, profile_id)
    family = _sftp_family(overview, profile_id)

    assert profile.provider_kind == "sftp"
    assert profile.sftp_credential_health_status == "qualified"
    assert profile.sftp_transport_status == "verified"
    assert profile.sftp_session_status == "activated"
    assert profile.sftp_credential_health_checked_at is not None
    assert profile.sftp_transport_checked_at is not None
    assert profile.sftp_session_checked_at is not None

    assert family.provider_kind == "sftp"
    assert family.recurring_baseline_transition_required is False

    serialized = overview.model_dump_json()
    for forbidden_value in (
        chain.get("hostname"),
        chain.get("username"),
        chain.get("remote_root_path"),
        chain.get("reference_name"),
    ):
        if isinstance(forbidden_value, str) and forbidden_value:
            assert forbidden_value not in serialized

    for forbidden_field in (
        "destination_hostname",
        "destination_port",
        "username",
        "remote_root_path",
        "reference_name",
        "private_key",
        "password",
        "passphrase",
    ):
        assert f'"{forbidden_field}"' not in serialized


def test_sftp_operator_overview_marks_and_clears_explicit_baseline_transition_requirement(
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
    ) = _approved_sftp_refresh(monkeypatch, "operator-baseline")

    changed_body = b"o" * observed_size
    register_external_document_source_sftp_file_content_read_adapter(
        _FileReadAdapter(content=changed_body)
    )
    register_external_document_source_remote_content_staging_store(_QuarantineStore())

    with TestingSessionLocal() as db:
        refresh, refresh_outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="sftp-operator-refresh",
            request_reason=(
                "Stage the changed SFTP content before operator-read-model admission."
            ),
            now=datetime(2026, 9, 29, 7, 0, tzinfo=UTC),
        )
        assert refresh_outcome == "completed"

        admission_auth, auth_outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh.id,
            authorized_by_id=actor_id,
            request_key="sftp-operator-admission-auth",
            authorization_reason=(
                "Authorize the exact verified refresh for operator-read-model N+1."
            ),
            now=datetime(2026, 9, 29, 7, 1, tzinfo=UTC),
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
            request_key="sftp-operator-admit",
            execution_reason=(
                "Admit the exact verified SFTP refresh as canonical N+1 for operator view."
            ),
        )
        assert admission_outcome == "admitted"
        admission_id = admission.id

        overview = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        family = _sftp_family(overview, profile_id)
        assert family.current_version_number >= 2
        assert family.recurring_baseline_transition_id is None
        assert family.recurring_baseline_status is None
        assert family.recurring_baseline_transition_required is True

    with TestingSessionLocal() as db:
        transition, outcome = establish_recurring_baseline_transition(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=admission_id,
            authorized_by_id=actor_id,
            request_key="sftp-operator-baseline-transition",
            reason=(
                "Explicitly establish the refreshed SFTP projection as recurring baseline."
            ),
            now=datetime(2026, 9, 29, 7, 2, tzinfo=UTC),
        )
        assert outcome == "established"

        overview = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        family = _sftp_family(overview, profile_id)
        assert family.recurring_baseline_transition_id == transition.id
        assert family.recurring_baseline_status == "established"
        assert family.recurring_baseline_authorized_at is not None
        assert family.recurring_baseline_transition_required is False
