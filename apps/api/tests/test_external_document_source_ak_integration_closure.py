from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

import app.modules.external_document_sources.change_detection_service as change_detection_service
import app.modules.external_document_sources.due_tick_observation_service as due_tick_observation_service
import app.modules.external_document_sources.family_version_admission_service as family_version_admission_service
import app.modules.external_document_sources.observation_refresh_execution_service as observation_refresh_execution_service
import app.modules.external_document_sources.recurring_observation_schedule_service as recurring_observation_schedule_service
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_models import (
    ExternalDocumentSourceDueTickDispatchConsumption,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_models import (
    ExternalDocumentSourceDueTickDispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.models import ExternalDocumentSourceProfile
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_models import (
    ExternalDocumentSourceObservationRefreshAdmissionExecution,
)
from app.modules.external_document_sources.observation_refresh_admission_execution_service import (
    execute_observation_refresh_admission,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
)
from app.modules.external_document_sources.observation_refresh_execution_service import (
    execute_observation_refresh_authorization,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    decide_observation_review_handoff,
)
from app.modules.external_document_sources.observation_review_handoff_models import (
    ExternalDocumentSourceObservationReviewHandoff,
)
from app.modules.external_document_sources.observation_review_handoff_service import (
    project_observation_review_handoff,
)
from app.modules.external_document_sources.operator_read_model_service import (
    build_external_document_source_operator_overview,
)
from app.modules.external_document_sources.recurring_observation_schedule_models import (
    ExternalDocumentSourceRecurringObservationSchedule,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    RemoteFileContentReadResult,
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
)
from app.modules.processing.models import DocumentProcessingJob
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _RAW_ITEM_ID
from tests.test_external_document_source_discovery import _headers
from tests.test_external_document_source_family_version_admission import _bound_v1
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _EXEC_REASON,
    _authorized_refresh,
    _enable_clean_aj,
    setup_function as _aj_setup,
    teardown_function as _aj_teardown,
)
from tests.test_external_document_source_recurring_observation_schedule import (
    _authorize as _authorize_schedule,
    _mfa_headers,
)
from tests.test_external_document_source_remote_content_staging import _QuarantineStore


def setup_function() -> None:
    _aj_setup()


def teardown_function() -> None:
    _aj_teardown()


def test_phase_ak_changed_recurring_loop_closes_through_exact_n_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose the already-governed recurring chain into one AK acceptance path.

    The helper intentionally traverses initial admission/binding, recurring schedule,
    due dispatch + service consumption, changed metadata observation, human AG review,
    AH exact content refresh/staging and AI admission authorization before returning.
    AK then executes AJ and verifies the canonical version and processing boundary.
    """

    (
        actor_id,
        profile_id,
        organization_id,
        claim_id,
        prior_document_id,
        _refresh_id,
        admission_authorization_id,
        binding_id,
        metadata_adapter,
        read_adapter,
        store,
    ) = _authorized_refresh(monkeypatch, "ak-compose")
    _enable_clean_aj(monkeypatch)

    provider_calls_before_aj = (metadata_adapter.calls, read_adapter.calls)
    staged_reads_before_aj = (store.head_calls, store.get_calls)

    with TestingSessionLocal() as db:
        assert (
            db.query(ExternalDocumentSourceRecurringObservationSchedule).count()
            == 1
        )
        assert db.query(ExternalDocumentSourceDueTickDispatch).count() == 1
        assert (
            db.query(ExternalDocumentSourceDueTickDispatchConsumption).count()
            == 1
        )
        observations = db.query(
            ExternalDocumentSourceDueTickObservationExecution
        ).all()
        assert len(observations) == 1
        assert observations[0].result_status == "changed"

        handoffs = db.query(ExternalDocumentSourceObservationReviewHandoff).all()
        assert len(handoffs) == 1
        assert handoffs[0].result_status == "changed"

        decisions = db.query(ExternalDocumentSourceObservationReviewDecision).all()
        assert len(decisions) == 1
        assert decisions[0].decision_kind == "approve_refresh"
        assert decisions[0].status == "refresh_authorized"
        assert decisions[0].ai_executed is False

        refresh_authorizations = db.query(
            ExternalDocumentSourceObservationRefreshAuthorization
        ).all()
        assert len(refresh_authorizations) == 1
        assert refresh_authorizations[0].status == "authorized"

        refreshes = db.query(
            ExternalDocumentSourceObservationRefreshExecution
        ).all()
        assert len(refreshes) == 1
        assert refreshes[0].result_status == "staged_refresh_verified"
        assert refreshes[0].remote_write_performed is False
        assert refreshes[0].remote_delete_performed is False
        assert refreshes[0].ai_executed is False

        admission_authorizations = db.query(
            ExternalDocumentSourceObservationRefreshAdmissionAuthorization
        ).all()
        assert len(admission_authorizations) == 1
        assert admission_authorizations[0].status == "authorized"
        assert admission_authorizations[0].remote_write_performed is False
        assert admission_authorizations[0].remote_delete_performed is False
        assert admission_authorizations[0].ai_executed is False

        before_admission = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        family_before_admission = next(
            row for row in before_admission.families if row.binding_id == binding_id
        )
        assert family_before_admission.refresh_execution_required is False
        assert family_before_admission.admission_authorization_required is False
        assert family_before_admission.admission_execution_required is True

        execution, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="ak-compose-aj",
            execution_reason=_EXEC_REASON,
        )
        assert outcome == "admitted"
        assert execution.status == "admitted"
        assert execution.prior_document_id == prior_document_id
        assert execution.prior_version_number == 1
        assert execution.new_version_number == 2
        assert execution.exactly_one_current_version_established is True
        assert execution.processing_enqueued is False
        assert execution.ai_executed is False
        assert execution.remote_write_performed is False
        assert execution.remote_delete_performed is False

        prior = db.get(Document, prior_document_id)
        current = db.get(Document, execution.new_document_id)
        assert prior is not None and current is not None
        assert prior.is_current is False
        assert current.is_current is True
        assert current.version_number == 2
        assert current.supersedes_document_id == prior.id
        assert current.document_family_id == prior.document_family_id

        assert (
            db.query(Document)
            .filter(
                Document.claim_id == claim_id,
                Document.document_family_id == current.document_family_id,
                Document.is_current.is_(True),
                Document.deleted_at.is_(None),
            )
            .count()
            == 1
        )
        assert db.query(DocumentProcessingJob).count() == 0

        after_admission = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        family_after_admission = next(
            row for row in after_admission.families if row.binding_id == binding_id
        )
        assert family_after_admission.current_document_id == execution.new_document_id
        assert family_after_admission.current_version_number == 2
        assert family_after_admission.refresh_execution_required is False
        assert family_after_admission.admission_authorization_required is False
        assert family_after_admission.admission_execution_required is False
        assert family_after_admission.processing_release_required is True

        execution_id = execution.id
        new_document_id = execution.new_document_id

    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before_aj
    assert store.head_calls == staged_reads_before_aj[0] + 1
    assert store.get_calls == staged_reads_before_aj[1] + 1

    with TestingSessionLocal() as db:
        replay, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="ak-compose-aj",
            execution_reason=_EXEC_REASON,
        )
        assert outcome == "replayed"
        assert replay.id == execution_id
        assert replay.new_document_id == new_document_id
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionExecution
            ).count()
            == 1
        )
        assert db.query(DocumentProcessingJob).count() == 0

    assert (metadata_adapter.calls, read_adapter.calls) == provider_calls_before_aj
