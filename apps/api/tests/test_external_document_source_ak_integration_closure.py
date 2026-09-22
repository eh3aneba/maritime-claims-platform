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


class _AkGoogleMetadataAdapter:
    adapter_kind = "deterministic_ak_google_metadata_v1"
    provider_kind = "google_drive"
    client_kind = "google_drive_transient_v3"
    observation_operation_kind = "drive_file_metadata_read_v1"
    provider_origin = "https://www.googleapis.com"

    def __init__(self, *, body: bytes, version: str):
        self.body = body
        self.version = version
        self.calls = 0
        self.last_policy = None

    def read_item_metadata(self, locator, policy):
        self.calls += 1
        self.last_policy = policy
        assert policy.provider_kind == "google_drive"
        assert policy.client_kind == self.client_kind
        assert policy.observation_operation_kind == self.observation_operation_kind
        assert policy.provider_origin == self.provider_origin
        assert f"/drive/v3/files/{_RAW_ITEM_ID}" in policy.metadata_endpoint_url
        assert "supportsAllDrives=true" in policy.metadata_endpoint_url
        assert "version" in policy.field_projection
        assert policy.allow_redirects is False
        return ExactItemMetadataResult(
            found=True,
            item=RemoteMetadataItemProjection(
                provider_item_id=_RAW_ITEM_ID,
                parent_item_id="google-folder-root",
                item_kind="file",
                display_name="AK Google Survey Report.pdf",
                mime_type_class="application/pdf",
                byte_size=len(self.body),
                modified_at=datetime(2026, 9, 22, 2, 0, tzinfo=UTC),
                version_token_hash=self.version,
            ),
        )


class _AkGoogleContentAdapter:
    adapter_kind = "deterministic_ak_google_content_v1"
    provider_kind = "google_drive"
    client_kind = "google_drive_transient_v3"
    read_operation_kind = "drive_file_media_read_v1"
    provider_origin = "https://www.googleapis.com"
    redirect_policy_kind = "no_redirects_v1"

    def __init__(self, *, body: bytes, version: str):
        self.body = body
        self.version = version
        self.calls = 0
        self.last_policy = None

    def read_content(self, locator, policy):
        self.calls += 1
        self.last_policy = policy
        assert policy.provider_kind == "google_drive"
        assert policy.client_kind == self.client_kind
        assert policy.read_operation_kind == self.read_operation_kind
        assert policy.provider_origin == self.provider_origin
        assert policy.redirect_policy_kind == self.redirect_policy_kind
        assert policy.max_redirects == 0
        assert f"/drive/v3/files/{_RAW_ITEM_ID}" in policy.content_endpoint_url
        assert "alt=media" in policy.content_endpoint_url
        assert "supportsAllDrives=true" in policy.content_endpoint_url
        return RemoteFileContentReadResult(
            read=True,
            content=self.body,
            media_type_class="application/pdf",
            observed_version_token_hash=self.version,
            latency_class="normal",
        )


