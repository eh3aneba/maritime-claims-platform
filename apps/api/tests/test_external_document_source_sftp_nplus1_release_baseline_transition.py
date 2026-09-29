from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _prior_source_state,
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
from app.modules.external_document_sources.processing_release_service import (
    get_active_processing_release_for_document,
    grant_processing_release,
)
from app.modules.external_document_sources.recurring_baseline_transition_service import (
    establish_recurring_baseline_transition,
    ensure_recurring_baseline_transition_integrity,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.documents.models import Document
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


def test_phase_ad_nplus1_requires_fresh_release_and_explicit_baseline_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        chain,
        metadata_adapter,
        actor_id,
        organization_id,
        profile_id,
        refresh_authorization_id,
        observed_size,
    ) = _approved_sftp_refresh(monkeypatch, "nplus1-release-baseline")

    with TestingSessionLocal() as db:
        from app.modules.external_document_sources.observation_review_decision_models import (
            ExternalDocumentSourceObservationRefreshAuthorization,
        )

        refresh_auth = db.get(
            ExternalDocumentSourceObservationRefreshAuthorization,
            refresh_authorization_id,
        )
        assert refresh_auth is not None
        prior_document = db.get(Document, refresh_auth.current_document_id)
        assert prior_document is not None
        claim_id = prior_document.claim_id

    with TestingSessionLocal() as db:
        old_release, old_outcome = grant_processing_release(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=prior_document.id,
            released_by_id=actor_id,
            request_key="sftp-phase-ad-prior-release",
            reason="Explicit local-processing release for the prior canonical SFTP Evidence version.",
        )
        assert old_outcome == "granted"
        assert old_release.document_version_number == prior_document.version_number
        old_release_document_id = old_release.document_id

    changed_body = b"n" * observed_size
    read_adapter = _FileReadAdapter(content=changed_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        refresh, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="sftp-phase-ad-refresh",
            request_reason="Stage the approved SFTP changed-file refresh before canonical N+1 admission.",
            now=datetime(2026, 9, 29, 5, 0, tzinfo=UTC),
        )
        assert outcome == "completed"

        admission_auth, auth_outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh.id,
            authorized_by_id=actor_id,
            request_key="sftp-phase-ad-admission-auth",
            authorization_reason="Authorize this exact verified SFTP refresh for canonical N+1 admission.",
            now=datetime(2026, 9, 29, 5, 1, tzinfo=UTC),
        )
        assert auth_outcome == "authorized"
        binding_id = admission_auth.binding_id

    security_calls = _enable_clean_aj(monkeypatch)
    with TestingSessionLocal() as db:
        admission, admission_outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_auth.id,
            executed_by_id=actor_id,
            request_key="sftp-phase-ad-admit",
            execution_reason="Admit the verified refresh as canonical SFTP Evidence N+1.",
        )
        assert admission_outcome == "admitted"
        new_document = db.get(Document, admission.new_document_id)
        binding = db.get(ExternalDocumentSourceEvidenceFamilyBinding, binding_id)
        assert new_document is not None
        assert binding is not None
        assert new_document.version_number == prior_document.version_number + 1
        assert new_document.is_current is True

        assert get_active_processing_release_for_document(
            db,
            document=new_document,
        ) is None

        with pytest.raises(
            ExternalDocumentSourceConflictError,
            match="explicit recurring baseline transition",
        ):
            _prior_source_state(
                db,
                binding=binding,
                current_document=new_document,
            )

        admission_id = admission.id
        new_document_id = new_document.id
        new_version_number = new_document.version_number

    assert len(read_adapter.calls) == 1
    assert security_calls == {"signature": 1, "malware": 1}

    with TestingSessionLocal() as db:
        new_release, release_outcome = grant_processing_release(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=new_document_id,
            released_by_id=actor_id,
            request_key="sftp-phase-ad-nplus1-release",
            reason="Explicit local-processing release for the newly admitted SFTP Evidence version.",
        )
        assert release_outcome == "granted"
        assert new_release.document_id == new_document_id
        assert new_release.document_version_number == new_version_number
        assert new_release.document_id != old_release_document_id

    assert len(read_adapter.calls) == 1

    with TestingSessionLocal() as db:
        transition, transition_outcome = establish_recurring_baseline_transition(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_admission_execution_id=admission_id,
            authorized_by_id=actor_id,
            request_key="sftp-phase-ad-baseline-transition",
            reason="Explicitly establish the refreshed SFTP source projection as the recurring baseline.",
            now=datetime(2026, 9, 29, 5, 2, tzinfo=UTC),
        )
        assert transition_outcome == "established"
        assert transition.provider_kind == "sftp"
        assert transition.current_document_id == new_document_id
        assert transition.current_version_number == new_version_number
        ensure_recurring_baseline_transition_integrity(db, transition)

        new_document = db.get(Document, new_document_id)
        binding = db.get(ExternalDocumentSourceEvidenceFamilyBinding, binding_id)
        assert new_document is not None and binding is not None
        baseline_projection, baseline_version = _prior_source_state(
            db,
            binding=binding,
            current_document=new_document,
        )
        assert baseline_projection == transition.baseline_projection_hash
        assert baseline_version == transition.baseline_version_token_hash

        transition_id = transition.id

    assert len(read_adapter.calls) == 1

    metadata_adapter.mode = "changed"
    with TestingSessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id="sftp-phase-ad-next-due",
            now=datetime(2026, 9, 29, 6, 0, tzinfo=UTC),
        )
        assert dispatch is not None
        assert dispatch.current_document_id == new_document_id
        observation, _consumption, consume_outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch.id,
            service_executor_id=_SERVICE_ID,
            now=datetime(2026, 9, 29, 6, 0, tzinfo=UTC),
        )
        assert consume_outcome == "consumed"
        assert observation.current_document_id == new_document_id
        assert observation.current_version_number == new_version_number
        assert observation.result_status == "unchanged"
        assert observation.baseline_projection_hash == transition.baseline_projection_hash

    assert transition_id is not None
