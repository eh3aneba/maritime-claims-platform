from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.credential_reference_health_service import (
    CredentialReferenceHealthProbeResult,
    register_external_document_source_credential_reference_health_resolver,
)
from app.modules.external_document_sources.credential_resolution_execution_service import (
    CredentialReferenceResolutionResult,
    register_external_document_source_credential_resolution_resolver,
)
from app.modules.external_document_sources.discovery_service import (
    ExternalDocumentSourceMetadataItem,
    register_external_document_source_discovery_adapter,
)
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_due_tick_dispatch,
)
from app.modules.external_document_sources.due_tick_dispatch_service import (
    dispatch_next_due_tick,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_models import (
    ExternalDocumentSourceObservationRefreshAdmissionAuthorization,
)
from app.modules.external_document_sources.observation_refresh_admission_authorization_service import (
    authorize_observation_refresh_admission,
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
from app.modules.external_document_sources.processing_release_models import (
    ExternalDocumentSourceProcessingRelease,
)
from app.modules.external_document_sources.provider_client_health_service import (
    ProviderClientHealthResult,
    register_external_document_source_provider_client_health_adapter,
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
    RemoteMetadataListResult,
    register_external_document_source_remote_metadata_list_adapter,
)
from app.modules.external_document_sources.token_acquisition_execution_service import (
    TokenAcquisitionResult,
    register_external_document_source_token_acquirer,
)
from app.modules.processing.models import DocumentProcessingJob
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _detect
from tests.test_external_document_source_checkpoint_generation import (
    _advance as _advance_generation_2,
)
from tests.test_external_document_source_checkpoint_generation_3 import (
    _advance as _advance_generation_3,
)
from tests.test_external_document_source_connection_authorization import (
    _approve_authorization,
    _request_authorization,
)
from tests.test_external_document_source_connection_bootstrap import (
    _execute as _execute_connection_bootstrap,
)
from tests.test_external_document_source_credential_reference import (
    _approve_binding as _approve_credential_binding,
    _request_binding as _request_credential_binding,
)
from tests.test_external_document_source_credential_reference_health import _qualify
from tests.test_external_document_source_credential_resolution_execution import _resolve
from tests.test_external_document_source_discovery import (
    _discover,
    _headers,
    _seed_tenant,
)
from tests.test_external_document_source_evidence_admission_authorization import (
    _authorize as _authorize_evidence_admission,
    _seed_claim,
)
from tests.test_external_document_source_evidence_admission_execution import (
    _enable_clean_admission,
    _execute as _execute_evidence_admission,
)
from tests.test_external_document_source_evidence_family_binding import (
    _bind as _bind_evidence_family,
)
from tests.test_external_document_source_generation_3_change_detection import (
    _observe as _observe_generation_3,
)
from tests.test_external_document_source_observation_refresh_admission_execution import (
    _EXEC_REASON as _AJ_EXEC_REASON,
    _enable_clean_aj,
    setup_function as _aj_setup,
    teardown_function as _aj_teardown,
)
from tests.test_external_document_source_observation_review_decision import _mfa_headers
from tests.test_external_document_source_provider_client_activation_authorization import (
    _approve as _approve_activation,
    _request as _request_activation,
)
from tests.test_external_document_source_provider_client_activation_execution import (
    _execute as _execute_activation,
)
from tests.test_external_document_source_provider_client_health import _health
from tests.test_external_document_source_recurring_observation_schedule import (
    _authorize as _authorize_schedule,
)
from tests.test_external_document_source_remote_content_staging import (
    _QuarantineStore,
    _stage,
)
from tests.test_external_document_source_remote_file_content_read import _read_content
from tests.test_external_document_source_remote_metadata_listing import _list_metadata
from tests.test_external_document_source_successor_change_detection import (
    _observe as _observe_successor,
)
from tests.test_external_document_source_successor_versioned_restaging import (
    _restage_successor,
)
from tests.test_external_document_source_sync_checkpoint import _checkpoint
from tests.test_external_document_source_token_acquisition_execution import _acquire
from tests.test_external_document_source_versioned_restaging import _restage


_ITEM_ID = "google-drive-file-ak-001"
_PARENT_ID = "google-drive-folder-ak-root"
_NAME = "Google Drive AK Survey Report.pdf"
_MIME = "application/pdf"

_BODY_V1 = b"google-drive-ak-v1-" * 256
_BODY_V2 = b"google-drive-ak-v2-" * 256
_BODY_V3 = b"google-drive-ak-v3-" * 256
_BODY_V4 = b"google-drive-ak-v4-refresh-" * 256

_VERSION_V1 = "a" * 64
_VERSION_V2 = "c" * 64
_VERSION_V3 = "d" * 64
_VERSION_V4 = "f" * 64

_MODIFIED_V1 = datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
_MODIFIED_V2 = datetime(2026, 9, 20, 2, 0, tzinfo=UTC)
_MODIFIED_V3 = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
_MODIFIED_V4 = datetime(2026, 9, 22, 0, 30, tzinfo=UTC)


def setup_function() -> None:
    _aj_setup()


def teardown_function() -> None:
    _aj_teardown()


class _GoogleDiscoveryAdapter:
    adapter_kind = "deterministic_google_drive_discovery_v1"

    def list_metadata(
        self,
        *,
        provider_kind: str,
        normalized_config: dict[str, str],
        max_results: int,
    ):
        assert provider_kind == "google_drive"
        assert normalized_config["shared_drive_id"] == "drive-ak-001"
        return [
            ExternalDocumentSourceMetadataItem(
                provider_item_id=_ITEM_ID,
                parent_item_id=_PARENT_ID,
                display_name=_NAME,
                item_kind="file",
                mime_type=_MIME,
                size_bytes=len(_BODY_V1),
                modified_at=_MODIFIED_V1,
                provider_etag="google-ak-discovery-etag",
            )
        ][:max_results]


class _GoogleCredentialHealthResolver:
    resolver_kind = "deterministic_google_secret_health_v1"

    def check(self, locator):
        assert locator.backend == "gcp_secret_manager"
        assert locator.namespace == "mcri-prod"
        assert locator.name == "google-drive-provider-credential"
        return CredentialReferenceHealthProbeResult(resolvable=True)


class _GoogleCredentialResolutionResolver:
    resolver_kind = "deterministic_google_secret_resolution_v1"

    def resolve(self, locator):
        assert locator.backend == "gcp_secret_manager"
        return CredentialReferenceResolutionResult(resolved=True)


class _GoogleTokenAcquirer:
    acquirer_kind = "deterministic_google_drive_token_v1"
    provider_kind = "google_drive"
    token_flow_kind = "jwt_bearer"
    token_endpoint_origin = "https://oauth2.googleapis.com"

    def __init__(self):
        self.calls = 0

    def acquire(self, locator, policy):
        self.calls += 1
        assert locator.backend == "gcp_secret_manager"
        assert policy.provider_kind == "google_drive"
        assert policy.token_flow_kind == "jwt_bearer"
        assert policy.token_endpoint_url == "https://oauth2.googleapis.com/token"
        assert policy.audience_kind == "google_drive_readonly"
        return TokenAcquisitionResult(acquired=True, expiry_class="standard")


class _GoogleHealthAdapter:
    adapter_kind = "deterministic_google_drive_health_v1"
    provider_kind = "google_drive"
    client_kind = "google_drive_transient_v3"
    health_operation_kind = "drive_about_health"
    provider_origin = "https://www.googleapis.com"

    def __init__(self):
        self.calls = 0

    def qualify(self, locator, policy):
        self.calls += 1
        assert policy.provider_kind == "google_drive"
        assert policy.health_operation_kind == "drive_about_health"
        assert policy.provider_origin == "https://www.googleapis.com"
        return ProviderClientHealthResult(
            healthy=True,
            latency_class="normal",
        )


class _GoogleListAdapter:
    adapter_kind = "deterministic_google_drive_list_v1"
    provider_kind = "google_drive"
    client_kind = "google_drive_transient_v3"
    listing_operation_kind = "drive_files_list_metadata_v1"
    provider_origin = "https://www.googleapis.com"

    def __init__(self):
        self.calls = 0

    def list_metadata(self, locator, policy):
        self.calls += 1
        assert policy.provider_kind == "google_drive"
        assert policy.listing_operation_kind == "drive_files_list_metadata_v1"
        assert "drive/v3/files?" in policy.listing_endpoint_url
        return RemoteMetadataListResult(
            listed=True,
            items=(
                RemoteMetadataItemProjection(
                    provider_item_id=_ITEM_ID,
                    parent_item_id=_PARENT_ID,
                    item_kind="file",
                    display_name=_NAME,
                    mime_type_class=_MIME,
                    byte_size=len(_BODY_V1),
                    modified_at=_MODIFIED_V1,
                    version_token_hash=_VERSION_V1,
                ),
            ),
            truncated=False,
            page_count=1,
        )


class _GoogleReadAdapter:
    adapter_kind = "deterministic_google_drive_content_v1"
    provider_kind = "google_drive"
    client_kind = "google_drive_transient_v3"
    read_operation_kind = "drive_file_media_read_v1"
    provider_origin = "https://www.googleapis.com"
    redirect_policy_kind = "no_redirects_v1"

    def __init__(self, *, content: bytes, version: str):
        self.content = content
        self.version = version
        self.calls = 0

    def read_content(self, locator, policy):
        self.calls += 1
        assert policy.provider_kind == "google_drive"
        assert policy.read_operation_kind == "drive_file_media_read_v1"
        assert policy.provider_origin == "https://www.googleapis.com"
        assert policy.max_redirects == 0
        assert "drive/v3/files/" in policy.content_endpoint_url
        assert "alt=media" in policy.content_endpoint_url
        return RemoteFileContentReadResult(
            read=True,
            content=self.content,
            media_type_class=_MIME,
            observed_version_token_hash=self.version,
            latency_class="normal",
        )


class _GoogleMetadataAdapter:
    adapter_kind = "deterministic_google_drive_exact_metadata_v1"
    provider_kind = "google_drive"
    client_kind = "google_drive_transient_v3"
    observation_operation_kind = "drive_file_metadata_read_v1"
    provider_origin = "https://www.googleapis.com"

    def __init__(self, *, body: bytes, version: str, modified_at: datetime):
        self.calls = 0
        self.result = ExactItemMetadataResult(
            found=True,
            item=RemoteMetadataItemProjection(
                provider_item_id=_ITEM_ID,
                parent_item_id=_PARENT_ID,
                item_kind="file",
                display_name=_NAME,
                mime_type_class=_MIME,
                byte_size=len(body),
                modified_at=modified_at,
                version_token_hash=version,
            ),
        )

    def read_item_metadata(self, locator, policy):
        self.calls += 1
        assert policy.provider_kind == "google_drive"
        assert policy.observation_operation_kind == "drive_file_metadata_read_v1"
        assert policy.provider_origin == "https://www.googleapis.com"
        assert f"/drive/v3/files/{_ITEM_ID}?" in policy.metadata_endpoint_url
        assert "version" in policy.field_projection
        return self.result


def _create_google_profile(requester_id, approver_id) -> str:
    requested = client.post(
        "/api/v1/external-document-sources/profiles",
        headers=_headers(requester_id),
        json={
            "provider_kind": "google_drive",
            "display_name": "AK Google Drive Evidence",
            "config": {
                "shared_drive_id": "drive-ak-001",
                "folder_id": "folder-ak-001",
            },
            "reason": (
                "Govern the Google Drive evidence source before any bounded "
                "read-only provider activity is authorized."
            ),
        },
    )
    assert requested.status_code == 201, requested.text
    profile_id = requested.json()["id"]
    approved = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/approve",
        headers=_headers(approver_id),
        json={
            "reason": (
                "Independently approve the bounded Google Drive source scope "
                "without granting file mutation authority."
            )
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    return profile_id


def _google_bound_v1(monkeypatch: pytest.MonkeyPatch):
    organization_id, requester_id, approver_id = _seed_tenant("ak-google-drive")
    profile_id = _create_google_profile(requester_id, approver_id)

    register_external_document_source_discovery_adapter(
        "google_drive",
        _GoogleDiscoveryAdapter(),
    )
    discovery = _discover(
        profile_id,
        requester_id,
        key="ak-google-discovery",
    )
    assert discovery.status_code == 201, discovery.text
    discovery_id = discovery.json()["id"]

    connection = _request_authorization(
        profile_id,
        discovery_id,
        requester_id,
        key="ak-google-connection-authorization",
    )
    assert connection.status_code == 201, connection.text
    connection_id = connection.json()["id"]
    approved_connection = _approve_authorization(
        profile_id,
        connection_id,
        approver_id,
    )
    assert approved_connection.status_code == 200, approved_connection.text

    bootstrap = _execute_connection_bootstrap(
        profile_id,
        connection_id,
        requester_id,
        key="ak-google-bootstrap",
    )
    assert bootstrap.status_code == 201, bootstrap.text

    credential = _request_credential_binding(
        profile_id,
        bootstrap.json()["id"],
        requester_id,
        key="ak-google-credential-reference",
        backend="gcp_secret_manager",
        namespace="mcri-prod",
        name="google-drive-provider-credential",
        version="v1",
    )
    assert credential.status_code == 201, credential.text
    credential_id = credential.json()["id"]
    approved_credential = _approve_credential_binding(
        profile_id,
        credential_id,
        approver_id,
    )
    assert approved_credential.status_code == 200, approved_credential.text

    register_external_document_source_credential_reference_health_resolver(
        "gcp_secret_manager",
        _GoogleCredentialHealthResolver(),
    )
    qualified = _qualify(
        profile_id,
        credential_id,
        requester_id,
        key="ak-google-credential-health",
    )
    assert qualified.status_code == 201, qualified.text
    assert qualified.json()["result_status"] == "resolvable"

    activation = _request_activation(
        profile_id,
        qualified.json()["id"],
        requester_id,
        key="ak-google-activation-authorization",
    )
    assert activation.status_code == 201, activation.text
    activation_id = activation.json()["id"]
    approved_activation = _approve_activation(
        profile_id,
        activation_id,
        approver_id,
    )
    assert approved_activation.status_code == 200, approved_activation.text

    activated = _execute_activation(
        profile_id,
        activation_id,
        requester_id,
        key="ak-google-activation",
    )
    assert activated.status_code == 201, activated.text

    register_external_document_source_credential_resolution_resolver(
        "gcp_secret_manager",
        _GoogleCredentialResolutionResolver(),
    )
    resolved = _resolve(
        profile_id,
        activated.json()["id"],
        requester_id,
        key="ak-google-resolution",
    )
    assert resolved.status_code == 201, resolved.text

    token_adapter = _GoogleTokenAcquirer()
    register_external_document_source_token_acquirer(
        "google_drive",
        "jwt_bearer",
        token_adapter,
    )
    acquired = _acquire(
        profile_id,
        resolved.json()["id"],
        requester_id,
        key="ak-google-token",
    )
    assert acquired.status_code == 201, acquired.text
    assert token_adapter.calls == 1

    health_adapter = _GoogleHealthAdapter()
    register_external_document_source_provider_client_health_adapter(
        "google_drive",
        "drive_about_health",
        health_adapter,
    )
    healthy = _health(
        profile_id,
        acquired.json()["id"],
        requester_id,
        key="ak-google-provider-health",
    )
    assert healthy.status_code == 201, healthy.text
    assert health_adapter.calls == 1

    list_adapter = _GoogleListAdapter()
    register_external_document_source_remote_metadata_list_adapter(
        "google_drive",
        "drive_files_list_metadata_v1",
        list_adapter,
    )
    listed = _list_metadata(
        profile_id,
        healthy.json()["id"],
        requester_id,
        key="ak-google-list",
    )
    assert listed.status_code == 201, listed.text
    file_item = listed.json()["items"][0]
    assert file_item["item_kind"] == "file"
    assert list_adapter.calls == 1

    initial_read = _GoogleReadAdapter(content=_BODY_V1, version=_VERSION_V1)
    register_external_document_source_remote_file_content_read_adapter(
        "google_drive",
        "drive_file_media_read_v1",
        initial_read,
    )
    read = _read_content(
        profile_id,
        listed.json()["id"],
        file_item["id"],
        requester_id,
        key="ak-google-read-v1",
    )
    assert read.status_code == 201, read.text
    assert initial_read.calls == 1

    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)
    staged = _stage(
        profile_id,
        read.json()["id"],
        requester_id,
        key="ak-google-stage-v1",
    )
    assert staged.status_code == 201, staged.text

    checkpoint = _checkpoint(
        profile_id,
        staged.json()["id"],
        requester_id,
        key="ak-google-checkpoint-v1",
    )
    assert checkpoint.status_code == 201, checkpoint.text

    changed_v2 = _GoogleMetadataAdapter(
        body=_BODY_V2,
        version=_VERSION_V2,
        modified_at=_MODIFIED_V2,
    )
    register_external_document_source_change_detection_adapter(
        "google_drive",
        "drive_file_metadata_read_v1",
        changed_v2,
    )
    observed_v2 = _detect(
        profile_id,
        checkpoint.json()["id"],
        requester_id,
        key="ak-google-observe-v2",
    )
    assert observed_v2.status_code == 201, observed_v2.text
    assert observed_v2.json()["result_status"] == "changed"

    read_v2 = _GoogleReadAdapter(content=_BODY_V2, version=_VERSION_V2)
    register_external_document_source_remote_file_content_read_adapter(
        "google_drive",
        "drive_file_media_read_v1",
        read_v2,
    )
    staged_v2 = _restage(
        profile_id,
        observed_v2.json()["id"],
        requester_id,
        key="ak-google-restage-v2",
    )
    assert staged_v2.status_code == 201, staged_v2.text

    checkpoint_v2 = _advance_generation_2(
        profile_id,
        staged_v2.json()["id"],
        requester_id,
        key="ak-google-checkpoint-v2",
    )
    assert checkpoint_v2.status_code == 201, checkpoint_v2.text

    changed_v3 = _GoogleMetadataAdapter(
        body=_BODY_V3,
        version=_VERSION_V3,
        modified_at=_MODIFIED_V3,
    )
    register_external_document_source_change_detection_adapter(
        "google_drive",
        "drive_file_metadata_read_v1",
        changed_v3,
    )
    observed_v3 = _observe_successor(
        profile_id,
        checkpoint_v2.json()["id"],
        requester_id,
        key="ak-google-observe-v3",
    )
    assert observed_v3.status_code == 201, observed_v3.text
    assert observed_v3.json()["result_status"] == "changed"

    read_v3 = _GoogleReadAdapter(content=_BODY_V3, version=_VERSION_V3)
    register_external_document_source_remote_file_content_read_adapter(
        "google_drive",
        "drive_file_media_read_v1",
        read_v3,
    )
    staged_v3 = _restage_successor(
        profile_id,
        observed_v3.json()["id"],
        requester_id,
        key="ak-google-restage-v3",
    )
    assert staged_v3.status_code == 201, staged_v3.text

    checkpoint_v3 = _advance_generation_3(
        profile_id,
        staged_v3.json()["id"],
        requester_id,
        key="ak-google-checkpoint-v3",
    )
    assert checkpoint_v3.status_code == 201, checkpoint_v3.text

    unchanged_v3 = _GoogleMetadataAdapter(
        body=_BODY_V3,
        version=_VERSION_V3,
        modified_at=_MODIFIED_V3,
    )
    register_external_document_source_change_detection_adapter(
        "google_drive",
        "drive_file_metadata_read_v1",
        unchanged_v3,
    )
    observed_current = _observe_generation_3(
        profile_id,
        checkpoint_v3.json()["id"],
        requester_id,
        key="ak-google-observe-current",
    )
    assert observed_current.status_code == 201, observed_current.text
    assert observed_current.json()["result_status"] == "unchanged"

    claim_id = _seed_claim(requester_id, "ak-google-drive")
    authorized = _authorize_evidence_admission(
        profile_id,
        observed_current.json()["id"],
        claim_id,
        requester_id,
        key="ak-google-evidence-authorize",
    )
    assert authorized.status_code == 201, authorized.text

    _enable_clean_admission(monkeypatch)
    admitted = _execute_evidence_admission(
        profile_id,
        authorized.json()["id"],
        requester_id,
        key="ak-google-evidence-admit",
    )
    assert admitted.status_code == 201, admitted.text

    bound = _bind_evidence_family(
        profile_id,
        admitted.json()["id"],
        requester_id,
        key="ak-google-family-bind",
    )
    assert bound.status_code == 201, bound.text
    assert bound.json()["provider_kind"] == "google_drive"

    return (
        requester_id,
        UUID(profile_id),
        organization_id,
        claim_id,
        admitted.json(),
        bound.json(),
        store,
    )


def test_phase_ak_google_drive_changed_recurring_loop_reaches_exact_n_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        actor_id,
        profile_id,
        organization_id,
        claim_id,
        initial_execution,
        binding,
        store,
    ) = _google_bound_v1(monkeypatch)

    prior_document_id = UUID(initial_execution["document_id"])
    binding_id = UUID(binding["id"])

    release = client.post(
        f"/api/v1/claims/{claim_id}/documents/{prior_document_id}/processing/release",
        headers=_headers(actor_id),
        json={
            "request_key": "ak-google-v1-phase-z-release",
            "reason": (
                "Release only the exact Google Drive v1 canonical Evidence "
                "version for local deterministic processing."
            ),
        },
    )
    assert release.status_code == 201, release.text
    assert release.json()["status"] == "active"

    scheduled = _authorize_schedule(
        str(profile_id),
        str(binding_id),
        actor_id,
        key="ak-google-recurring-schedule",
        cadence="hourly",
        effective_at="2026-09-22T00:00:00Z",
        headers=_mfa_headers(actor_id),
    )
    assert scheduled.status_code == 201, scheduled.text

    changed_v4 = _GoogleMetadataAdapter(
        body=_BODY_V4,
        version=_VERSION_V4,
        modified_at=_MODIFIED_V4,
    )
    register_external_document_source_change_detection_adapter(
        "google_drive",
        "drive_file_metadata_read_v1",
        changed_v4,
    )

    with TestingSessionLocal() as db:
        dispatch = dispatch_next_due_tick(
            db,
            worker_id="ak-google-scheduler",
            now=datetime(2026, 9, 22, 2, 0, tzinfo=UTC),
        )
        assert dispatch is not None
        dispatch_id = dispatch.id

    with TestingSessionLocal() as db:
        observation, _consumption, outcome = consume_due_tick_dispatch(
            db,
            dispatch_id=dispatch_id,
            service_executor_id="external-evidence-observer-v1",
            now=datetime(2026, 9, 22, 2, 0, tzinfo=UTC),
        )
        assert outcome == "consumed"
        assert observation.provider_kind == "google_drive"
        assert observation.result_status == "changed"
        assert observation.remote_write_performed is False
        assert observation.remote_delete_performed is False
        assert observation.ai_executed is False

        handoff, projected = project_observation_review_handoff(
            db,
            observation_execution_id=observation.id,
            projector_id="ak-google-review-projector-v1",
            now=datetime(2026, 9, 22, 2, 1, tzinfo=UTC),
        )
        assert handoff is not None
        assert projected == "projected"
        handoff_id = handoff.id

    with TestingSessionLocal() as db:
        decision, refresh_authorization, outcome = decide_observation_review_handoff(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            handoff_id=handoff_id,
            decided_by_id=actor_id,
            request_key="ak-google-ag-approve",
            decision_kind="approve_refresh",
            decision_reason=(
                "Human reviewer authorizes one exact Google Drive changed-item "
                "refresh after verifying the recurring observation lineage."
            ),
            now=datetime(2026, 9, 22, 2, 2, tzinfo=UTC),
        )
        assert outcome == "decided"
        assert decision.decision_kind == "approve_refresh"
        assert decision.ai_executed is False
        assert refresh_authorization is not None
        refresh_authorization_id = refresh_authorization.id

    refresh_read = _GoogleReadAdapter(content=_BODY_V4, version=_VERSION_V4)
    register_external_document_source_remote_file_content_read_adapter(
        "google_drive",
        "drive_file_media_read_v1",
        refresh_read,
    )
    register_external_document_source_remote_content_staging_store(store)

    with TestingSessionLocal() as db:
        refresh, outcome = execute_observation_refresh_authorization(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            authorization_id=refresh_authorization_id,
            requested_by_id=actor_id,
            request_key="ak-google-ah-refresh",
            request_reason=(
                "Read and stage the separately approved exact Google Drive "
                "changed version without canonical Evidence mutation."
            ),
            now=datetime(2026, 9, 22, 2, 3, tzinfo=UTC),
        )
        assert outcome == "completed"
        assert refresh.result_status == "staged_refresh_verified"
        assert refresh.remote_write_performed is False
        assert refresh.remote_delete_performed is False
        assert refresh.ai_executed is False
        refresh_id = refresh.id

    with TestingSessionLocal() as db:
        authorization, outcome = authorize_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            refresh_execution_id=refresh_id,
            authorized_by_id=actor_id,
            request_key="ak-google-ai-authorize",
            authorization_reason=(
                "Authorize only the exact verified Google Drive staged refresh "
                "for the later canonical N+1 admission boundary."
            ),
            now=datetime(2026, 9, 22, 2, 4, tzinfo=UTC),
        )
        assert outcome == "authorized"
        assert authorization.ai_executed is False
        admission_authorization_id = authorization.id

    _enable_clean_aj(monkeypatch)
    with TestingSessionLocal() as db:
        execution, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="ak-google-aj-admit",
            execution_reason=_AJ_EXEC_REASON,
        )
        assert outcome == "admitted"
        assert execution.prior_document_id == prior_document_id
        assert execution.prior_version_number == 1
        assert execution.new_version_number == 2
        assert execution.remote_write_performed is False
        assert execution.remote_delete_performed is False
        assert execution.processing_enqueued is False
        assert execution.ai_executed is False

        prior = db.get(Document, prior_document_id)
        current = db.get(Document, execution.new_document_id)
        assert prior is not None and current is not None
        assert prior.is_current is False
        assert current.is_current is True
        assert current.version_number == 2
        assert current.supersedes_document_id == prior.id
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

        releases = (
            db.query(ExternalDocumentSourceProcessingRelease)
            .filter(
                ExternalDocumentSourceProcessingRelease.organization_id
                == organization_id,
                ExternalDocumentSourceProcessingRelease.binding_id == binding_id,
            )
            .all()
        )
        assert len(releases) == 1
        assert releases[0].document_id == prior_document_id
        assert releases[0].document_version_number == 1
        assert releases[0].status == "active"

        overview = build_external_document_source_operator_overview(
            db,
            organization_id=organization_id,
        )
        family = next(row for row in overview.families if row.binding_id == binding_id)
        assert family.provider_kind == "google_drive"
        assert family.current_document_id == execution.new_document_id
        assert family.current_version_number == 2
        assert family.processing_release_required is True
        assert family.refresh_execution_required is False
        assert family.admission_authorization_required is False
        assert family.admission_execution_required is False
        assert len(family.version_history) == 2
        assert [row.version_number for row in family.version_history] == [1, 2]
        assert family.version_history[0].is_current is False
        assert family.version_history[0].processing_release_required is False
        assert family.version_history[1].is_current is True
        assert family.version_history[1].processing_release_required is True

        assert (
            db.query(ExternalDocumentSourceObservationReviewHandoff).count()
            == 1
        )
        assert (
            db.query(ExternalDocumentSourceObservationReviewDecision).count()
            == 1
        )
        assert (
            db.query(ExternalDocumentSourceObservationRefreshExecution).count()
            == 1
        )
        assert (
            db.query(
                ExternalDocumentSourceObservationRefreshAdmissionAuthorization
            ).count()
            == 1
        )
        assert db.query(DocumentProcessingJob).count() == 0

        execution_id = execution.id
        new_document_id = execution.new_document_id

    assert changed_v4.calls == 1
    assert refresh_read.calls == 1

    with TestingSessionLocal() as db:
        replay, outcome = execute_observation_refresh_admission(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            binding_id=binding_id,
            authorization_id=admission_authorization_id,
            executed_by_id=actor_id,
            request_key="ak-google-aj-admit",
            execution_reason=_AJ_EXEC_REASON,
        )
        assert outcome == "replayed"
        assert replay.id == execution_id
        assert replay.new_document_id == new_document_id
        assert db.query(DocumentProcessingJob).count() == 0