def test_phase_ak_google_drive_changed_recurring_loop_reaches_exact_n_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the Google Drive recurring contract from a governed bound v1 through AJ.

    Earlier A→Y tests already prove creation/admission/binding integrity. This AK
    acceptance deliberately starts at that governed bound baseline, swaps only
    the provider-specific recurring context to a separately approved Google Drive
    profile, and then exercises the real schedule/dispatch/AG/AH/AI/AJ services.
    """

    (
        actor_id,
        _sharepoint_profile_id,
        claim_id,
        initial_execution,
        binding_body,
    ) = _bound_v1(monkeypatch, "ak-google-baseline")
    binding_id = UUID(binding_body["id"])
    prior_document_id = UUID(initial_execution["document_id"])

    with TestingSessionLocal() as db:
        binding = db.get(ExternalDocumentSourceEvidenceFamilyBinding, binding_id)
        assert binding is not None
        assert hashlib.sha256(_RAW_ITEM_ID.encode("utf-8")).hexdigest() == binding.stable_source_item_hash

        lineage_observation, lineage_checkpoint, _profile, lineage_locator, _policy = (
            due_tick_observation_service._provider_lineage(db, binding)
        )
        lineage_observation_id = lineage_observation.id
        lineage_checkpoint_id = lineage_checkpoint.id
        organization_id = binding.organization_id

        approver = (
            db.query(User)
            .filter(
                User.organization_id == organization_id,
                User.role == UserRole.ADMIN,
                User.id != actor_id,
                User.is_active.is_(True),
            )
            .first()
        )
        assert approver is not None
        approver_id = approver.id

    requested = client.post(
        "/api/v1/external-document-sources/profiles",
        headers=_headers(actor_id),
        json={
            "provider_kind": "google_drive",
            "display_name": "AK Google Drive fixture",
            "config": {
                "shared_drive_id": "ak-drive-001",
                "folder_id": "ak-folder-001",
            },
            "reason": "Govern the Google Drive source used by the AK recurring integration acceptance.",
        },
    )
    assert requested.status_code == 201, requested.text
    google_profile_id = UUID(requested.json()["id"])
    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{google_profile_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": "Independently approve the Google Drive scope used by the AK recurring acceptance."
        },
    )
    assert approved.status_code == 200, approved.text

    with TestingSessionLocal() as db:
        google_profile = db.get(ExternalDocumentSourceProfile, google_profile_id)
        assert google_profile is not None
        assert google_profile.status == "active"
        binding = db.get(ExternalDocumentSourceEvidenceFamilyBinding, binding_id)
        assert binding is not None
        binding.profile_id = google_profile_id
        binding.provider_kind = "google_drive"
        binding.profile_hash = google_profile.profile_hash
        db.commit()
        google_profile_hash = google_profile.profile_hash

    # The provider-neutral recurring chain needs only the already-proven bound
    # baseline. Avoid re-running A→Y while still exercising every recurring
    # authority transition and the real Google Drive policy/operation mapping.
    def _skip_binding_integrity(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        recurring_observation_schedule_service,
        "_ensure_binding_integrity",
        _skip_binding_integrity,
    )
    monkeypatch.setattr(
        family_version_admission_service,
        "_ensure_binding_integrity",
        _skip_binding_integrity,
    )
    monkeypatch.setattr(
        due_tick_observation_service,
        "_ensure_binding_integrity",
        _skip_binding_integrity,
    )

    def _google_provider_lineage(db, _binding):
        profile = db.get(ExternalDocumentSourceProfile, google_profile_id)
        assert profile is not None
        policy = change_detection_service._policy(
            "google_drive",
            profile.normalized_config,
            _RAW_ITEM_ID,
        )
        return (
            SimpleNamespace(id=lineage_observation_id),
            SimpleNamespace(id=lineage_checkpoint_id),
            profile,
            lineage_locator,
            policy,
        )

    fake_listing_item = SimpleNamespace(
        provider_item_id=_RAW_ITEM_ID,
        item_kind="file",
        mime_type_class="application/pdf",
    )

    def _google_generation3_lineage(db, _checkpoint):
        profile = db.get(ExternalDocumentSourceProfile, google_profile_id)
        assert profile is not None
        return (
            None,
            None,
            None,
            fake_listing_item,
            profile,
            lineage_locator,
            None,
            None,
            None,
        )

    monkeypatch.setattr(
        due_tick_observation_service,
        "_provider_lineage",
        _google_provider_lineage,
    )
    monkeypatch.setattr(
        observation_refresh_execution_service,
        "_provider_lineage",
        _google_provider_lineage,
    )
    monkeypatch.setattr(
        observation_refresh_execution_service,
        "_generation3_lineage",
        _google_generation3_lineage,
    )

    changed_body = b"google-ak-refresh-" * 257
    changed_version = "9" * 64
    metadata_adapter = _AkGoogleMetadataAdapter(
        body=changed_body,
        version=changed_version,
    )
    content_adapter = _AkGoogleContentAdapter(
        body=changed_body,
        version=changed_version,
    )
    register_external_document_source_change_detection_adapter(
        "google_drive",
        "drive_file_metadata_read_v1",
        metadata_adapter,
    )
    register_external_document_source_remote_file_content_read_adapter(
        "google_drive",
        "drive_file_media_read_v1",
        content_adapter,
    )
    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    schedule_response = _authorize_schedule(
        str(google_profile_id),
        str(binding_id),
        actor_id,
        key="ak-google-schedule",
        cadence="hourly",
        effective_at="2026-09-22T00:00:00Z",
        headers=_mfa_headers(actor_id),
    )
    assert schedule_response.status_code == 201, schedule_response.text

    with TestingSessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id="ak-google-scheduler",
            now=datetime(2026, 9, 22, 0, 0, tzinfo=UTC),
        )
        assert dispatch is not None
        assert dispatch.provider_kind == "google_drive"
        assert dispatch.profile_id == google_profile_id

        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch.id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 22, 0, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        assert observation.result_status == "changed"
        assert observation.provider_kind == "google_drive"
        assert observation.profile_hash == google_profile_hash
        assert observation.observed_version_token_hash == changed_version

        handoff, projected = project_observation_review_handoff(
            db,
            observation_execution_id=observation.id,
            projector_id="external-evidence-review-projector-v1",
            now=datetime(2026, 9, 22, 0, 1, tzinfo=UTC),
        )
        assert projected == "projected"
        assert handoff is not None
        assert handoff.result_status == "changed"

        decision, refresh_authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=google_profile_id,
            handoff_id=handoff.id,
            decided_by_id=actor_id,
            request_key="ak-google-ag",
            decision_kind="approve_refresh",
            decision_reason="Human reviewer approves this exact changed Google Drive version for one refresh.",
            now=datetime(2026, 9, 22, 0, 2, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert decision.decision_kind == "approve_refresh"
        assert decision.ai_executed is False
        assert refresh_authorization is not None

        refresh, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=google_profile_id,
            authorization_id=refresh_authorization.id,
            requested_by_id=actor_id,
            request_key="ak-google-ah",
            request_reason="Read and quarantine-stage only the exact approved Google Drive changed version.",
            now=datetime(2026, 9, 22, 0, 3, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert refresh.result_status == "staged_refresh_verified"
        assert refresh.provider_kind == "google_drive"
        assert refresh.content_version_token_hash == changed_version
        assert refresh.remote_write_performed is False
        assert refresh.remote_delete_performed is False
        assert refresh.ai_executed is False

        admission_authorization, outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=google_profile_id,
            refresh_execution_id=refresh.id,
            authorized_by_id=actor_id,
            request_key="ak-google-ai",
            authorization_reason=(
                "Authorize only this exact staged Google Drive refresh for a later canonical N+1 admission."
            ),
            now=datetime(2026, 9, 22, 0, 4, tzinfo=UTC),
        )
        assert outcome == "authorized"
        assert admission_authorization.provider_kind == "google_drive"
        assert admission_authorization.ai_executed is False

    _enable_clean_aj(monkeypatch)

    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=google_profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization.id,
            executed_by_id=actor_id,
            request_key="ak-google-aj",
            execution_reason=_EXEC_REASON,
        )
        assert outcome == "admitted"
        assert execution.status == "admitted"
        assert execution.prior_document_id == prior_document_id
        assert execution.prior_version_number == 1
        assert execution.new_version_number == 2
        assert execution.remote_write_performed is False
        assert execution.remote_delete_performed is False
        assert execution.ai_executed is False
        assert execution.processing_enqueued is False

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

        overview = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        row = next(item for item in overview.families if item.binding_id == binding_id)
        assert row.provider_kind == "google_drive"
        assert row.current_document_id == execution.new_document_id
        assert row.current_version_number == 2
        assert row.processing_release_required is True

    assert metadata_adapter.calls == 1
    assert content_adapter.calls == 1
    assert store.put_calls == 1
