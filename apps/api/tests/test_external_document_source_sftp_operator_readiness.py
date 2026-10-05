from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import sqlite

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
    _latest_sftp_rows_by_profile,
    _sftp_current_lineage_rows,
    _sftp_runtime_readiness,
    build_external_document_source_operator_overview,
)
from app.modules.external_document_sources.recurring_baseline_transition_service import (
    establish_recurring_baseline_transition,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.sftp_credential_health_models import (
    ExternalDocumentSourceSftpCredentialHealthQualification,
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

    assert (
        _sftp_runtime_readiness(
            profile_hash=profile_hash,
            credential_health=credential,
            transport_verification=transport,
            session_activation=session,
        )
        == expected
    )


def test_ae_b_current_lineage_suppresses_stale_stage_labels() -> None:
    profile_hash = "b" * 64
    stale_credential = SimpleNamespace(
        id="credential-old",
        profile_hash="c" * 64,
        result_status="qualified",
    )
    current_transport = SimpleNamespace(
        id="transport-current",
        profile_hash=profile_hash,
        result_status="verified",
    )
    mixed_session = SimpleNamespace(
        profile_hash=profile_hash,
        result_status="activated",
        health_qualification_id="credential-old",
        transport_verification_id="transport-current",
    )

    credential, transport, session = _sftp_current_lineage_rows(
        profile_hash=profile_hash,
        credential_health=stale_credential,
        transport_verification=current_transport,
        session_activation=mixed_session,
    )

    assert credential is None
    assert transport is current_transport
    assert session is None
    assert (
        _sftp_runtime_readiness(
            profile_hash=profile_hash,
            credential_health=stale_credential,
            transport_verification=current_transport,
            session_activation=mixed_session,
        )
        == "not_qualified"
    )


def test_ae_b_explicit_current_failure_stays_attention_when_other_lineage_is_stale() -> None:
    profile_hash = "d" * 64
    current_credential = SimpleNamespace(
        id="credential-current",
        profile_hash=profile_hash,
        result_status="unqualified",
    )
    stale_transport = SimpleNamespace(
        id="transport-old",
        profile_hash="e" * 64,
        result_status="verified",
    )

    credential, transport, session = _sftp_current_lineage_rows(
        profile_hash=profile_hash,
        credential_health=current_credential,
        transport_verification=stale_transport,
        session_activation=None,
    )
    assert credential is current_credential
    assert transport is None
    assert session is None
    assert (
        _sftp_runtime_readiness(
            profile_hash=profile_hash,
            credential_health=current_credential,
            transport_verification=stale_transport,
            session_activation=None,
        )
        == "attention"
    )


class _EmptyScalars:
    def all(self):
        return []


class _CapturingDb:
    def __init__(self) -> None:
        self.statements = []

    def scalars(self, statement):
        self.statements.append(statement)
        return _EmptyScalars()


def test_ae_b_latest_sftp_qualification_selection_is_one_set_based_window_query() -> None:
    db = _CapturingDb()
    profile_ids = [uuid4(), uuid4()]

    result = _latest_sftp_rows_by_profile(
        db,  # type: ignore[arg-type]
        model=ExternalDocumentSourceSftpCredentialHealthQualification,
        organization_id=uuid4(),
        profile_ids=profile_ids,
        timestamp_column=ExternalDocumentSourceSftpCredentialHealthQualification.checked_at,
    )

    assert result == {}
    assert len(db.statements) == 1
    sql = str(db.statements[0].compile(dialect=sqlite.dialect()))
    normalized = " ".join(sql.lower().split())
    assert "row_number() over" in normalized
    assert "partition by external_doc_source_sftp_cred_health_checks.profile_id" in normalized
    assert "checked_at desc" in normalized
    assert "id desc" in normalized
